#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authentication routes: /login, /logout."""

from flask import flash, redirect, render_template, request, session, url_for

from ...auth import ldap_auth
from ...constants import SUPPORTED_LANGS
from lib.debug import DebugLevel
from lib.security.ratelimit import RateLimiter

# Per-IP login throttle thresholds come from config (web_admin|login_ratelimit_*,
# attrs _LOGIN_RL_MAX / _LOGIN_RL_WINDOW; 0 = disabled) — a brute-force speed bump
# on top of the per-account lockout (stops single-IP password spraying).


def _establish_session(wa, username: str, user: dict, remember: bool = False) -> None:
    """Populate the Flask session after a successful authentication."""
    # A successful auth clears the per-IP login throttle (legit users on a shared
    # NAT are never penalised by earlier failures).
    rl = getattr(wa, '_login_ratelimit', None)
    if rl is not None:
        rl.reset(request.remote_addr or '?')
    session.permanent = remember
    token, uid = wa._create_session(
        username, request.remote_addr, request.user_agent.string,
    )
    session['session_token'] = token
    session['session_id']    = uid
    session['logged_in']     = True
    session['username']      = username
    role_ref  = user.get('role', 'viewer')
    role_name = wa._uid_to_role_name(role_ref) if wa._is_uid(role_ref) else role_ref
    session['role']         = role_name or 'viewer'
    session['display_name'] = user.get('display_name', username)
    wa._dbg(f"> Auth >> session established user={username!r} role={session['role']}",
            DebugLevel.info)
    user_lang = user.get('lang')
    if user_lang and user_lang in SUPPORTED_LANGS:
        session['lang'] = user_lang
    user_dm = user.get('dark_mode')
    if user_dm is not None:
        session['dark_mode'] = user_dm


def register(app, wa):

    if not hasattr(wa, '_login_ratelimit'):
        wa._login_ratelimit = RateLimiter()

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

            # ── LDAP authentication ───────────────────────────────────────
            cfg             = wa._read_config_file(wa._CONFIG_FILE) or {}
            ldap_cfg        = cfg.get('ldap') or {}
            _ldap_conn_error = None  # set if LDAP fails with connection error

            if ldap_cfg.get('enabled') and ldap_auth.is_available():
                existing = wa._users.get(username, {})
                # Local users always go through local auth, not LDAP
                if existing.get('auth_source', 'local') != 'local':
                    attrs, reason = ldap_auth.authenticate(wa, username, password)
                    if attrs:
                        canonical = attrs.get('username') or username
                        user = ldap_auth.sync_user(wa, canonical, attrs)
                        if not user.get('enabled', True):
                            flash(wa._t('account_disabled'), 'danger')
                            _login_failed(canonical, 'account_disabled')
                            return redirect(url_for('login'))
                        _establish_session(wa, canonical, user, remember)
                        _login_ok(canonical, 'ldap', remember)
                        return redirect(url_for('dashboard'))
                    # SSO users have no local password — never fall through to local auth
                    if reason == 'ldap_connection_error':
                        flash(wa._t('ldap_connection_error'), 'danger')
                    else:
                        flash(wa._t('invalid_credentials'), 'danger')
                    _login_failed(username, reason)
                    return redirect(url_for('login'))
                elif not existing:
                    # Unknown user + LDAP enabled → try LDAP first
                    attrs, reason = ldap_auth.authenticate(wa, username, password)
                    if attrs:
                        canonical = attrs.get('username') or username
                        user = ldap_auth.sync_user(wa, canonical, attrs)
                        if not user.get('enabled', True):
                            flash(wa._t('account_disabled'), 'danger')
                            _login_failed(canonical, 'account_disabled')
                            return redirect(url_for('login'))
                        _establish_session(wa, canonical, user, remember)
                        _login_ok(canonical, 'ldap', remember)
                        return redirect(url_for('dashboard'))
                    if reason in ('ldap_invalid_credentials', 'ldap_user_not_found'):
                        flash(wa._t('invalid_credentials'), 'danger')
                        _login_failed(username, reason)
                        return redirect(url_for('login'))
                    # ldap_connection_error: fall through to local only if fallback enabled
                    # and track the LDAP error to surface it if local also fails
                    if not ldap_cfg.get('fallback_to_local', True):
                        flash(wa._t('ldap_connection_error'), 'danger')
                        _login_failed(username, reason)
                        return redirect(url_for('login'))
                    _ldap_conn_error = reason  # remember for after local auth

            # ── Local authentication ──────────────────────────────────────
            user, reason = wa._authenticate(username, password)
            if user:
                _establish_session(wa, username, user, remember)
                _login_ok(username, user.get('auth_source') or 'local', remember)
                return redirect(url_for('dashboard'))

            if reason == 'account_locked':
                # Use a generic message that doesn't confirm the account exists
                # or reveal the exact remaining lockout time to avoid account
                # enumeration.  The real reason is recorded in the audit log.
                error = wa._t('invalid_credentials')
            elif reason == 'account_disabled':
                # Same generic message — don't reveal that the account exists
                # and is explicitly disabled.
                error = wa._t('invalid_credentials')
            elif _ldap_conn_error:
                # Local auth also failed for a user unknown locally — surface the LDAP error
                error = wa._t('ldap_connection_error')
            else:
                error = wa._t('invalid_credentials')

            _login_failed(username, reason)
            flash(error, 'danger')
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
