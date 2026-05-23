#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authentication routes: /login, /logout."""

import math
from datetime import datetime, timezone

from flask import flash, redirect, render_template, request, session, url_for

from ..auth import ldap_auth
from ..constants import SUPPORTED_LANGS


def _establish_session(wa, username: str, user: dict, remember: bool = False) -> None:
    """Populate the Flask session after a successful authentication."""
    session.permanent = remember
    token, sid = wa._create_session(
        username, request.remote_addr, request.user_agent.string,
    )
    session['session_token'] = token
    session['session_id']    = sid
    session['logged_in']     = True
    session['username']      = username
    role_ref  = user.get('role', 'viewer')
    role_name = wa._uid_to_role_name(role_ref) if wa._is_uid(role_ref) else role_ref
    session['role']         = role_name or 'viewer'
    session['display_name'] = user.get('display_name', username)
    user_lang = user.get('lang')
    if user_lang and user_lang in SUPPORTED_LANGS:
        session['lang'] = user_lang
    user_dm = user.get('dark_mode')
    if user_dm is not None:
        session['dark_mode'] = user_dm


def register(app, wa):

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Login page."""
        if session.get('logged_in'):
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            remember = request.form.get('remember_me') == 'on'

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
                        user = ldap_auth.sync_user(wa, username, attrs)
                        if not user.get('enabled', True):
                            flash(wa._t('account_disabled'), 'danger')
                            wa._audit('login_failed', username, request.remote_addr,
                                      detail={'reason': 'account_disabled'})
                            return redirect(url_for('login'))
                        _establish_session(wa, username, user, remember)
                        wa._audit('login_ok', username, request.remote_addr,
                                  detail={'auth_source': 'ldap'})
                        return redirect(url_for('dashboard'))
                    # SSO users have no local password — never fall through to local auth
                    if reason == 'ldap_connection_error':
                        flash(wa._t('ldap_connection_error'), 'danger')
                    else:
                        flash(wa._t('invalid_credentials'), 'danger')
                    wa._audit('login_failed', username, request.remote_addr,
                              detail={'reason': reason})
                    return redirect(url_for('login'))
                elif not existing:
                    # Unknown user + LDAP enabled → try LDAP first
                    attrs, reason = ldap_auth.authenticate(wa, username, password)
                    if attrs:
                        user = ldap_auth.sync_user(wa, username, attrs)
                        if not user.get('enabled', True):
                            flash(wa._t('account_disabled'), 'danger')
                            wa._audit('login_failed', username, request.remote_addr,
                                      detail={'reason': 'account_disabled'})
                            return redirect(url_for('login'))
                        _establish_session(wa, username, user, remember)
                        wa._audit('login_ok', username, request.remote_addr,
                                  detail={'auth_source': 'ldap'})
                        return redirect(url_for('dashboard'))
                    if reason in ('ldap_invalid_credentials', 'ldap_user_not_found'):
                        flash(wa._t('invalid_credentials'), 'danger')
                        wa._audit('login_failed', username, request.remote_addr,
                                  detail={'reason': reason})
                        return redirect(url_for('login'))
                    # ldap_connection_error: fall through to local only if fallback enabled
                    # and track the LDAP error to surface it if local also fails
                    if not ldap_cfg.get('fallback_to_local', True):
                        flash(wa._t('ldap_connection_error'), 'danger')
                        wa._audit('login_failed', username, request.remote_addr,
                                  detail={'reason': reason})
                        return redirect(url_for('login'))
                    _ldap_conn_error = reason  # remember for after local auth

            # ── Local authentication ──────────────────────────────────────
            user, reason = wa._authenticate(username, password)
            if user:
                _establish_session(wa, username, user, remember)
                wa._audit('login_ok', username, request.remote_addr)
                return redirect(url_for('dashboard'))

            if reason == 'account_locked':
                raw          = wa._users.get(username, {})
                locked_str   = raw.get('_locked_until', '')
                try:
                    secs_left = (datetime.fromisoformat(locked_str)
                                 - datetime.now(timezone.utc)).total_seconds()
                    mins_left = math.ceil(max(secs_left, 0) / 60)
                except (ValueError, TypeError):
                    mins_left = 1
                error = wa._t('account_locked', str(mins_left))
            elif reason == 'account_disabled':
                error = wa._t('account_disabled')
            elif _ldap_conn_error:
                # Local auth also failed for a user unknown locally — surface the LDAP error
                error = wa._t('ldap_connection_error')
            else:
                error = wa._t('invalid_credentials')

            wa._audit('login_failed', username, request.remote_addr,
                      detail={'reason': reason})
            flash(error, 'danger')
            return redirect(url_for('login'))

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        """Log out and redirect to login page."""
        token = session.get('session_token')
        uname = session.get('username', '')
        if token:
            wa._revoke_session(token)
        wa._audit('logout', uname, request.remote_addr)
        session.clear()
        return redirect(url_for('login'))
