#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Internal fail2ban wiring for WebAdmin.

The jail/counter *logic* lives in :mod:`lib.security.ipban` (framework-free) and
its persistence in :mod:`lib.stores.ipbans` / :mod:`lib.stores.ip_whitelist`.
This mixin is only the Flask-side glue mixed into :class:`WebAdmin`:

  * create the shared :class:`~lib.security.ipban.IpBanManager` + its stores,
  * push config into it (:meth:`_configure_ipban`),
  * feed it offenses from request outcomes (:meth:`_ipban_offense` / the
    after-request capture) and block jailed IPs up-front (:meth:`_ipban_gate_response`).

The host WebAdmin provides ``_db_connector``, ``_t``, ``_audit_system`` and the
``_IPBAN_*`` runtime attributes (defaults declared here).
"""

from __future__ import annotations

import time

from flask import g, jsonify, make_response, render_template, request

from lib.config.spec import cfg_default as _cfg_default


class _IpBanMixin:
    """fail2ban glue: shared manager + request gate + offense capture."""

    # ── runtime settings (overridden by saved config / env at startup) ──────────
    _IPBAN_ENABLED = _cfg_default('web_admin|ipban_enabled')
    _IPBAN_AUTH_THRESHOLD = _cfg_default('web_admin|ipban_auth_threshold')
    _IPBAN_AUTH_WINDOW = _cfg_default('web_admin|ipban_auth_window_secs')
    _IPBAN_AUTHZ_THRESHOLD = _cfg_default('web_admin|ipban_authz_threshold')
    _IPBAN_AUTHZ_WINDOW = _cfg_default('web_admin|ipban_authz_window_secs')
    _IPBAN_DURATIONS = _cfg_default('web_admin|ipban_durations')
    _IPBAN_PERMANENT_AFTER = _cfg_default('web_admin|ipban_permanent_after')
    _IPBAN_WHITELIST = _cfg_default('web_admin|ipban_whitelist')

    # HTTP block actions the web service can produce (see lib.security.ipban_services).
    _WEB_BLOCK_ACTIONS = ('page', 'minimal', 'reject', 'json')

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def _init_ipban(self) -> None:
        """Create the shared jail manager + its stores on the general connector, so
        counting/ban state is persistent and shared across every process. Called from
        the entity-store init (after ``_db_connector`` exists)."""
        from lib.stores.ipbans import IpBanStore              # noqa: PLC0415
        from lib.stores.ip_whitelist import IpWhitelistStore  # noqa: PLC0415
        from lib.security.ipban import IpBanManager           # noqa: PLC0415
        from lib.security.ipban_services import IpBanServiceRegistry  # noqa: PLC0415
        self._ipban_store = IpBanStore(self._db_connector)
        self._ip_whitelist_store = IpWhitelistStore(self._db_connector)
        self._ipban_store.prune(time.time())
        self._ipban = IpBanManager(store=self._ipban_store, notify=self._ipban_notify)
        # Service capability registry: each exposed service declares its ports +
        # supported block actions, so nothing about them is hardcoded. Web registers
        # itself here; syslog registers from its own manager when it (re)starts.
        self._ipban_services = IpBanServiceRegistry(persist=self._ipban_store.set_service_action)
        self._ipban_services.load_actions(self._ipban_store.service_actions())
        self._register_web_service()

    def _register_web_service(self) -> None:
        """Declare the web admin as a fail2ban-aware service (its port + the HTTP
        block actions it can produce)."""
        reg = getattr(self, '_ipban_services', None)
        if reg is None:
            return
        reg.register(id='web', label_key='ipban_svc_web',
                     supports=self._WEB_BLOCK_ACTIONS, default='page',
                     endpoints=[{'port': int(getattr(self, '_WEB_PORT', 0) or 0),
                                 'proto': 'tcp', 'kind': 'http'}])

    def _apply_ipban_config(self, wa_cfg: dict) -> None:
        """Apply the fail2ban string fields (no_rule → not in INT/BOOL rules) from a
        ``web_admin`` config dict, then push everything into the live manager. Called
        on boot and after a config save."""
        if isinstance(wa_cfg.get('ipban_durations'), str):
            self._IPBAN_DURATIONS = wa_cfg['ipban_durations']
        if isinstance(wa_cfg.get('ipban_whitelist'), str):
            self._IPBAN_WHITELIST = wa_cfg['ipban_whitelist']
        self._register_web_service()   # refresh the web endpoint (port may have changed)
        self._configure_ipban()

    def _configure_ipban(self) -> None:
        """Push the current fail2ban settings into the shared jail manager.  The
        whitelist = programmatic/env CSV ∪ the UI-managed store (with descriptions) ∪
        loopback (always merged inside configure()), so the app never jails its own
        local hops."""
        mgr = getattr(self, '_ipban', None)
        if mgr is None:
            return
        store = getattr(self, '_ip_whitelist_store', None)
        store_vals = store.values() if store is not None else []
        mgr.configure(
            enabled=self._IPBAN_ENABLED,
            auth_threshold=self._IPBAN_AUTH_THRESHOLD,
            auth_window=self._IPBAN_AUTH_WINDOW,
            authz_threshold=self._IPBAN_AUTHZ_THRESHOLD,
            authz_window=self._IPBAN_AUTHZ_WINDOW,
            durations=self._IPBAN_DURATIONS,
            permanent_after=self._IPBAN_PERMANENT_AFTER,
            whitelist=self._IPBAN_WHITELIST,
            extra_whitelist=store_vals,
        )

    def _ipban_notify(self, action: str, ip: str, info: dict) -> None:
        """Audit an automatic/manual ban lifecycle event (banned / escalated / lifted)."""
        try:
            detail = {'ip': ip, 'reason': info.get('reason', ''),
                      'level': info.get('level'), 'by': info.get('by', 'system')}
            detail['permanent'] = info.get('until') is None
            self._audit_system(f'ip_{action}',
                               detail={k: v for k, v in detail.items() if v is not None})
        except Exception:  # pylint: disable=broad-except
            pass

    # ── request-time helpers ────────────────────────────────────────────────────
    @staticmethod
    def _client_ip() -> str:
        """The request's client IP (already proxy-corrected by ProxyFix when
        ``proxy_count`` > 0), used as the fail2ban key."""
        return request.remote_addr or ''

    def _ipban_offense(self, category: str) -> None:
        """Register one fail2ban offense for the current request's IP, guarded so a
        single request is counted at most once (an explicit call here suppresses the
        generic 401/403 capture in the after-request hook)."""
        mgr = getattr(self, '_ipban', None)
        if mgr is None or getattr(g, '_ipban_counted', False):
            return
        g._ipban_counted = True
        try:
            mgr.register_offense(self._client_ip(), category)
        except Exception:  # pylint: disable=broad-except
            pass

    def _ipban_block_reason(self, retry: int) -> str:
        """The block message + a "try again in X" / "permanent" sentence."""
        if retry and retry < 31_536_000:
            mins = max(1, (int(retry) + 59) // 60)
            when = self._t('ipban_blocked_retry').replace('{}', f'~{mins} min')
        else:
            when = self._t('ipban_blocked_permanent')
        return (self._t('ip_banned') + ' ' + when).strip()

    def _ipban_block_page(self, retry: int) -> str:
        """The 'page' block action: the app's styled error page (same look as every
        other error) with the ban-specific reason + remaining time. Static assets are
        gate-exempt so the CSS loads. Falls back to a self-contained page on failure."""
        desc = self._ipban_block_reason(retry)
        try:
            return render_template('error.html', code=403, icon='bi-shield-lock',
                                   title=self._t('ipban_blocked_title'), description=desc)
        except Exception:  # pylint: disable=broad-except
            from markupsafe import escape as _esc  # noqa: PLC0415
            return (f'<!doctype html><meta charset="utf-8">'
                    f'<title>403</title><p style="font:1rem system-ui;margin:2rem">'
                    f'{_esc(desc)}</p>')

    def _ipban_gate_response(self):
        """The fail2ban gate (a before-request): reject a jailed IP up-front, before
        routing/auth/CSRF, so a banned attacker reaches no endpoint. Returns a Response
        to short-circuit, or None to continue. Static assets are always served (the
        'page' action's CSS must load; harmless otherwise)."""
        if request.path.startswith('/static/'):
            return None
        mgr = getattr(self, '_ipban', None)
        if mgr is None:
            return None
        ip = self._client_ip()
        banned, retry, _reason = mgr.is_banned(ip)
        if not banned:
            return None
        g._ipban_blocked = True   # don't let this block itself count as an offense
        # Action precedence: per-ban override (Banned IPs table) → the web service's
        # configured action (service registry) → 'page'.
        svc = getattr(self, '_ipban_services', None)
        action = mgr.block_action(ip) or (svc.action_for('web') if svc else 'page')
        is_api = request.path.startswith('/api/') or request.is_json
        if action in ('reject', 'drop'):
            # 'reject': an empty 403, connection closed — the least an HTTP server can do
            # (a true packet-level DROP is impossible here: the connection is already
            # accepted, and behind a proxy the app only sees the proxy's IP).
            resp = make_response('', 403)
            resp.headers['Connection'] = 'close'
        elif action == 'json' or (is_api and action != 'minimal'):
            # Structured JSON — the admin's choice, or the sensible default for an API
            # client (which can't use an HTML page).
            resp = jsonify({'error': self._t('ip_banned'), 'retry_after': retry})
            resp.status_code = 403
        elif action == 'minimal':
            resp = make_response(self._t('ip_banned'), 403)
        else:  # 'page' — the app's styled error page (default)
            resp = make_response(self._ipban_block_page(retry), 403)
        if retry:
            resp.headers['Retry-After'] = str(retry)
        return resp

    def _ipban_capture(self, response) -> None:
        """After-request offense capture: count a 401/403 as an offense for the client
        IP unless this request already registered one explicitly (login/CSRF) or is the
        gate's own block. An authenticated 403 (a logged-in user probing a forbidden
        section) is the tolerant 'forbidden' track; a 401 or a 403 with no session is
        anonymous abuse ('unauthorized' / 'forbidden_anon')."""
        from flask import session  # noqa: PLC0415
        mgr = getattr(self, '_ipban', None)
        if (mgr is None or response.status_code not in (401, 403)
                or getattr(g, '_ipban_blocked', False)
                or getattr(g, '_ipban_counted', False)
                or request.path.startswith('/static/')):
            return
        if response.status_code == 401:
            cat = 'unauthorized'
        elif session.get('logged_in'):
            cat = 'forbidden'
        else:
            cat = 'forbidden_anon'
        self._ipban_offense(cat)
