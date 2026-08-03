#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for LDAP authentication integration.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_providers_ldap.py`` lives in ``tests/integration/test_providers_ldap.py``."""




# ── helpers ──────────────────────────────────────────────────────────────────

# ── is_available ─────────────────────────────────────────────────────────────

class TestLdapAvailability:
    def test_is_available_returns_bool(self):
        from lib.providers.ldap import auth as ldap_auth
        assert isinstance(ldap_auth.is_available(), bool)


# ── _map_role ─────────────────────────────────────────────────────────────────

class TestLdapMapRole:
    def test_admin_group_maps_to_admin(self):
        from lib.providers.ldap.auth import _map_role
        result = _map_role(['CN=Admins,DC=example,DC=com'],
                           {'CN=Admins,DC=example,DC=com': 'admin'})
        assert result == 'admin'

    def test_no_match_returns_empty_string(self):
        from lib.providers.ldap.auth import _map_role
        result = _map_role(['CN=Unknown'], {})
        assert result == ''

    def test_editor_maps_correctly(self):
        from lib.providers.ldap.auth import _map_role
        result = _map_role(['Editors'], {'Editors': 'editor'})
        assert result == 'editor'

    def test_highest_priority_wins(self):
        from lib.providers.ldap.auth import _map_role
        result = _map_role(
            ['CN=Editors', 'CN=Admins'],
            {'CN=Admins': 'admin', 'CN=Editors': 'editor'},
        )
        assert result == 'admin'


# ── authenticate ──────────────────────────────────────────────────────────────


# ── sync_user ─────────────────────────────────────────────────────────────────


# ── Login integration ─────────────────────────────────────────────────────────


# ── /api/ldap/test audit behaviour ───────────────────────────────────────────

