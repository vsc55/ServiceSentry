#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authentication routes: /login, /logout.

Routes registered by this file:

    GET,POST /login   login form (GET) / authenticate (POST) — local + LDAP/OIDC/SAML
    POST     /logout  end the current session
"""

from flask import flash, redirect, render_template, request, session, url_for

from lib.debug import DebugLevel
from lib.security.ratelimit import RateLimiter

# Per-IP login throttle thresholds come from config (web_admin|login_ratelimit_*,
# attrs _LOGIN_RL_MAX / _LOGIN_RL_WINDOW; 0 = disabled) — a brute-force speed bump
# on top of the per-account lockout (stops single-IP password spraying).


def register(app, wa):

    if not hasattr(wa, '_login_ratelimit'):
        wa._login_ratelimit = RateLimiter()

    # Auth lives in web_admin (outside the notify-events discovery roots), so it declares
    # its notification events with the manual registry — the same escape hatch any code has.
    from lib.core.notify.events import register_event  # noqa: PLC0415
    for _key, _label, _order in (('auth_login', 'notif_event_auth_login', 50),
                                 ('auth_login_failed', 'notif_event_auth_login_failed', 51),
                                 ('auth_account_locked', 'notif_event_auth_locked', 52)):
        register_event({'key': _key, 'source': 'auth', 'label_key': _label,
                        'matrix': True, 'order': _order})

    def _login_ok(username, source, remember=False):
        """Audit a successful login (with source/role/remember) + info debug line."""
        role = session.get('role', '')
        wa._dbg(f"> Auth >> login OK user={username!r} source={source} role={role!r} "
                f"from {request.remote_addr}", DebugLevel.info)
        wa._audit('login_ok', username, request.remote_addr,
                  detail={'auth_source': source, 'role': role, 'remember': bool(remember)})

    def _login_failed(username, reason):
        """Audit a failed login + **warning** debug line (visible at the default level)."""
        wa._dbg(f"> Auth >> login FAILED user={username!r} reason={reason} "
                f"from {request.remote_addr}", DebugLevel.warning)
        wa._audit('login_failed', username, request.remote_addr, detail={'reason': reason})
        # Forward to the notification router (opt-in matrix): a lock is its own kind.
        try:
            import time as _t  # noqa: PLC0415
            from lib.core.notify.notification_dispatcher import dispatch as _dispatch  # noqa: PLC0415,E501
            from lib.core.notify.formatting import notify_lang, notify_text  # noqa: PLC0415
            _kind = 'auth_account_locked' if reason == 'account_locked' else 'auth_login_failed'
            _cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
            _lang = notify_lang(_cfg)
            _st = 'notif_status_locked' if _kind == 'auth_account_locked' else 'notif_status_failed'
            _dispatch(wa, kind=_kind, module='auth', item=username or (request.remote_addr or '?'),
                      status=notify_text(_cfg, _lang, _st),
                      message=notify_text(_cfg, _lang, 'notif_msg_auth_failed', username or '?',
                                          reason, request.remote_addr),
                      timestamp=_t.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception:  # pylint: disable=broad-except
            pass
        # Feed the internal fail2ban (progressive per-IP jail) — every failed login,
        # whatever the reason, is one 'auth'-track offense.
        wa._ipban_offense('login_failed')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Login page."""
        if session.get('logged_in'):
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            # Per-IP brute-force throttle (before any credential work). Config-driven
            # thresholds (0 = disabled).
            _ip = request.remote_addr or '?'
            _ok, _retry = wa._login_ratelimit.hit(_ip, wa._LOGIN_RL_MAX, wa._LOGIN_RL_WINDOW)
            if not _ok:
                wa._audit('login_throttled', '', _ip, detail={'retry_after': _retry})
                wa._ipban_offense('login_throttled')
                flash(wa._t('login_throttled'), 'danger')
                return redirect(url_for('login'))
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            remember = request.form.get('remember_me') == 'on'
            wa._dbg(f"> Auth >> login attempt user={username!r} from {request.remote_addr}",
                    DebugLevel.info)

            # Resolve the attempt (LDAP when enabled → local) with no web concern; the
            # decision + the previously-duplicated LDAP branches live in
            # _AuthMixin.resolve_login.  Here we only map the result to session/audit/flash.
            result = wa.resolve_login(username, password)
            if result.user:
                wa._establish_session(result.username, result.user, remember)
                _login_ok(result.username, result.source, remember)
                return redirect(wa._landing_url(result.user))
            _login_failed(result.username, result.reason)
            flash(wa._t(result.flash_key), 'danger')
            return redirect(url_for('login'))

        return render_template('login.html')

    @app.route('/logout', methods=['POST'])
    def logout():
        """Log out and redirect to login page (POST-only + CSRF → no logout-CSRF)."""
        token = session.get('session_token')
        uname = session.get('username', '')
        if token:
            wa._revoke_session(token)
        wa._dbg(f"> Auth >> logout user={uname!r} from {request.remote_addr}", DebugLevel.info)
        wa._audit('logout', uname, request.remote_addr,
                  detail={'uid': session.get('session_id', ''),
                          'role': session.get('role', '')})
        session.clear()
        return redirect(url_for('login'))
