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
        self._fail_count: dict[str, int] = {}

    # ── Monitoring loop ───────────────────────────────────────────────────

    def check(self):
        if not self.is_enabled:
            self._debug('Web: Module disabled, skipping check.', DebugLevel.info)
            return self.dict_return

        items = []
        for key, value in self.get_conf('list', {}).items():
            is_enabled = self._DEFAULTS['enabled']
            match value:
                case bool():
                    is_enabled = value
                    url, scheme, verify_ssl = key, 'https', True
                    self._debug(
                        f'[Deprecate] Check: {url} — Enabled: {is_enabled}. Update format.',
                        DebugLevel.warning,
                    )
                case dict():
                    is_enabled = value.get('enabled', is_enabled)
                    url        = (value.get('url', '') or '').strip() or key
                    scheme     = (value.get('scheme', '') or 'https').strip()
                    verify_ssl = bool(value.get('verify_ssl', True))
                    self._debug(f'Check: {url} — Enabled: {is_enabled}', DebugLevel.info)
                case _:
                    url, scheme, verify_ssl = key, 'https', True
                    self._debug(
                        f'Check: {url} — Unknown format, using defaults.', DebugLevel.warning
                    )

            if is_enabled:
                items.append((key, url, verify_ssl, scheme))

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.get_conf('threads', self._default_threads)
        ) as executor:
            futures = {
                executor.submit(self._web_check, name, url, verify_ssl, scheme): name
                for name, url, verify_ssl, scheme in items
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f'Check: {name} — Exception: {exc}', DebugLevel.error)
                    self.dict_return.set(name, False, f'Web: {name} — Error: {exc} 💥')

        super().check()
        return self.dict_return

    # ── Per-item check ────────────────────────────────────────────────────

    def _web_check(self, name: str, url: str, verify_ssl: bool = True, scheme: str = 'https') -> None:
        code_exp  = (
            self.get_conf_in_list('code', name, 0)
            or self.get_conf('code', self._MODULE_DEFAULTS['code'])
        )
        timeout = (
            self.get_conf_in_list('timeout', name, 0)
            or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])
        )
        method           = str(self.get_conf_in_list('method', name, 'GET') or 'GET').upper()
        check_content    = bool(self.get_conf_in_list('check_content', name, False))
        content_contains = str(self.get_conf_in_list('content_contains', name, '') or '')
        auth_enabled     = bool(self.get_conf_in_list('auth_enabled', name, False))
        auth_user        = str(self.get_conf_in_list('auth_user', name, '') or '') if auth_enabled else ''
        auth_password    = str(self.get_conf_in_list('auth_password', name, '') or '') if auth_enabled else ''
        alert            = int(self.get_conf_in_list('alert', name, 1) or 1)

        code, detail = self._web_request(
            url, timeout, verify_ssl, scheme,
            method, check_content, content_contains, auth_user, auth_password,
        )
        status = (code == code_exp)

        # Consecutive-failure threshold: suppress alert until 'alert' failures accumulate
        if not status:
            self._fail_count[name] = self._fail_count.get(name, 0) + 1
        else:
            self._fail_count[name] = 0
        effective = status or (self._fail_count.get(name, 0) < alert)

        icon      = '🔼' if effective else '🔽'
        s_message = f'Web: {name} {icon}'
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
        from lib.net_guard import validate_external_url  # noqa: PLC0415
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
        # When URL is empty, fall back to _item_key (injected by the action handler
        # from the item's dict key — used when placeholder: "__key__" is the URL).
        url = (config.get('url') or '').strip() or (config.get('_item_key') or '').strip()
        if not url:
            return {'ok': False, 'message': 'URL is required'}

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
