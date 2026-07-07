#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAML2 SSO routes: /auth/saml2/login, /auth/saml2/acs, /auth/saml2/metadata.

The ACS callback validates the assertion (with replay + InResponseTo hardening)
and then hands off to the web session layer
(``web_admin.routes.auth._establish_session``) — the one place a provider
legitimately reaches back into web_admin (a web callback establishes a web session).
"""

import threading
import time

from . import auth as saml_auth


def register(app, wa) -> None:
    """Register /auth/saml2/login, /auth/saml2/acs, /auth/saml2/metadata."""
    if not saml_auth._HAS_SAML2:
        return

    from flask import (flash, make_response, redirect,
                       request, session, url_for)
    from lib.web_admin.routes.auth import _establish_session, _landing_url

    @app.route('/auth/saml2/login')
    def saml2_login():
        auth = saml_auth.get_auth(wa, request)
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
        auth = saml_auth.get_auth(wa, request)
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
        user       = saml_auth.sync_user(wa, name_id, saml_attrs)

        if user is None:
            flash(wa._t('sso_user_not_allowed'), 'danger')
            wa._audit('login_failed', '', request.remote_addr,
                      detail={'reason': 'saml2_auto_create_disabled'})
            return redirect(url_for('login'))

        cfg           = saml_auth._get_config(wa)
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
        return redirect(_landing_url(wa, user))

    @app.route('/auth/saml2/metadata')
    def saml2_metadata():
        auth = saml_auth.get_auth(wa, request)
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
