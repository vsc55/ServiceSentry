#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for SAML2 SSO authentication integration."""

import json
from unittest.mock import MagicMock, patch

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ── helpers ──────────────────────────────────────────────────────────────────

def _saml2_cfg(config_dir, extra=None):
    import os
    cfg_path = os.path.join(config_dir, 'config.json')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    cfg['saml2'] = {
        'enabled': True,
        'idp_entity_id': 'https://idp.example.com',
        'idp_sso_url': 'https://idp.example.com/saml2/sso',
        'idp_cert': 'MIIC...',
        'sp_entity_id': 'https://myapp.example.com',
        'sp_acs_url': 'https://myapp.example.com/auth/saml2/acs',
        'sp_cert': '',
        'sp_key': '',
        'username_attr': 'uid',
        'email_attr': 'email',
        'name_attr': 'displayName',
        'groups_attr': 'groups',
        'group_role_map': '{"Admins": "admin"}',
        'auto_create_users': True,
        **(extra or {}),
    }
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)


def _make_saml_attrs(uid='jane', email='jane@example.com',
                     display_name='Jane SAML', groups=None):
    """Return a SAML attribute dict as onelogin-python-saml would produce."""
    return {
        'uid':          [uid],
        'email':        [email],
        'displayName':  [display_name],
        'groups':       groups or [],
    }


def _mock_auth(name_id='jane', attrs=None, errors=None, authenticated=True):
    """Return a pre-configured mock for OneLogin_Saml2_Auth."""
    m = MagicMock()
    m.get_errors.return_value = errors or []
    m.is_authenticated.return_value = authenticated
    m.get_nameid.return_value = name_id
    m.get_attributes.return_value = attrs if attrs is not None else _make_saml_attrs(name_id)
    m.login.return_value = 'https://idp.example.com/saml2/sso?SAMLRequest=abc'
    # Replay/InResponseTo plumbing (must be JSON-serialisable for the session).
    m.get_last_request_id.return_value = 'req-id-123'
    m.get_last_assertion_id.return_value = None      # None → skip the one-time cache
    return m


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def saml2_admin_client(config_dir, var_dir):
    """WebAdmin + test client with SAML2 routes registered (python3-saml mocked)."""
    import lib.web_admin.auth.saml_auth as saml_mod

    with patch.object(saml_mod, '_HAS_SAML2', True):
        wa = WebAdmin(config_dir, 'admin', 'secret', var_dir,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config['TESTING'] = True
        client = wa.app.test_client()
        # Simulate a prior SP-initiated /auth/saml2/login: the ACS now requires a
        # session-bound request id (rejects unsolicited responses). Consumed (pop) per
        # ACS request; the unsolicited-rejection test clears it explicitly.
        with client.session_transaction() as _s:
            _s['_saml_req_id'] = 'req-id-123'
        yield wa, client


# ── is_available ──────────────────────────────────────────────────────────────

class TestSaml2Availability:
    def test_is_available_returns_bool(self):
        from lib.web_admin.auth import saml_auth
        assert isinstance(saml_auth.is_available(), bool)


# ── _map_role ─────────────────────────────────────────────────────────────────

class TestSaml2MapRole:
    def test_admin_group_maps_to_admin(self):
        from lib.web_admin.auth.saml_auth import _map_role
        assert _map_role(['Admins'], {'Admins': 'admin'}) == 'admin'

    def test_no_match_returns_empty_string(self):
        from lib.web_admin.auth.saml_auth import _map_role
        assert _map_role(['Unknown'], {}) == ''

    def test_editor_maps_correctly(self):
        from lib.web_admin.auth.saml_auth import _map_role
        assert _map_role(['Editors'], {'Editors': 'editor'}) == 'editor'

    def test_highest_priority_wins(self):
        from lib.web_admin.auth.saml_auth import _map_role
        result = _map_role(
            ['Editors', 'Admins'],
            {'Admins': 'admin', 'Editors': 'editor'},
        )
        assert result == 'admin'

    def test_case_insensitive_match(self):
        from lib.web_admin.auth.saml_auth import _map_role
        assert _map_role(['admins'], {'Admins': 'admin'}) == 'admin'


# ── sync_user ─────────────────────────────────────────────────────────────────

class TestSaml2SyncUser:

    def test_new_user_is_created(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir)
        attrs = _make_saml_attrs('alice', 'alice@example.com', 'Alice SAML')
        user = saml_auth.sync_user(admin, 'alice', attrs)
        assert 'alice' in admin._users
        assert user['auth_source'] == 'saml2'
        assert user['display_name'] == 'Alice SAML'
        assert user['email'] == 'alice@example.com'

    def test_name_id_used_when_no_username_attr(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir, extra={'username_attr': ''})
        attrs = {}  # no uid attr
        user = saml_auth.sync_user(admin, 'nameid-user', attrs)
        assert 'nameid-user' in admin._users

    def test_existing_user_role_is_resynced(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir)
        admin._users['bob'] = {
            'uid': 'some-uid',
            'auth_source': 'saml2',
            'auth_source_id': 'bob',
            'display_name': 'Bob Old',
            'email': '',
            'role': admin._role_name_to_uid('viewer'),
            'groups': [],
            'enabled': True,
        }
        attrs = _make_saml_attrs('bob', 'bob@example.com', 'Bob New', groups=['Admins'])
        user = saml_auth.sync_user(admin, 'bob', attrs)
        assert admin._uid_to_role_name(user['role']) == 'admin'
        assert user['display_name'] == 'Bob New'

    def test_auto_create_false_blocks_new_user(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir, extra={'auto_create_users': False})
        result = saml_auth.sync_user(admin, 'newbie', _make_saml_attrs('newbie'))
        assert result is None
        assert 'newbie' not in admin._users

    def test_auto_create_false_allows_existing_user(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir, extra={'auto_create_users': False})
        admin._users['existing'] = {
            'uid': 'uid-existing',
            'auth_source': 'saml2',
            'auth_source_id': 'existing',
            'display_name': 'Existing',
            'email': '',
            'role': admin._role_name_to_uid('viewer'),
            'groups': [],
            'enabled': True,
        }
        user = saml_auth.sync_user(admin, 'existing', _make_saml_attrs('existing'))
        assert user is not None

    def test_new_user_uid_is_generated(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir)
        user = saml_auth.sync_user(admin, 'uid_test', _make_saml_attrs('uid_test'))
        assert 'uid' in user
        assert len(user['uid']) == 36

    def test_name_id_stored_as_auth_source_id(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir)
        user = saml_auth.sync_user(admin, 'uid=carol,dc=example,dc=com',
                                   _make_saml_attrs('carol'))
        assert user['auth_source_id'] == 'uid=carol,dc=example,dc=com'

    def test_empty_name_id_and_no_attrs_returns_none(self, admin, config_dir):
        from lib.web_admin.auth import saml_auth
        _saml2_cfg(config_dir, extra={'username_attr': ''})
        result = saml_auth.sync_user(admin, '', {})
        assert result is None


# ── Login integration ─────────────────────────────────────────────────────────

class TestSaml2LoginFlow:

    def test_login_page_shows_saml2_button(self, saml2_admin_client, config_dir):
        """SAML2 button appears on /login when SAML2 is enabled."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        resp = client.get('/login')
        assert resp.status_code == 200
        assert b'/auth/saml2/login' in resp.data

    def test_saml2_login_redirects_to_idp(self, saml2_admin_client, config_dir):
        """GET /auth/saml2/login redirects to IdP SSO URL."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        import lib.web_admin.auth.saml_auth as saml_mod
        mock_auth = _mock_auth()
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            resp = client.get('/auth/saml2/login')
        assert resp.status_code in (301, 302)
        assert b'idp.example.com' in resp.headers['Location'].encode()

    def test_acs_creates_user_and_session(self, saml2_admin_client, config_dir):
        """Successful SAMLResponse creates user and establishes a session."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        import lib.web_admin.auth.saml_auth as saml_mod
        mock_auth = _mock_auth('carol', _make_saml_attrs('carol', 'carol@example.com'))
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            resp = client.post('/auth/saml2/acs',
                               data={'SAMLResponse': 'base64data'},
                               follow_redirects=True)
        assert resp.status_code == 200
        assert 'carol' in wa._users
        assert wa._users['carol']['auth_source'] == 'saml2'

    def test_acs_unsolicited_response_rejected(self, saml2_admin_client, config_dir):
        """A response with no session-bound request id (unsolicited / stolen-assertion
        replay / login-CSRF) is rejected before processing — anti-replay."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        import lib.web_admin.auth.saml_auth as saml_mod
        mock_auth = _mock_auth('mallory', _make_saml_attrs('mallory'))
        with client.session_transaction() as s:
            s.pop('_saml_req_id', None)       # attacker never went through /login
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            resp = client.post('/auth/saml2/acs', data={'SAMLResponse': 'stolen'},
                               follow_redirects=True)
        assert resp.status_code == 200
        assert b'name="username"' in resp.data          # bounced back to login
        assert 'mallory' not in wa._users               # never provisioned
        mock_auth.process_response.assert_not_called()  # rejected before processing

    def test_acs_group_maps_to_admin_role(self, saml2_admin_client, config_dir):
        """SAML2 groups claim is mapped to the correct role on ACS."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        import lib.web_admin.auth.saml_auth as saml_mod
        attrs = _make_saml_attrs('dana', groups=['Admins'])
        mock_auth = _mock_auth('dana', attrs)
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            client.post('/auth/saml2/acs', data={'SAMLResponse': 'base64data'},
                        follow_redirects=True)
        assert 'dana' in wa._users
        assert wa._uid_to_role_name(wa._users['dana']['role']) == 'admin'

    def test_acs_saml_errors_redirect_to_login(self, saml2_admin_client, config_dir):
        """SAML2 assertion errors redirect back to /login."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        import lib.web_admin.auth.saml_auth as saml_mod
        mock_auth = _mock_auth(errors=['invalid_signature'])
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            resp = client.post('/auth/saml2/acs',
                               data={'SAMLResponse': 'bad'},
                               follow_redirects=True)
        assert resp.status_code == 200
        assert b'name="username"' in resp.data

    def test_acs_not_authenticated_redirects_to_login(self, saml2_admin_client, config_dir):
        """ACS returning is_authenticated=False redirects to /login."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        import lib.web_admin.auth.saml_auth as saml_mod
        mock_auth = _mock_auth(authenticated=False)
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            resp = client.post('/auth/saml2/acs',
                               data={'SAMLResponse': 'x'},
                               follow_redirects=True)
        assert resp.status_code == 200
        assert b'name="username"' in resp.data

    def test_acs_auto_create_false_blocks_unknown_user(self, saml2_admin_client, config_dir):
        """auto_create_users=False rejects unknown users in ACS."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir, extra={'auto_create_users': False})
        import lib.web_admin.auth.saml_auth as saml_mod
        mock_auth = _mock_auth('stranger', _make_saml_attrs('stranger'))
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            resp = client.post('/auth/saml2/acs',
                               data={'SAMLResponse': 'x'},
                               follow_redirects=True)
        assert resp.status_code == 200
        assert 'stranger' not in wa._users
        assert b'name="username"' in resp.data

    def test_acs_disabled_account_blocked(self, saml2_admin_client, config_dir):
        """A disabled SAML2 user is blocked at the ACS endpoint."""
        wa, client = saml2_admin_client
        _saml2_cfg(config_dir)
        wa._users['dis_saml'] = {
            'uid': 'uid-dis',
            'auth_source': 'saml2',
            'auth_source_id': 'dis_saml',
            'display_name': 'Disabled',
            'email': '',
            'role': wa._role_name_to_uid('viewer'),
            'groups': [],
            'enabled': False,
        }
        import lib.web_admin.auth.saml_auth as saml_mod
        mock_auth = _mock_auth('dis_saml', _make_saml_attrs('dis_saml'))
        with patch.object(saml_mod, 'get_auth', return_value=mock_auth):
            resp = client.post('/auth/saml2/acs',
                               data={'SAMLResponse': 'x'},
                               follow_redirects=True)
        assert resp.status_code == 200
        assert b'name="username"' in resp.data
        assert not wa._users['dis_saml']['enabled']
