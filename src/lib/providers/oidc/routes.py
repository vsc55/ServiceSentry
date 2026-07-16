#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OIDC SSO routes: /auth/oidc/login, /auth/oidc/callback.

The interactive callback validates the token and then hands off to the web
session layer (``web_admin.routes.auth._establish_session``) — the one place a
provider legitimately reaches back into web_admin (a web callback establishes a
web session).

Routes registered by this file:

    GET    /auth/oidc/login     start OIDC login (redirect to IdP)
    GET    /auth/oidc/callback  validate token, establish session
"""

from lib.config.spec import cfg_get

from . import auth as oidc_auth


def register(app, wa):
    """Register /auth/oidc/login and /auth/oidc/callback routes."""
    if not oidc_auth._HAS_AUTHLIB:
        return
    # The IdP redirects back here cross-site (protected by the OIDC state param, not CSRF).
    wa._register_csrf_exempt('/auth/oidc/callback')

    from flask import flash, redirect, request, url_for
    from lib.web_admin.routes.auth import _establish_session, _landing_url

    @app.route('/auth/oidc/login')
    def oidc_login():
        """Start OIDC login: redirect the browser to the IdP's authorization
        endpoint (or back to the local login page if OIDC is disabled)."""
        client = oidc_auth.get_client(wa)
        if client is None:
            flash(wa._t('oidc_disabled'), 'danger')
            return redirect(url_for('login'))
        redirect_uri = url_for('oidc_callback', _external=True)
        return client.authorize_redirect(redirect_uri)

    @app.route('/auth/oidc/callback')
    def oidc_callback():
        """OIDC redirect callback: exchange the code for a token, read the
        userinfo, sync the user, and establish a web session (auditing the
        outcome). Redirects to the landing page on success, back to login on any
        failure (token error, user not allowed, account disabled)."""
        client = oidc_auth.get_client(wa)
        if client is None:
            flash(wa._t('oidc_disabled'), 'danger')
            return redirect(url_for('login'))
        try:
            token    = client.authorize_access_token()
            userinfo = token.get('userinfo') or client.userinfo()
        except Exception as exc:
            flash(wa._t('sso_callback_error', str(exc)), 'danger')
            wa._audit('login_failed', '', request.remote_addr,
                      detail={'reason': 'oidc_callback_error', 'error': str(exc)})
            return redirect(url_for('login'))

        cfg            = oidc_auth._get_config(wa)
        username_claim = cfg_get(cfg, 'oidc|username_claim', falsy=True)
        groups_claim   = cfg_get(cfg, 'oidc|groups_claim', falsy=True)
        username       = userinfo.get(username_claim) or userinfo.get('sub', '')
        received_groups = userinfo.get(groups_claim, [])
        if not isinstance(received_groups, list):
            received_groups = []

        user = oidc_auth.sync_user(wa, userinfo)
        if user is None:
            flash(wa._t('sso_user_not_allowed'), 'danger')
            wa._audit('login_failed', username or '', request.remote_addr,
                      detail={'reason': 'oidc_auto_create_disabled',
                              'groups_received': received_groups})
            return redirect(url_for('login'))

        if not user.get('enabled', True):
            flash(wa._t('account_disabled'), 'danger')
            wa._audit('login_failed', username, request.remote_addr,
                      detail={'reason': 'account_disabled'})
            return redirect(url_for('login'))

        _establish_session(wa, username, user)
        role_uid = user.get('role', '')
        assigned_role = wa._uid_to_role_name(role_uid) if wa._is_uid(role_uid) else role_uid
        wa._audit('login_ok', username, request.remote_addr,
                  detail={'auth_source': 'oidc',
                          'groups_received': received_groups,
                          'role_assigned': assigned_role})
        return redirect(_landing_url(wa, user))
