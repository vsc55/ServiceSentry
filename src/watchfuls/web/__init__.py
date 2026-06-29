#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry — Web watchful
#
"""Watchful to check HTTP/HTTPS endpoint availability and response content."""

import base64
import concurrent.futures
import json
import os
import ssl
import urllib.error
import urllib.request

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(
    open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8')
)


class Watchful(ModuleBase):
    """Monitors HTTP/HTTPS endpoints: status code, optional content check, basic auth."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {
        k: v['default']
        for k, v in _SCHEMA['list'].items()
        if isinstance(v, dict) and 'default' in v
    }
    _MODULE_DEFAULTS = {
        k: v['default']
        for k, v in _SCHEMA['__module__'].items()
        if isinstance(v, dict) and 'default' in v
    }

    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'test_connection'})

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    # ── Monitoring loop ───────────────────────────────────────────────────

    def check(self):
        if not self.is_enabled:
            self._debug('Web: Module disabled, skipping check.', DebugLevel.info)
            return self.dict_return

        names = []
        for key, value in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                if value:
                    names.append(key)   # legacy: key is the url, bool = enabled
                continue
            it = self._resolved_item(key)
            if it.get('enabled', self._DEFAULTS['enabled']):
                names.append(key)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, self.module_default('threads', self._default_threads))
        ) as executor:
            futures = {executor.submit(self._web_check, name): name for name in names}
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f'Check: {name} — Exception: {exc}', DebugLevel.error)
                    _lbl = self.get_conf(['list', name, 'label'], '') or name
                    self.dict_return.set(name, False, f'Web: {_lbl} — Error: {exc} 💥')

        super().check()
        return self.dict_return

    # ── Per-item check ────────────────────────────────────────────────────

    def _resolved_item(self, key: str) -> dict:
        """Item config for *key* with any referenced host merged in (no-op when
        inline).  Cached per check cycle (the monitor builds a fresh instance
        each cycle)."""
        cache = self.__dict__.setdefault('_resolved_items', {})
        if key not in cache:
            raw = self.get_conf(['list', key], {})
            cache[key] = self.resolve_host(raw) if isinstance(raw, dict) else {}
        return cache[key]

    @staticmethod
    def _compose_target(server: str, port, path: str = '') -> str:
        """Build the request target (host[:port][/path], scheme-less) from the
        host-centric fields.  The scheme is applied separately by ``_web_request``.

        * ``port`` is appended only when it is a non-standard port — 80/443 are
          implied by the scheme and omitted, as is a blank/0 port.
        * ``server`` may already carry a scheme (``https://…``, legacy data) or an
          embedded ``:port`` — in either case it is used verbatim (no port added).
        """
        server = (server or '').strip().rstrip('/')
        target = server
        if server and '://' not in server:
            try:
                p = int(port or 0)
            except (TypeError, ValueError):
                p = 0
            host_part = server.split('/', 1)[0]
            if p and p not in (80, 443) and ':' not in host_part:
                if '/' in server:
                    host, rest = server.split('/', 1)
                    target = f'{host}:{p}/{rest}'
                else:
                    target = f'{server}:{p}'
        path = (path or '').strip()
        if path:
            target = target.rstrip('/') + '/' + path.lstrip('/')
        return target

    def _web_check(self, name: str) -> None:
        it = self._resolved_item(name)
        # Host-centric: a host's address fills 'server'; 'port'/'path' compose the
        # target.  Legacy items keep the address in 'url' (pre-server/port split) —
        # honoured as a fallback so existing checks keep working until re-saved.
        server = (it.get('server', '') or '').strip() or (it.get('url', '') or '').strip()
        path   = (it.get('path', '') or '').strip()
        url    = self._compose_target(server, it.get('port', 0), path) or name
        # Display name: the editable label (e.g. "NS1 - https://api…"); key is a UID.
        label = (it.get('label', '') or '').strip() or url
        scheme       = (it.get('scheme', '') or 'https').strip()
        verify_ssl   = bool(it.get('verify_ssl', True))
        code_exp     = it.get('code', 0) or self.get_conf('code', self._MODULE_DEFAULTS['code'])
        timeout      = it.get('timeout', 0) or self.module_default('timeout', self._MODULE_DEFAULTS['timeout'])
        method           = str(it.get('method', 'GET') or 'GET').upper()
        check_content    = bool(it.get('check_content', False))
        content_contains = str(it.get('content_contains', '') or '')
        auth_enabled     = bool(it.get('auth_enabled', False))
        auth_user        = str(it.get('auth_user', '') or '') if auth_enabled else ''
        auth_password    = str(it.get('auth_password', '') or '') if auth_enabled else ''
        # Consecutive-failure threshold: blank/0 inherits the module-level value
        # (Configuration > Modules), then the module schema default — like ping.
        alert            = int(it.get('alert', 0)
                               or self.module_default('alert', self._MODULE_DEFAULTS['alert']))

        code, detail = self._web_request(
            url, timeout, verify_ssl, scheme,
            method, check_content, content_contains, auth_user, auth_password,
        )
        status = (code == code_exp)

        # Consecutive-failure threshold: suppress alert until 'alert' failures
        # accumulate.  Persisted via fail_streak (survives cycles/processes).
        streak = self.fail_streak(name, not status)
        effective = status or streak < alert

        icon      = '🔼' if effective else '🔽'
        s_message = f'Web: {label} {icon}'
        if not status:
            s_message += f' [{detail}]'

        self.dict_return.set(name, effective, s_message, False,
                             {'code': code, 'detail': detail})
        if self.check_status(effective, self.name_module, name):
            self.send_message(s_message, effective)

    # ── HTTP request (shared by check loop and test_connection) ───────────

    @staticmethod
    def _web_request(
        url:              str,
        timeout:          int  = 15,
        verify_ssl:       bool = True,
        scheme:           str  = 'https',
        method:           str  = 'GET',
        check_content:    bool = False,
        content_contains: str  = '',
        auth_user:        str  = '',
        auth_password:    str  = '',
    ) -> tuple[int, str]:
        """Perform an HTTP request. Returns (status_code, detail).

        Returns code 0 on connection error (URLError / OSError).
        """
        target = url if '://' in url else f'{scheme}://{url}'
        # SSRF guard: block non-HTTP(S) schemes and link-local/metadata targets.
        # Private/internal hosts are intentionally allowed (legitimate monitoring).
        from lib.security.net_guard import validate_external_url  # noqa: PLC0415
        _reason = validate_external_url(target)
        if _reason:
            return 0, f'Blocked: {_reason}'
        try:
            req = urllib.request.Request(target, method=method.upper())
            req.add_header('User-Agent', 'ServiceSentry/1.0')
            if auth_user:
                token = base64.b64encode(
                    f'{auth_user}:{auth_password}'.encode()
                ).decode()
                req.add_header('Authorization', f'Basic {token}')

            kwargs: dict = {}
            if not verify_ssl and target.startswith('https://'):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                kwargs['context'] = ctx

            with urllib.request.urlopen(req, timeout=timeout, **kwargs) as resp:
                code = resp.status
                if check_content and content_contains and method.upper() != 'HEAD':
                    body = resp.read(131072).decode('utf-8', errors='replace')
                    if content_contains not in body:
                        return code, f'Content not found: {content_contains!r}'
                return code, f'HTTP {code}'

        except urllib.error.HTTPError as exc:
            return exc.code, f'HTTP {exc.code}'
        except (urllib.error.URLError, OSError) as exc:
            return 0, str(exc)

    # ── Web action ────────────────────────────────────────────────────────

    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """POST /api/v1/watchfuls/web/test_connection

        Receives the item fields from the UI form and runs a live request.
        Returns {"ok": bool, "message": str}.
        """
        # Compose from server/port/path (host-centric).  Fall back to legacy 'url'
        # and then to _item_key (the item's dict key, injected by the action
        # handler) so older configs and key-as-address checks still test.
        server = ((config.get('server') or '').strip()
                  or (config.get('url') or '').strip()
                  or (config.get('_item_key') or '').strip())
        if not server:
            return {'ok': False, 'message': 'Server is required'}
        url = cls._compose_target(server, config.get('port', 0), config.get('path', ''))

        code_exp  = int(config.get('code')    or cls._MODULE_DEFAULTS.get('code',    200))
        timeout   = int(config.get('timeout') or cls._MODULE_DEFAULTS.get('timeout', 15))
        auth_enabled = bool(config.get('auth_enabled', False))

        code, detail = cls._web_request(
            url              = url,
            timeout          = timeout,
            verify_ssl       = bool(config.get('verify_ssl', True)),
            scheme           = str(config.get('scheme') or 'https'),
            method           = str(config.get('method') or 'GET').upper(),
            check_content    = bool(config.get('check_content', False)),
            content_contains = str(config.get('content_contains') or ''),
            auth_user        = str(config.get('auth_user') or '') if auth_enabled else '',
            auth_password    = str(config.get('auth_password') or '') if auth_enabled else '',
        )
        ok = (code == code_exp)
        return {'ok': ok, 'message': detail if not ok else f'{detail} (expected {code_exp})'}
