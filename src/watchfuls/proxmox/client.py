#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry - Proxmox VE watchful: talking to the API.
#
"""One HTTPS conversation with a Proxmox node, and the failover between several.

No external dependencies: urllib + ssl, the same pattern as the ``web`` watchful.
Authentication is either an API token (``Authorization: PVEAPIToken=<id>=<secret>``) or
username+password, where the login ticket goes into the ``PVEAuthCookie`` cookie.

A check decides WHAT to ask the cluster and what the answer means. This decides how to ask
it, and what to do when the node you asked is the one that is down - which is why
``_connect_failover`` exists: a cluster with a dead node must still answer about itself.
"""

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request


class PveError(Exception):
    """Proxmox API error carrying the HTTP status code (0 = connection error)."""

    def __init__(self, code: int, msg: str = ''):
        self.code = code
        self.msg = msg
        super().__init__(f'HTTP {code}: {msg}' if code else (msg or 'connection error'))


def _split_hosts(value: str) -> list:
    """Split a host field into a candidate address list (comma/space/newline) — a
    Proxmox cluster has several nodes, so the check can fail over between them."""
    return [h for h in re.split(r'[,\s]+', str(value or '').strip()) if h]


class PveClient:
    """Connect, request, and fail over. Mixed into ``Watchful``."""

    # ── API client (stateless; usable from the test_connection classmethod) ─

    @staticmethod
    def _request(url: str, *, method: str = 'GET', data: dict = None,
                 headers: dict = None, verify_ssl: bool = True,
                 timeout: int = 10) -> tuple[int, str]:
        """Low-level HTTPS request. Returns (status_code, body_text).

        Raises ``PveError`` on HTTP error (with the status code) or on a
        connection/transport error (code 0).
        """
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('User-Agent', 'ServiceSentry/1.0')
        req.add_header('Accept', 'application/json')
        for k, v in (headers or {}).items():
            req.add_header(k, v)

        kwargs: dict = {}
        if not verify_ssl and url.startswith('https://'):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs['context'] = ctx
        try:
            with urllib.request.urlopen(req, timeout=timeout, **kwargs) as resp:
                return resp.status, resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read().decode('utf-8', errors='replace')
            except Exception:  # pylint: disable=broad-except
                pass
            raise PveError(exc.code, (detail or str(exc))[:300]) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise PveError(0, str(getattr(exc, 'reason', exc))) from exc

    @classmethod
    def _connect(cls, host: str, port: int, verify_ssl: bool, timeout: int,
                 auth_method: str, token_id: str, token_secret: str,
                 username: str, password: str) -> dict:
        """Build a connection context (base URL + auth headers). For password
        auth it logs in to obtain a ticket. Raises ``PveError`` on failure."""
        base = f'https://{host}:{port}/api2/json'
        # SSRF guard (blocks link-local/metadata; private hosts allowed) like web.
        from lib.security.net_guard import validate_external_url  # noqa: PLC0415
        reason = validate_external_url(f'https://{host}:{port}')
        if reason:
            raise PveError(0, f'Bloqueado: {reason}')

        if auth_method == 'password':
            if not username:
                raise PveError(0, 'usuario requerido')
            code, text = cls._request(
                f'{base}/access/ticket', method='POST',
                data={'username': username, 'password': password},
                verify_ssl=verify_ssl, timeout=timeout,
            )
            ticket = ((json.loads(text or '{}') or {}).get('data') or {}).get('ticket')
            if not ticket:
                raise PveError(code, 'login fallido')
            headers = {'Cookie': f'PVEAuthCookie={ticket}'}
        else:
            if not token_id or not token_secret:
                raise PveError(0, 'token_id y token_secret requeridos')
            headers = {'Authorization': f'PVEAPIToken={token_id}={token_secret}'}

        return {'base': base, 'headers': headers,
                'verify_ssl': verify_ssl, 'timeout': timeout}

    @classmethod
    def _pve_get(cls, conn: dict, path: str):
        """GET *path* and return the JSON ``data`` payload (raises on HTTP error)."""
        _code, text = cls._request(
            conn['base'] + path, headers=conn['headers'],
            verify_ssl=conn['verify_ssl'], timeout=conn['timeout'],
        )
        return (json.loads(text or '{}') or {}).get('data')

    def _connect_failover(self, candidates: list, port: int, verify_ssl: bool,
                          timeout: int, auth_args: tuple):
        """Try each candidate node address until one connects AND answers a cheap
        probe (``/version``); a Proxmox cluster has several nodes, so a single one
        being down must not blind the whole check.  Returns ``(conn, address)`` or
        raises the last error.  (Instance method so the per-check ``_pve_get`` and
        this probe share the same path — and the same test patch.)"""
        last = None
        for addr in candidates:
            try:
                conn = self._connect(addr, port, verify_ssl, timeout, *auth_args)
                self._pve_get(conn, '/version')   # probe: reachable + authenticated
                return conn, addr
            except Exception as exc:  # pylint: disable=broad-except
                last = exc
        raise last or PveError(0, 'sin nodos alcanzables')
