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
    import lib.providers.saml.auth as saml_mod

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
        from lib.providers.saml import auth as saml_auth
        assert isinstance(saml_auth.is_available(), bool)


# ── _map_role ─────────────────────────────────────────────────────────────────

class TestSaml2MapRole:
    def test_admin_group_maps_to_admin(self):
        from lib.providers.saml.auth import _map_role
        assert _map_role(['Admins'], {'Admins': 'admin'}) == 'admin'

    def test_no_match_returns_empty_string(self):
        from lib.providers.saml.auth import _map_role
        assert _map_role(['Unknown'], {}) == ''

    def test_editor_maps_correctly(self):
        from lib.providers.saml.auth import _map_role
        assert _map_role(['Editors'], {'Editors': 'editor'}) == 'editor'

    def test_highest_priority_wins(self):
        from lib.providers.saml.auth import _map_role
        result = _map_role(
            ['Editors', 'Admins'],
            {'Admins': 'admin', 'Editors': 'editor'},
        )
        assert result == 'admin'

    def test_case_insensitive_match(self):
        from lib.providers.saml.auth import _map_role
        assert _map_role(['admins'], {'Admins': 'admin'}) == 'admin'


# ── sync_user ─────────────────────────────────────────────────────────────────



# ── Login integration ─────────────────────────────────────────────────────────



