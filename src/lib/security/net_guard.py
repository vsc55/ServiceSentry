#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSRF guard for user-supplied URLs fetched server-side.

ServiceSentry is a monitoring tool, so requests to private/internal devices
(RFC1918 10/8, 172.16/12, 192.168/16) are a *legitimate* use case and are NOT
blocked.  What we do block is what is never a legitimate monitoring target and
is a classic SSRF escalation vector:

* non-HTTP(S) schemes — ``file://``, ``ftp://``, ``data://``, ``gopher://`` …
  (e.g. ``file:///etc/passwd`` local file read)
* the link-local range 169.254.0.0/16, which includes the cloud
  instance-metadata endpoint 169.254.169.254 (IAM credential theft)
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def validate_external_url(url: str, *, allowed_schemes=('http', 'https')) -> str | None:
    """Validate a user-supplied URL for safe server-side fetching.

    Returns ``None`` if the URL is acceptable, or a short human-readable reason
    string if it must be rejected.
    """
    if not url or not isinstance(url, str):
        return 'empty URL'
    try:
        parsed = urlparse(url.strip())
    except (ValueError, TypeError):
        return 'malformed URL'

    scheme = (parsed.scheme or '').lower()
    if scheme not in allowed_schemes:
        return f'scheme {scheme or "(none)"!r} not allowed (use http/https)'

    host = parsed.hostname
    if not host:
        return 'missing host'

    # Resolve every address the host maps to and reject link-local / metadata.
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        # Can't resolve — let the actual request fail rather than guess.
        return None
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split('%')[0])  # strip scope id
        except ValueError:
            continue
        if ip.is_link_local:          # 169.254.0.0/16 + fe80::/10 (cloud metadata)
            return 'link-local / metadata address blocked'
    return None


# ── Redirects ─────────────────────────────────────────────────────────────────────────────
# Validating the URL somebody typed is half the guard: urllib and requests both follow a
# 3xx by themselves, and the place a redirect points at was never looked at. A server of
# one's own that answers `302 Location: http://169.254.169.254/…` turned a checked URL into
# a request to the metadata endpoint. Each hop is validated as the first one was.

#: How many redirects a guarded fetch follows before giving up — the built-in default; the
#: running value is `web_admin|max_redirects` (env `SS_MAX_REDIRECTS`), set per process by
#: :func:`set_max_redirects` and read with :func:`max_redirects`.
MAX_REDIRECTS = 10
_max_redirects = MAX_REDIRECTS


def max_redirects() -> int:
    """The redirect ceiling in force in this process."""
    return _max_redirects


def set_max_redirects(value) -> None:
    """Set the ceiling from config: an int in 0..30, anything else leaves the default."""
    global _max_redirects                               # pylint: disable=global-statement
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = MAX_REDIRECTS
    _max_redirects = n if 0 <= n <= 30 else MAX_REDIRECTS


def max_redirects_from(web_admin_section: dict | None) -> int:
    """The ceiling a process without the web admin's runtime attributes should use: the
    environment override when it is a valid value, else the saved `web_admin` section."""
    import os                                           # noqa: PLC0415
    raw = os.environ.get('SS_MAX_REDIRECTS', '').strip()
    if raw.isdigit() and 0 <= int(raw) <= 30:
        return int(raw)
    from lib.config.spec import cfg_get                 # noqa: PLC0415
    return cfg_get(web_admin_section or {}, 'web_admin|max_redirects')


class RedirectBlocked(OSError):
    """A redirect pointed somewhere :func:`validate_external_url` refuses."""


def guarded_opener():
    """A ``urllib`` opener that validates every redirect target before following it."""
    import urllib.request                               # noqa: PLC0415

    class _Revalidating(urllib.request.HTTPRedirectHandler):
        max_redirections = max_redirects()

        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913
            reason = validate_external_url(newurl)
            if reason:
                raise RedirectBlocked(f'redirect blocked: {reason}')
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(_Revalidating)


def guarded_get(url: str, *, getter=None, max_redirects: int | None = None, **kwargs):
    """``requests.get`` that follows redirects by hand, validating each target.

    *getter* is the ``get`` to call (``requests.get`` by default) — passed by the caller
    so a module that imports ``requests`` under its own name keeps one name to mock.
    Raises :class:`RedirectBlocked` for a refused hop or too many of them."""
    from urllib.parse import urljoin                    # noqa: PLC0415
    if getter is None:
        import requests                                 # noqa: PLC0415
        getter = requests.get
    kwargs['allow_redirects'] = False
    current = url
    hops = _max_redirects if max_redirects is None else max_redirects
    for _ in range(hops + 1):
        reason = validate_external_url(current)
        if reason:
            raise RedirectBlocked(f'blocked: {reason}')
        resp = getter(current, **kwargs)
        status = int(getattr(resp, 'status_code', 0) or 0)
        location = (getattr(resp, 'headers', None) or {}).get('Location')
        if status in (301, 302, 303, 307, 308) and location:
            current = urljoin(current, location)
            continue
        return resp
    raise RedirectBlocked('too many redirects')
