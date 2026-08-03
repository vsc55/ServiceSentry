#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for OIDC/OAuth2 SSO authentication integration.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_providers_oidc.py`` lives in ``tests/integration/test_providers_oidc.py``."""




# ── helpers ──────────────────────────────────────────────────────────────────

# ── Fixture ───────────────────────────────────────────────────────────────────

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


