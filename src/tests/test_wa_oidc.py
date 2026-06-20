#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for OIDC/OAuth2 SSO authentication integration."""

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

def _oidc_cfg(config_dir, extra=None):
    import os
    cfg_path = os.path.join(config_dir, 'config.json')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    cfg['oidc'] = {
        'enabled': True,
        'provider_url': 'https://idp.example.com',
        'client_id': 'my-client',
        'client_secret': 'my-secret',
        'scopes': 'openid email profile',
        'username_claim': 'preferred_username',
        'email_claim': 'email',
        'name_claim': 'name',
        'groups_claim': 'groups',
        'group_role_map': '{"Admins": "admin"}',
        'auto_create_users': True,
        **(extra or {}),
    }
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)


def _make_userinfo(username='jane', email='jane@example.com', name='Jane Doe', groups=None):
    return {
        'sub': f'sub-{username}',
        'preferred_username': username,
        'email': email,
        'name': name,
        'groups': groups or [],
    }


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def oidc_admin_client(config_dir, var_dir):
    """WebAdmin + test client with OIDC routes registered (authlib mocked)."""
    import lib.web_admin.auth.oidc_auth as oidc_mod

    with patch.object(oidc_mod, '_HAS_AUTHLIB', True):
        wa = WebAdmin(config_dir, 'admin', 'secret', var_dir,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config['TESTING'] = True
        yield wa, wa.app.test_client()


# ── is_available ──────────────────────────────────────────────────────────────

class TestOidcAvailability:
    def test_is_available_returns_bool(self):
        from lib.web_admin.auth import oidc_auth
        assert isinstance(oidc_auth.is_available(), bool)


# ── _map_role ─────────────────────────────────────────────────────────────────

class TestOidcMapRole:
    def test_admin_group_maps_to_admin(self):
        from lib.web_admin.auth.oidc_auth import _map_role
        assert _map_role(['Admins'], {'Admins': 'admin'}) == 'admin'

    def test_no_match_returns_empty_string(self):
        from lib.web_admin.auth.oidc_auth import _map_role
        assert _map_role(['Unknown'], {}) == ''

    def test_editor_maps_correctly(self):
        from lib.web_admin.auth.oidc_auth import _map_role
        assert _map_role(['Editors'], {'Editors': 'editor'}) == 'editor'

    def test_highest_priority_wins(self):
        from lib.web_admin.auth.oidc_auth import _map_role
        result = _map_role(
            ['Editors', 'Admins'],
            {'Admins': 'admin', 'Editors': 'editor'},
        )
        assert result == 'admin'

    def test_case_insensitive_match(self):
        from lib.web_admin.auth.oidc_auth import _map_role
        assert _map_role(['admins'], {'Admins': 'admin'}) == 'admin'


# ── sync_user ─────────────────────────────────────────────────────────────────

class TestOidcSyncUser:

    def test_new_user_is_created(self, admin, config_dir):
        from lib.web_admin.auth import oidc_auth
        _oidc_cfg(config_dir)
        user = oidc_auth.sync_user(admin, _make_userinfo('alice', 'alice@example.com', 'Alice Smith'))
        assert 'alice' in admin._users
        assert user['auth_source'] == 'oidc'
        assert user['display_name'] == 'Alice Smith'
        assert user['email'] == 'alice@example.com'

    def test_existing_user_role_is_resynced(self, admin, config_dir):
        from lib.web_admin.auth import oidc_auth
        _oidc_cfg(config_dir)
        admin._users['bob'] = {
            'uid': 'some-uid',
            'auth_source': 'oidc',
            'auth_source_id': 'sub-bob',
            'display_name': 'Bob Old',
            'email': '',
            'role': admin._role_name_to_uid('viewer'),
            'groups': [],
            'enabled': True,
        }
        user = oidc_auth.sync_user(
            admin,
            _make_userinfo('bob', 'bob@example.com', 'Bob New', groups=['Admins']),
        )
        assert admin._uid_to_role_name(user['role']) == 'admin'
        assert user['display_name'] == 'Bob New'

    def test_auto_create_false_blocks_new_user(self, admin, config_dir):
        from lib.web_admin.auth import oidc_auth
        _oidc_cfg(config_dir, extra={'auto_create_users': False})
        result = oidc_auth.sync_user(admin, _make_userinfo('newbie'))
        assert result is None
        assert 'newbie' not in admin._users

    def test_auto_create_false_allows_existing_user(self, admin, config_dir):
        from lib.web_admin.auth import oidc_auth
        _oidc_cfg(config_dir, extra={'auto_create_users': False})
        admin._users['existing'] = {
            'uid': 'uid-existing',
            'auth_source': 'oidc',
            'auth_source_id': 'sub-existing',
            'display_name': 'Existing User',
            'email': '',
            'role': admin._role_name_to_uid('viewer'),
            'groups': [],
            'enabled': True,
        }
        user = oidc_auth.sync_user(admin, _make_userinfo('existing'))
        assert user is not None

    def test_new_user_uid_is_generated(self, admin, config_dir):
        from lib.web_admin.auth import oidc_auth
        _oidc_cfg(config_dir)
        user = oidc_auth.sync_user(admin, _make_userinfo('uid_test'))
        assert 'uid' in user
        assert len(user['uid']) == 36

    def test_empty_userinfo_returns_none(self, admin, config_dir):
        from lib.web_admin.auth import oidc_auth
        _oidc_cfg(config_dir)
        assert oidc_auth.sync_user(admin, {}) is None

    def test_sub_stored_as_auth_source_id(self, admin, config_dir):
        from lib.web_admin.auth import oidc_auth
        _oidc_cfg(config_dir)
        user = oidc_auth.sync_user(admin, _make_userinfo('carol'))
        assert user['auth_source_id'] == 'sub-carol'


# ── Login integration ─────────────────────────────────────────────────────────

class TestOidcLoginFlow:

    def test_login_page_shows_sso_button(self, oidc_admin_client, config_dir):
        """SSO button appears on /login when OIDC is enabled."""
        wa, client = oidc_admin_client
        _oidc_cfg(config_dir)
        resp = client.get('/login')
        assert resp.status_code == 200
        assert b'/auth/oidc/login' in resp.data

    def test_oidc_login_triggers_redirect(self, oidc_admin_client, config_dir):
        """GET /auth/oidc/login redirects via the OAuth client."""
        wa, client = oidc_admin_client
        _oidc_cfg(config_dir)
        import lib.web_admin.auth.oidc_auth as oidc_mod
        from flask import redirect as flask_redirect
        mock_oauth = MagicMock()
        mock_oauth.authorize_redirect.return_value = flask_redirect(
            'https://idp.example.com/authorize?response_type=code'
        )
        with patch.object(oidc_mod, 'get_client', return_value=mock_oauth):
            resp = client.get('/auth/oidc/login')
        assert resp.status_code in (301, 302)

    def test_callback_creates_user_and_session(self, oidc_admin_client, config_dir):
        """Successful OIDC callback creates user and establishes a session."""
        wa, client = oidc_admin_client
        _oidc_cfg(config_dir)
        import lib.web_admin.auth.oidc_auth as oidc_mod
        userinfo = _make_userinfo('carol', 'carol@example.com', 'Carol OIDC')
        mock_oauth = MagicMock()
        mock_oauth.authorize_access_token.return_value = {'userinfo': userinfo}
        with patch.object(oidc_mod, 'get_client', return_value=mock_oauth):
            resp = client.get('/auth/oidc/callback', follow_redirects=True)
        assert resp.status_code == 200
        assert 'carol' in wa._users
        assert wa._users['carol']['auth_source'] == 'oidc'

    def test_callback_group_maps_to_admin_role(self, oidc_admin_client, config_dir):
        """OIDC group claim is mapped to the correct role on callback."""
        wa, client = oidc_admin_client
        _oidc_cfg(config_dir)
        import lib.web_admin.auth.oidc_auth as oidc_mod
        userinfo = _make_userinfo('dana', groups=['Admins'])
        mock_oauth = MagicMock()
        mock_oauth.authorize_access_token.return_value = {'userinfo': userinfo}
        with patch.object(oidc_mod, 'get_client', return_value=mock_oauth):
            client.get('/auth/oidc/callback', follow_redirects=True)
        assert 'dana' in wa._users
        assert wa._uid_to_role_name(wa._users['dana']['role']) == 'admin'

    def test_callback_token_error_returns_to_login(self, oidc_admin_client, config_dir):
        """Token exchange failure redirects to /login with an error flash."""
        wa, client = oidc_admin_client
        _oidc_cfg(config_dir)
        import lib.web_admin.auth.oidc_auth as oidc_mod
        mock_oauth = MagicMock()
        mock_oauth.authorize_access_token.side_effect = Exception('token error')
        with patch.object(oidc_mod, 'get_client', return_value=mock_oauth):
            resp = client.get('/auth/oidc/callback', follow_redirects=True)
        assert resp.status_code == 200
        assert b'name="username"' in resp.data  # back on /login

    def test_auto_create_false_blocks_unknown_user(self, oidc_admin_client, config_dir):
        """auto_create_users=False rejects unknown users in the OIDC callback."""
        wa, client = oidc_admin_client
        _oidc_cfg(config_dir, extra={'auto_create_users': False})
        import lib.web_admin.auth.oidc_auth as oidc_mod
        mock_oauth = MagicMock()
        mock_oauth.authorize_access_token.return_value = {
            'userinfo': _make_userinfo('stranger'),
        }
        with patch.object(oidc_mod, 'get_client', return_value=mock_oauth):
            resp = client.get('/auth/oidc/callback', follow_redirects=True)
        assert resp.status_code == 200
        assert 'stranger' not in wa._users
        assert b'name="username"' in resp.data

    def test_disabled_account_blocked_at_callback(self, oidc_admin_client, config_dir):
        """A disabled OIDC user is blocked at the callback."""
        wa, client = oidc_admin_client
        _oidc_cfg(config_dir)
        wa._users['dis_user'] = {
            'uid': 'uid-dis',
            'auth_source': 'oidc',
            'auth_source_id': 'sub-dis_user',
            'display_name': 'Disabled',
            'email': '',
            'role': wa._role_name_to_uid('viewer'),
            'groups': [],
            'enabled': False,
        }
        import lib.web_admin.auth.oidc_auth as oidc_mod
        mock_oauth = MagicMock()
        mock_oauth.authorize_access_token.return_value = {
            'userinfo': _make_userinfo('dis_user'),
        }
        with patch.object(oidc_mod, 'get_client', return_value=mock_oauth):
            resp = client.get('/auth/oidc/callback', follow_redirects=True)
        assert resp.status_code == 200
        assert b'name="username"' in resp.data
        assert not wa._users['dis_user']['enabled']
