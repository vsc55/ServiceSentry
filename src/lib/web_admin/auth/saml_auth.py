#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAML2 SSO authentication for web_admin.

Requires the optional ``python3-saml`` package (``pip install python3-saml``).
If not installed, ``is_available()`` returns False and the SAML2 routes
are not registered.
"""

import json
import uuid
from urllib.parse import urlparse

_HAS_SAML2 = False
try:
    from onelogin.saml2.auth import OneLogin_Saml2_Auth
    _HAS_SAML2 = True
except Exception:
    OneLogin_Saml2_Auth = None


def is_available() -> bool:
    return _HAS_SAML2


# ── Config helpers ────────────────────────────────────────────────────────────

def _get_config(wa) -> dict:
    raw = wa._read_config_file(wa._CONFIG_FILE) or {}
    return raw.get('saml2') or {}


def _get_group_role_map(cfg: dict) -> dict:
    raw = cfg.get('group_role_map') or '{}'
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Role mapping ──────────────────────────────────────────────────────────────

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


# ── Request / settings helpers ────────────────────────────────────────────────

def _prepare_flask_request(req) -> dict:
    """Convert a Flask request to the format onelogin-python-saml expects."""
    url_data = urlparse(req.url)
    port = url_data.port
    if port is None:
        port = 443 if req.scheme == 'https' else 80
    return {
        'https':       'on' if req.scheme == 'https' else 'off',
        'http_host':   req.host,
        'server_port': str(port),
        'script_name': req.path,
        'get_data':    req.args.copy(),
        'post_data':   req.form.copy(),
    }


def _build_saml_settings(cfg: dict) -> dict:
    """Build the onelogin-python-saml settings dict from our config section."""
    return {
        'strict': True,
        'debug':  False,
        'sp': {
            'entityId': cfg.get('sp_entity_id', '') or '',
            'assertionConsumerService': {
                'url':     cfg.get('sp_acs_url', '') or '',
                'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST',
            },
            'nameIdFormat': 'urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified',
            'x509cert':  cfg.get('sp_cert', '') or '',
            'privateKey': cfg.get('sp_key',  '') or '',
        },
        'idp': {
            'entityId': cfg.get('idp_entity_id', '') or '',
            'singleSignOnService': {
                'url':     cfg.get('idp_sso_url', '') or '',
                'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect',
            },
            'x509cert': cfg.get('idp_cert', '') or '',
        },
    }


# ── Auth object factory ───────────────────────────────────────────────────────

def get_auth(wa, req):
    """Return an initialized OneLogin_Saml2_Auth for this request, or None."""
    if not _HAS_SAML2:
        return None
    cfg = _get_config(wa)
    if not cfg.get('enabled'):
        return None
    settings     = _build_saml_settings(cfg)
    request_data = _prepare_flask_request(req)
    return OneLogin_Saml2_Auth(request_data, settings)


# ── User sync ─────────────────────────────────────────────────────────────────

def sync_user(wa, name_id: str, saml_attrs: dict) -> dict | None:
    """Create or update user from SAML2 assertion attributes.

    Returns the user dict, or None if auto_create_users is False and the
    user does not already exist.
    """
    cfg            = _get_config(wa)
    auto_create    = cfg.get('auto_create_users', True)
    group_role_map = _get_group_role_map(cfg)

    username_attr = cfg.get('username_attr', '') or ''
    email_attr    = cfg.get('email_attr',    'email')       or 'email'
    name_attr     = cfg.get('name_attr',     'displayName') or 'displayName'
    groups_attr   = cfg.get('groups_attr',   'groups')      or 'groups'

    def _first(attr_name: str) -> str:
        vals = saml_attrs.get(attr_name, [])
        return str(vals[0]) if vals else ''

    username     = _first(username_attr) if username_attr else ''
    username     = username or name_id
    email        = _first(email_attr)
    display_name = _first(name_attr)
    groups       = [str(v) for v in saml_attrs.get(groups_attr, [])]

    if not username:
        return None

    role_name = _map_role(groups, group_role_map)
    _dr = cfg.get('default_role', '')
    default_role_uid = _dr if wa._is_uid(_dr) else (wa._role_name_to_uid(_dr or 'none') or wa._role_name_to_uid('none'))
    role_uid     = wa._role_name_to_uid(role_name) or default_role_uid

    existing = wa._users.get(username)
    if existing is None:
        if not auto_create:
            return None
        user = {
            'uid':            str(uuid.uuid4()),
            'auth_source':    'saml2',
            'auth_source_id': name_id,
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
        user['auth_source']    = 'saml2'
        user['auth_source_id'] = name_id
        user['display_name']   = display_name or user.get('display_name', '')
        user['email']          = email        or user.get('email', '')
        user['role']           = role_uid

    wa._persist_users()
    return user


# ── Route registration ────────────────────────────────────────────────────────

def register_routes(app, wa) -> None:
    """Register /auth/saml2/login, /auth/saml2/acs, /auth/saml2/metadata."""
    if not _HAS_SAML2:
        return

    from flask import (flash, make_response, redirect,
                       request, url_for)
    from ..routes.auth import _establish_session

    @app.route('/auth/saml2/login')
    def saml2_login():
        auth = get_auth(wa, request)
        if auth is None:
            flash(wa._t('saml2_disabled'), 'danger')
            return redirect(url_for('login'))
        return redirect(auth.login())

    @app.route('/auth/saml2/acs', methods=['POST'])
    def saml2_acs():
        auth = get_auth(wa, request)
        if auth is None:
            flash(wa._t('saml2_disabled'), 'danger')
            return redirect(url_for('login'))

        auth.process_response()
        errors = auth.get_errors()

        if errors:
            reason = '; '.join(errors)
            flash(wa._t('saml2_auth_error', reason), 'danger')
            wa._audit('login_failed', '', request.remote_addr,
                      detail={'reason': 'saml2_error', 'errors': errors})
            return redirect(url_for('login'))

        if not auth.is_authenticated():
            flash(wa._t('saml2_not_authenticated'), 'danger')
            wa._audit('login_failed', '', request.remote_addr,
                      detail={'reason': 'saml2_not_authenticated'})
            return redirect(url_for('login'))

        name_id    = auth.get_nameid()
        saml_attrs = auth.get_attributes()
        user       = sync_user(wa, name_id, saml_attrs)

        if user is None:
            flash(wa._t('sso_user_not_allowed'), 'danger')
            wa._audit('login_failed', '', request.remote_addr,
                      detail={'reason': 'saml2_auto_create_disabled'})
            return redirect(url_for('login'))

        cfg           = _get_config(wa)
        username_attr = cfg.get('username_attr', '') or ''
        if username_attr and saml_attrs.get(username_attr):
            username = str(saml_attrs[username_attr][0])
        else:
            username = name_id

        if not user.get('enabled', True):
            flash(wa._t('account_disabled'), 'danger')
            wa._audit('login_failed', username, request.remote_addr,
                      detail={'reason': 'account_disabled'})
            return redirect(url_for('login'))

        _establish_session(wa, username, user)
        wa._audit('login_ok', username, request.remote_addr,
                  detail={'auth_source': 'saml2'})
        return redirect(url_for('dashboard'))

    @app.route('/auth/saml2/metadata')
    def saml2_metadata():
        auth = get_auth(wa, request)
        if auth is None:
            return wa._t('saml2_disabled'), 404

        settings = auth.get_settings()
        metadata = settings.get_sp_metadata()
        errors   = settings.validate_metadata(metadata)

        if errors:
            return str(errors), 500

        resp = make_response(metadata, 200)
        resp.headers['Content-Type'] = 'text/xml'
        return resp
