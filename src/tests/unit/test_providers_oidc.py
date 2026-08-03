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
    import lib.providers.oidc.auth as oidc_mod

    with patch.object(oidc_mod, '_HAS_AUTHLIB', True):
        wa = WebAdmin(config_dir, 'admin', 'secret', var_dir,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config['TESTING'] = True
        yield wa, wa.app.test_client()


# ── is_available ──────────────────────────────────────────────────────────────

class TestOidcAvailability:
    def test_is_available_returns_bool(self):
        from lib.providers.oidc import auth as oidc_auth
        assert isinstance(oidc_auth.is_available(), bool)


# ── _map_role ─────────────────────────────────────────────────────────────────

class TestOidcMapRole:
    def test_admin_group_maps_to_admin(self):
        from lib.providers.oidc.auth import _map_role
        assert _map_role(['Admins'], {'Admins': 'admin'}) == 'admin'

    def test_no_match_returns_empty_string(self):
        from lib.providers.oidc.auth import _map_role
        assert _map_role(['Unknown'], {}) == ''

    def test_editor_maps_correctly(self):
        from lib.providers.oidc.auth import _map_role
        assert _map_role(['Editors'], {'Editors': 'editor'}) == 'editor'

    def test_highest_priority_wins(self):
        from lib.providers.oidc.auth import _map_role
        result = _map_role(
            ['Editors', 'Admins'],
            {'Admins': 'admin', 'Editors': 'editor'},
        )
        assert result == 'admin'

    def test_case_insensitive_match(self):
        from lib.providers.oidc.auth import _map_role
        assert _map_role(['admins'], {'Admins': 'admin'}) == 'admin'


# ── sync_user ─────────────────────────────────────────────────────────────────



# ── Login integration ─────────────────────────────────────────────────────────



