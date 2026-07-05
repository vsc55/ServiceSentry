#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAML2 SSO authentication for web_admin.

Requires the optional ``python3-saml`` package (``pip install python3-saml``).
If not installed, ``is_available()`` returns False and the SAML2 routes
are not registered.
"""

import json
import threading
import time
import uuid
from urllib.parse import urlparse

from lib.config.spec import cfg_default, cfg_get
from lib.debug import DebugLevel

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
    return wa._config_section('saml2')


def _get_group_role_map(cfg: dict) -> dict:
    raw = cfg.get('group_role_map') or cfg_default('saml2|group_role_map')
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


def _build_saml_settings(cfg: dict, base_url: str = '') -> dict:
    """Build the onelogin-python-saml settings dict from our config section.

    The SP identity (``sp_entity_id`` / ``sp_acs_url``) is ServiceSentry's own and is
    NOT hand-edited: when unset it derives from ``base_url`` (the public base URL),
    matching the read-only values shown in the config UI."""
    base = (base_url or '').rstrip('/')
    sp_entity = (cfg.get('sp_entity_id') or '').strip() or base
    sp_acs    = (cfg.get('sp_acs_url') or '').strip() or (f'{base}/auth/saml2/acs' if base else '')
    return {
        'strict': True,
        'debug':  False,
        'sp': {
            'entityId': sp_entity,
            'assertionConsumerService': {
                'url':     sp_acs,
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
        # Hardening: require the assertion itself to be signed (not just the envelope),
        # reject deprecated SHA-1 signatures, and pin SHA-256. Entra signs the assertion
        # with RSA-SHA256 by default, so this is compatible with the standard setup.
        'security': {
            'wantAssertionsSigned':     True,
            'wantMessagesSigned':       False,
            'wantNameId':               True,
            'rejectDeprecatedAlgorithm': True,
            'signatureAlgorithm': 'http://www.w3.org/2001/04/xmldsig-more#rsa-sha256',
            'digestAlgorithm':    'http://www.w3.org/2001/04/xmlenc#sha256',
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
    base_url = wa.public_base_url() if hasattr(wa, 'public_base_url') else ''
    settings     = _build_saml_settings(cfg, base_url)
    request_data = _prepare_flask_request(req)
    return OneLogin_Saml2_Auth(request_data, settings)


# ── User sync ─────────────────────────────────────────────────────────────────

def sync_user(wa, name_id: str, saml_attrs: dict) -> dict | None:
    """Create or update user from SAML2 assertion attributes.

    Returns the user dict, or None if auto_create_users is False and the
    user does not already exist.
    """
    cfg            = _get_config(wa)
    auto_create    = cfg_get(cfg, 'saml2|auto_create_users')
    group_role_map = _get_group_role_map(cfg)

    username_attr = cfg.get('username_attr', '') or ''
    email_attr    = cfg_get(cfg, 'saml2|email_attr', falsy=True)
    name_attr     = cfg_get(cfg, 'saml2|name_attr', falsy=True)
    groups_attr   = cfg_get(cfg, 'saml2|groups_attr', falsy=True)

    def _first(attr_name: str) -> str:
        vals = saml_attrs.get(attr_name, [])
        return str(vals[0]) if vals else ''

    username     = _first(username_attr) if username_attr else ''
    username     = username or name_id
    email        = _first(email_attr)
    display_name = _first(name_attr)
    groups       = [str(v) for v in saml_attrs.get(groups_attr, [])]

    if not username:
        wa._dbg("> Auth/SAML2 >> no username resolved; rejecting", DebugLevel.warning)
        return None

    role_name = _map_role(groups, group_role_map)
    _dr = cfg.get('default_role', '')
    default_role_uid = _dr if wa._is_uid(_dr) else (wa._role_name_to_uid(_dr or 'none') or wa._role_name_to_uid('none'))
    role_uid     = wa._role_name_to_uid(role_name) or default_role_uid

    existing = wa._users.get(username)
    if existing is None:
        if not auto_create:
            wa._dbg(f"> Auth/SAML2 >> user {username!r} unknown and auto-create off; rejecting",
                    DebugLevel.info)
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
    wa._dbg(f"> Auth/SAML2 >> {'created' if existing is None else 'updated'} user={username!r} "
            f"role={role_name} groups={len(groups)}", DebugLevel.info)
    return user


# ── Route registration ────────────────────────────────────────────────────────

def register_routes(app, wa) -> None:
    """Register /auth/saml2/login, /auth/saml2/acs, /auth/saml2/metadata."""
    if not _HAS_SAML2:
        return

    from flask import (flash, make_response, redirect,
                       request, session, url_for)
    from ..routes.auth import _establish_session

    @app.route('/auth/saml2/login')
    def saml2_login():
        auth = get_auth(wa, request)
        if auth is None:
            flash(wa._t('saml2_disabled'), 'danger')
            return redirect(url_for('login'))
        url = auth.login()
        # Bind this SP-initiated request to the session so the ACS can verify the
        # response's InResponseTo → blocks replay / unsolicited-response injection.
        session['_saml_req_id'] = auth.get_last_request_id()
        return redirect(url)

    @app.route('/auth/saml2/acs', methods=['POST'])
    def saml2_acs():
        auth = get_auth(wa, request)
        if auth is None:
            flash(wa._t('saml2_disabled'), 'danger')
            return redirect(url_for('login'))

        # Require a pending SP-initiated request id bound to THIS session and validate
        # the response's InResponseTo against it. Rejecting a missing id is essential:
        # python3-saml SKIPS the InResponseTo check when request_id is None, so an
        # attacker (who never hit /auth/saml2/login and thus has no _saml_req_id) would
        # otherwise replay a stolen assertion or force a login (login-CSRF). SameSite=Lax
        # lets the session cookie ride the IdP's top-level POST, so the genuine flow keeps
        # its id. (Unsolicited / IdP-initiated responses are intentionally not accepted.)
        req_id = session.pop('_saml_req_id', None)
        if not req_id:
            wa._audit('login_failed', '', request.remote_addr,
                      detail={'reason': 'saml2_unsolicited'})
            flash(wa._t('saml2_not_authenticated'), 'danger')
            return redirect(url_for('login'))
        auth.process_response(request_id=req_id)
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

        # One-time-use: reject a validated assertion that was already consumed
        # (replay within its NotOnOrAfter window). Keyed by the assertion id, kept
        # in-memory with a short TTL (the library's own timestamp check bars it after).
        try:
            _aid = auth.get_last_assertion_id()
        except Exception:  # pylint: disable=broad-except
            _aid = None
        if _aid:
            _now = time.time()
            _lock = getattr(wa, '_saml_used_lock', None)
            if _lock is None:
                _lock = wa._saml_used_lock = threading.Lock()
            with _lock:                      # atomic prune → check → record (no TOCTOU race)
                _used = getattr(wa, '_saml_used_assertions', None)
                if _used is None:
                    _used = wa._saml_used_assertions = {}
                for _k in [k for k, exp in _used.items() if exp < _now]:
                    _used.pop(_k, None)
                _replayed = _aid in _used
                if not _replayed:
                    _used[_aid] = _now + 600  # 10-min window (>= typical NotOnOrAfter)
            if _replayed:
                flash(wa._t('saml2_not_authenticated'), 'danger')
                wa._audit('login_failed', '', request.remote_addr,
                          detail={'reason': 'saml2_assertion_replay'})
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
