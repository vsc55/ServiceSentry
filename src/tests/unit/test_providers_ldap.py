#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for LDAP authentication integration."""

from unittest.mock import MagicMock, patch

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ── helpers ──────────────────────────────────────────────────────────────────

def _login(client, username='admin', password='secret'):
    client.post('/login', data={'username': username, 'password': password})


def _ldap_cfg(config_dir, extra=None):
    import json, os
    cfg_path = os.path.join(config_dir, 'config.json')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    cfg['ldap'] = {
        'enabled': True,
        'server': 'ldap.example.com',
        'port': 389,
        'use_ssl': False,
        'timeout': 5,
        'bind_dn': 'cn=svc,dc=example,dc=com',
        'bind_password': 'svcpass',
        'base_dn': 'dc=example,dc=com',
        'user_filter': '(sAMAccountName={username})',
        'email_attr': 'mail',
        'name_attr': 'displayName',
        'group_attr': 'memberOf',
        'group_role_map': '{"CN=Admins,DC=example,DC=com": "admin"}',
        'fallback_to_local': True,
        **(extra or {}),
    }
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)


def _make_ldap_entry(dn, display_name='John Doe', email='john@example.com', groups=None):
    entry = MagicMock()
    entry.entry_dn = dn

    def _attr(name, values):
        a = MagicMock()
        a.values = values
        return a

    entry.displayName = _attr('displayName', [display_name])
    entry.mail        = _attr('mail',        [email])
    entry.memberOf    = _attr('memberOf',    groups or [])
    return entry


def _make_group_entry(dn, cn):
    """Minimal mock of an LDAP group entry (used for secondary group search)."""
    entry = MagicMock()
    entry.entry_dn = dn
    cn_attr = MagicMock()
    cn_attr.values = [cn]
    entry.cn = cn_attr
    return entry


def _conn_with_secondary_groups(user_entry, group_entries=None):
    """Return a mock Connection whose search() serves user_entry on the first
    call and group_entries on subsequent calls (posixGroup topology test)."""
    conn = MagicMock()
    group_entries = group_entries or []
    conn.entries = [user_entry]
    n = [0]

    def _search(base_dn, search_filter, search_scope=None, attributes=None):
        seq = [[user_entry], group_entries]
        conn.entries = seq[min(n[0], len(seq) - 1)]
        n[0] += 1
        return base_dn, search_filter, search_scope, attributes

    conn.search = _search
    return conn


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

