#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OIDC / OAuth2 SSO authentication for web_admin.

Requires the optional ``authlib`` package (``pip install authlib``).
If not installed, ``is_available()`` returns False and the SSO routes
are not registered.
"""

import hashlib
import json
import os
import uuid

_HAS_AUTHLIB = False
try:
    from authlib.integrations.flask_client import OAuth
    _HAS_AUTHLIB = True
except Exception:
    OAuth = None


class OidcUnavailableError(RuntimeError):
    """Raised when authlib is not installed."""


def is_available() -> bool:
    return _HAS_AUTHLIB


# ── Config helpers ──────────────────────────────────────────────────────────

def _get_config(wa) -> dict:
    raw = wa._read_config_file(wa._CONFIG_FILE) or {}
    return raw.get('oidc') or {}


def _get_group_role_map(cfg: dict) -> dict:
    raw = cfg.get('group_role_map') or '{}'
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}


def _config_hash(cfg: dict) -> str:
    key = f"{cfg.get('provider_url')}|{cfg.get('client_id')}|{cfg.get('client_secret')}"
    return hashlib.sha256(key.encode()).hexdigest()


# ── Role mapping ─────────────────────────────────────────────────────────────

def _map_role(groups: list, group_role_map: dict) -> str:
    priority = ['admin', 'editor', 'viewer']
    matched: dict = {}
    for g in groups:
        for pattern, role in group_role_map.items():
            if pattern.lower() == str(g).lower():
                if role not in matched:
                    matched[role] = g
    for role in priority:
        if role in matched:
            return role
    for role in matched:
        return role
    return ''


# ── OAuth client (lazy, re-initialized on config change) ─────────────────────

_oauth_instance = None
_oauth_app_ref  = None


def get_client(wa):
    """Return the configured Authlib OAuth client, re-init on config change."""
    global _oauth_instance, _oauth_app_ref

    if not _HAS_AUTHLIB:
        return None

    cfg = _get_config(wa)
    if not cfg.get('enabled'):
        return None

    provider_url = (cfg.get('provider_url') or '').strip().rstrip('/')
    if not provider_url or '://' not in provider_url:
        raise ValueError(
            f"OIDC provider_url is not configured or missing scheme "
            f"(got: {provider_url!r}). "
            "Set it in Configuration → Auth → OIDC (e.g. "
            "https://login.microsoftonline.com/<tenant>/v2.0)."
        )

    ch = _config_hash(cfg)
    if (wa._oidc_config_hash == ch and _oauth_instance is not None
            and _oauth_app_ref is wa._app):
        return _oauth_instance.create_client('sso')

    oauth = OAuth(wa._app)
    oauth.register(
        name='sso',
        client_id=cfg.get('client_id', ''),
        client_secret=cfg.get('client_secret', ''),
        server_metadata_url=provider_url + '/.well-known/openid-configuration',
        client_kwargs={'scope': cfg.get('scopes', 'openid email profile')},
    )

    _oauth_instance       = oauth
    _oauth_app_ref        = wa._app
    wa._oidc_config_hash  = ch
    return oauth.create_client('sso')


# ── User sync ────────────────────────────────────────────────────────────────

def sync_user(wa, userinfo: dict) -> dict | None:
    """Create or update user from OIDC userinfo. Returns user dict or None if not allowed."""
    cfg             = _get_config(wa)
    auto_create     = cfg.get('auto_create_users', True)
    group_role_map  = _get_group_role_map(cfg)

    username_claim  = cfg.get('username_claim', 'preferred_username') or 'preferred_username'
    email_claim     = cfg.get('email_claim',    'email')              or 'email'
    name_claim      = cfg.get('name_claim',     'name')               or 'name'
    groups_claim    = cfg.get('groups_claim',   'groups')             or 'groups'

    username     = userinfo.get(username_claim) or userinfo.get('sub', '')
    email        = userinfo.get(email_claim, '')
    display_name = userinfo.get(name_claim, '')
    groups       = userinfo.get(groups_claim, [])
    if not isinstance(groups, list):
        groups = []
    sub = userinfo.get('sub', '')

    if not username:
        return None

    role_name = _map_role(groups, group_role_map)
    _dr = cfg.get('default_role', '')
    default_role_uid = _dr if wa._is_uid(_dr) else (wa._role_name_to_uid(_dr or 'none') or wa._role_name_to_uid('none'))
    role_uid  = wa._role_name_to_uid(role_name) or default_role_uid

    existing = wa._users.get(username)
    if existing is None:
        if not auto_create:
            return None
        user = {
            'uid':            str(uuid.uuid4()),
            'auth_source':    'oidc',
            'auth_source_id': sub,
            'display_name':   display_name,
            'email':          email,
            'role':           role_uid,
            'groups':         [],
            'enabled':        True,
            'lang':           '',
            'dark_mode':      False,
        }
        wa._users[username] = user
    else:
        user = existing
        user['auth_source']    = 'oidc'
        user['auth_source_id'] = sub
        user['display_name']   = display_name or user.get('display_name', '')
        user['email']          = email        or user.get('email', '')
        user['role']           = role_uid  # re-sync on every login

    wa._persist_users()
    return user


# ── Route registration ────────────────────────────────────────────────────────

def register_routes(app, wa):
    """Register /auth/oidc/login and /auth/oidc/callback routes."""
    if not _HAS_AUTHLIB:
        return

    from flask import redirect, render_template, request, session, url_for
    from flask import flash
    from ..routes.auth import _establish_session

    @app.route('/auth/oidc/login')
    def oidc_login():
        client = get_client(wa)
        if client is None:
            flash(wa._t('oidc_disabled'), 'danger')
            return redirect(url_for('login'))
        redirect_uri = url_for('oidc_callback', _external=True)
        return client.authorize_redirect(redirect_uri)

    @app.route('/auth/oidc/callback')
    def oidc_callback():
        client = get_client(wa)
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

        cfg            = _get_config(wa)
        username_claim = cfg.get('username_claim', 'preferred_username') or 'preferred_username'
        groups_claim   = cfg.get('groups_claim', 'groups') or 'groups'
        username       = userinfo.get(username_claim) or userinfo.get('sub', '')
        received_groups = userinfo.get(groups_claim, [])
        if not isinstance(received_groups, list):
            received_groups = []

        user = sync_user(wa, userinfo)
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
        return redirect(url_for('dashboard'))
