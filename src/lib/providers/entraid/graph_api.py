#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Graph — the HTTP surface the **monitor** side uses.

Why this exists next to :mod:`~lib.providers.entraid.auth`, which does the same job with
``requests``: the watchfuls run in the monitor, they are stubbed at exactly this layer by
their tests, and their timeout / TLS-context / proxy behaviour is urllib's.  Swapping
their transport would be a behaviour change dressed up as a refactor, so the monitor side
keeps ``urllib`` + ``ssl`` and the web side keeps ``requests``.

**This is the only module in the package on urllib.**  Everything else here
(``auth``, ``directory``, ``mail``, ``teams``, ``provisioning``) is the web side and uses
``requests``.

Consumed as a mixin, so a watchful gets the whole transport by inheriting it::

    class Watchful(MyChecks, EntraApi, ModuleBase):
        ...

Every method is a class/staticmethod on purpose: field pickers and page hooks run as
classmethods with no monitor behind them, so nothing here may depend on instance state.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from lib import APP_NAME
from lib.providers.entraid.client import (
    AUTHORITY, GRAPH_BASE, GRAPH_SCOPE, EntraApiError, api_error)

# How many pages of a collection to follow before giving up.  A bound, not a limit that
# should ever be reached: it exists so a malformed next-link cannot spin forever.
MAX_PAGES = 20

# Graph's own ceiling for a $batch request.  Not a tunable: asking for 21 is rejected.
BATCH_MAX = 20


def qs(params: dict) -> str:
    """A percent-encoded query string.

    Always encoded, never hand-built: an unencoded space in a query value makes the HTTP
    client refuse the URL outright (``URL can't contain control characters``), which is a
    lesson this codebase learnt in production.
    """
    return urllib.parse.urlencode(params)


def q(value) -> str:
    """A value safe to drop into a URL *path* segment (tenant ids, subscriptions, regions)."""
    return urllib.parse.quote(str(value or '').strip(), safe='')


def parse_dt(value):
    """A Microsoft ISO-8601 timestamp (``Z``-suffixed) → an aware datetime, or None.

    Returns None rather than raising: one unparseable credential must not take a whole
    expiry check down with it.  Naive values are assumed UTC, which is what these APIs
    mean when they omit the offset.
    """
    text = str(value or '').strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class EntraApi:
    """Transport, tokens and paging for any Microsoft API reached with an Entra token."""

    @staticmethod
    def _request(url: str, *, method: str = 'GET', data: dict = None,
                 json_body=None, headers: dict = None,
                 timeout: int = 15) -> tuple[int, str]:
        """Low-level HTTPS request → ``(status, body_text)``.  Raises EntraApiError.

        ``data`` is form-urlencoded (what the token endpoint wants); ``json_body`` is sent
        as JSON (what Graph and ARM writes want).  At most one of the two is used.
        """
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs.setdefault('Content-Type', 'application/json')
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
        else:
            body = None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('User-Agent', f'{APP_NAME}/1.0')
        for k, v in hdrs.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ssl.create_default_context()) as resp:
                return resp.status, resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read().decode('utf-8', errors='replace')
            except Exception:  # pylint: disable=broad-except
                pass
            raise EntraApiError(exc.code, api_error(detail) or str(exc)) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise EntraApiError(0, str(getattr(exc, 'reason', exc))) from exc

    @classmethod
    def _get_token(cls, tenant: str, client_id: str, secret: str, timeout: int,
                   scope: str = GRAPH_SCOPE) -> str:
        """App-only (client-credentials) access token.

        The scope is a parameter because Azure Resource Manager is a DIFFERENT audience
        from Microsoft Graph — a Graph token is rejected by ARM and vice versa.
        """
        url = f'{AUTHORITY}/{q(tenant)}/oauth2/v2.0/token'
        _code, text = cls._request(url, method='POST', timeout=timeout, data={
            'grant_type':    'client_credentials',
            'client_id':     client_id,
            'client_secret': secret,
            'scope':         scope,
        })
        data = json.loads(text or '{}') or {}
        tok = data.get('access_token')
        if not tok:
            raise EntraApiError(0, str(data.get('error_description') or 'no token')[:200])
        return tok

    @classmethod
    def _api_text(cls, base: str, token: str, path: str, timeout: int) -> str:
        """Raw body of an authenticated GET against *base* + *path*."""
        _code, text = cls._request(base + path, timeout=timeout,
                                   headers={'Authorization': 'Bearer ' + token})
        return text

    @classmethod
    def _graph_text(cls, token: str, path: str, timeout: int) -> str:
        return cls._api_text(GRAPH_BASE, token, path, timeout)

    @classmethod
    def _graph_json(cls, token: str, path: str, timeout: int) -> dict:
        return json.loads(cls._graph_text(token, path, timeout) or '{}') or {}

    @classmethod
    def _graph_batch(cls, token: str, paths: list, timeout: int) -> dict:
        """Many GETs in as few round-trips as Graph allows → ``{path: body}``.

        Per-object questions about a tenant are N requests, and N sequential HTTPS
        round-trips is exactly how a check ends up timing out on a large one.  ``$batch``
        takes 20 at a time, so 200 objects cost 10 requests instead of 200.

        Only the sub-requests that answered 200 come back: one object that 404s or is
        forbidden is dropped from the result rather than costing the whole batch.  A batch
        request that fails outright raises, like any other call here.
        """
        out: dict = {}
        for start in range(0, len(paths), BATCH_MAX):
            chunk = paths[start:start + BATCH_MAX]
            _code, text = cls._request(
                GRAPH_BASE + '/$batch', method='POST', timeout=timeout,
                headers={'Authorization': 'Bearer ' + token},
                json_body={'requests': [{'id': str(n), 'method': 'GET', 'url': p}
                                        for n, p in enumerate(chunk)]})
            for resp in ((json.loads(text or '{}') or {}).get('responses') or []):
                try:
                    n = int(resp.get('id'))
                except (TypeError, ValueError):
                    continue
                if int(resp.get('status') or 0) == 200 and 0 <= n < len(chunk):
                    out[chunk[n]] = resp.get('body') or {}
        return out

    @classmethod
    def _paged(cls, token: str, url: str, timeout: int, *,
               next_key: str = '@odata.nextLink', base: str = GRAPH_BASE,
               max_pages: int = MAX_PAGES) -> list:
        """Every page of a collection → the concatenated ``value`` lists.

        Graph pages at 100 items by default and ARM pages large result sets too, so a
        single-page read silently reports a slice of the answer — exactly the kind of
        partial truth a monitoring check must never tell.

        *url* may be a path (prefixed with *base*) or absolute; the next-links these APIs
        return are absolute, so following them needs no prefixing.  ``next_key`` differs
        by surface: Graph says ``@odata.nextLink``, ARM says ``nextLink``.
        """
        out, pages = [], 0
        current = url if url.startswith('http') else base + url
        while current and pages < max_pages:
            _code, text = cls._request(current, timeout=timeout,
                                       headers={'Authorization': 'Bearer ' + token})
            data = json.loads(text or '{}') or {}
            out.extend(v for v in (data.get('value') or []) if isinstance(v, dict))
            current = str(data.get(next_key) or '')
            pages += 1
        return out
