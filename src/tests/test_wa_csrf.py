#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSRF protection (double-submit token) — enabled explicitly here; the shared
fixture disables it so the rest of the suite needs no token plumbing."""

import json
import os

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _login_csrf(c):
    """Log in while CSRF is enforced: GET /login to seed the token, then POST it."""
    c.get('/login')
    with c.session_transaction() as s:
        tok = s['_csrf']
    r = c.post('/login', data={'username': 'admin', 'password': 'secret',
                               'csrf_token': tok}, follow_redirects=True)
    return tok, r


class TestCsrf:
    def _client(self, admin):
        admin._csrf_enabled = True
        return admin.app.test_client()

    def test_login_requires_token(self, admin):
        c = self._client(admin)
        # POST without the token → rejected (redirect to login, not logged in).
        c.get('/login')
        r = c.post('/login', data={'username': 'admin', 'password': 'secret'},
                   follow_redirects=True)
        assert b'modules-container' not in r.data

    def test_login_with_token_succeeds(self, admin):
        c = self._client(admin)
        _tok, r = _login_csrf(c)
        assert b'modules-container' in r.data

    def test_api_mutation_without_token_rejected(self, admin):
        c = self._client(admin)
        _login_csrf(c)
        r = c.put('/api/v1/config', json={'monitoring': {'timer_check': 77}})
        assert r.status_code == 403

    def test_api_mutation_with_token_allowed(self, admin):
        c = self._client(admin)
        tok, _ = _login_csrf(c)
        r = c.put('/api/v1/config', json={'monitoring': {'timer_check': 77}},
                  headers={'X-CSRF-Token': tok})
        assert r.status_code != 403

    def test_get_never_blocked(self, admin):
        c = self._client(admin)
        _login_csrf(c)
        assert c.get('/api/v1/config').status_code == 200

    def test_scim_exempt_from_csrf(self, admin, config_dir):
        # SCIM is token-authenticated (no cookies) → exempt from CSRF; a POST with a
        # valid bearer and no CSRF token must not be 403'd by the CSRF gate.
        admin._csrf_enabled = True
        token = 'scimtoken_0123456789abcdef'
        p = os.path.join(config_dir, 'config.json')
        try:
            with open(p, encoding='utf-8') as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        cfg['scim'] = {'enabled': True, 'token': token, 'default_role': '', 'auto_disable': True}
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
        admin._config_mgr.invalidate()
        admin._read_config_file(admin._CONFIG_FILE)
        c = admin.app.test_client()
        r = c.post('/scim/v2/Users', headers={'Authorization': f'Bearer {token}'},
                   json={'userName': 'csrf_exempt@x.com', 'active': True})
        assert r.status_code != 403
