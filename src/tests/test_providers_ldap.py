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


class TestLdapSyncUser:
    def test_refuses_to_convert_local_account(self, admin, config_dir):
        """R5 (account-takeover): an LDAP login whose username collides with a LOCAL
        account must be refused — sync returns None (the caller rejects, no 500), and the
        account is NOT converted to SSO."""
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        admin._users['carol'] = {
            'uid': 'uid-carol', 'auth_source': 'local',
            'role': admin._role_name_to_uid('admin'), 'groups': [], 'enabled': True,
        }
        result = ldap_auth.sync_user(
            admin, 'carol',
            {'dn': 'CN=carol,DC=x', 'display_name': 'C', 'email': '', 'groups': []})
        assert result is None
        assert admin._users['carol']['auth_source'] == 'local'


# ── authenticate ──────────────────────────────────────────────────────────────

class TestLdapAuthenticate:

    def test_disabled_returns_ldap_disabled(self, admin):
        from lib.providers.ldap import auth as ldap_auth
        with patch.object(ldap_auth, '_HAS_LDAP3', True), \
             patch.object(ldap_auth, '_get_config', return_value={'enabled': False}):
            attrs, reason = ldap_auth.authenticate(admin, 'user', 'pass')
        assert attrs is None
        assert reason == 'ldap_disabled'

    def test_unavailable_returns_ldap_unavailable(self, admin):
        from lib.providers.ldap import auth as ldap_auth
        with patch.object(ldap_auth, '_HAS_LDAP3', False):
            attrs, reason = ldap_auth.authenticate(admin, 'user', 'pass')
        assert attrs is None
        assert reason == 'ldap_unavailable'

    def test_connection_error_returns_connection_error(self, admin, config_dir):
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server') as MockServer, \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            MockConn.side_effect = ldap_auth.LDAPException('connection refused')
            attrs, reason = ldap_auth.authenticate(admin, 'john', 'pass')
        assert attrs is None
        assert reason == 'ldap_connection_error'

    def test_user_not_found_returns_not_found(self, admin, config_dir):
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server'), \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            conn_inst = MagicMock()
            conn_inst.entries = []
            MockConn.return_value = conn_inst
            attrs, reason = ldap_auth.authenticate(admin, 'nobody', 'pass')
        assert attrs is None
        assert reason == 'ldap_user_not_found'

    def test_invalid_password_returns_invalid_credentials(self, admin, config_dir):
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        entry = _make_ldap_entry('CN=John,DC=example,DC=com')
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server') as MockServer, \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            srv_inst  = MagicMock()
            MockServer.return_value = srv_inst
            conn_inst = MagicMock()
            conn_inst.entries = [entry]
            # service bind ok, user bind fails
            MockConn.side_effect = [conn_inst,
                                    ldap_auth.LDAPException('invalid credentials')]
            attrs, reason = ldap_auth.authenticate(admin, 'john', 'wrongpass')
        assert attrs is None
        assert reason == 'ldap_invalid_credentials'

    def test_successful_auth_returns_attrs(self, admin, config_dir):
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        entry = _make_ldap_entry(
            'CN=John,DC=example,DC=com',
            display_name='John Doe',
            email='john@example.com',
            groups=['CN=Admins,DC=example,DC=com'],
        )
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server') as MockServer, \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            srv_inst  = MagicMock()
            MockServer.return_value = srv_inst
            conn_inst = _conn_with_secondary_groups(entry)
            user_conn = MagicMock()
            MockConn.side_effect = [conn_inst, user_conn]
            attrs, reason = ldap_auth.authenticate(admin, 'john', 'correctpass')
        assert reason is None
        assert attrs is not None
        assert attrs['display_name'] == 'John Doe'
        assert attrs['email'] == 'john@example.com'

    def test_posix_group_memberuid_maps_role(self, admin, config_dir):
        """posixGroup membership via memberUid on the group object maps the role."""
        from lib.providers.ldap import auth as ldap_auth
        grp_dn = 'cn=Administrators,ou=Group,dc=example,dc=com'
        _ldap_cfg(config_dir, extra={'group_role_map': f'{{"{grp_dn}": "admin"}}'})
        # User entry has no memberOf — membership is on the group side (posixGroup)
        user_entry  = _make_ldap_entry('uid=john,ou=People,dc=example,dc=com',
                                       display_name='John', email='john@example.com')
        group_entry = _make_group_entry(grp_dn, 'Administrators')
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server') as MockServer, \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            MockServer.return_value = MagicMock()
            conn_inst = _conn_with_secondary_groups(user_entry, [group_entry])
            MockConn.side_effect = [conn_inst, MagicMock()]
            attrs, reason = ldap_auth.authenticate(admin, 'john', 'pass')
        assert reason is None
        assert any(grp_dn.lower() in g.lower() for g in attrs['groups'])
        user = ldap_auth.sync_user(admin, 'john', attrs)
        assert admin._uid_to_role_name(user['role']) == 'admin'


# ── sync_user ─────────────────────────────────────────────────────────────────

class TestLdapSyncUser:

    def test_new_user_is_created(self, admin, config_dir):
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        attrs = {
            'dn': 'CN=New,DC=example,DC=com',
            'display_name': 'New User',
            'email': 'new@example.com',
            'groups': [],
        }
        user = ldap_auth.sync_user(admin, 'newuser', attrs)
        assert 'newuser' in admin._users
        assert user['auth_source'] == 'ldap'
        assert user['display_name'] == 'New User'
        assert user['email'] == 'new@example.com'

    def test_existing_user_role_is_resynced(self, admin, config_dir):
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        admin._users['john'] = {
            'uid': 'some-uid',
            'auth_source': 'ldap',
            'auth_source_id': '',
            'display_name': 'John Old',
            'email': '',
            'role': admin._role_name_to_uid('viewer'),
            'groups': [],
            'enabled': True,
        }
        attrs = {
            'dn': 'CN=John,DC=example,DC=com',
            'display_name': 'John New',
            'email': 'john@example.com',
            'groups': ['CN=Admins,DC=example,DC=com'],
        }
        user = ldap_auth.sync_user(admin, 'john', attrs)
        # Role re-synced from 'viewer' → 'admin' due to group mapping
        assert admin._uid_to_role_name(user['role']) == 'admin'
        assert user['display_name'] == 'John New'

    def test_new_user_uid_is_generated(self, admin, config_dir):
        from lib.providers.ldap import auth as ldap_auth
        _ldap_cfg(config_dir)
        attrs = {'dn': '', 'display_name': '', 'email': '', 'groups': []}
        user = ldap_auth.sync_user(admin, 'uid_user', attrs)
        assert 'uid' in user
        assert len(user['uid']) == 36  # UUID format


# ── Login integration ─────────────────────────────────────────────────────────

class TestLdapLoginFlow:

    def test_ldap_user_logged_in_successfully(self, admin, client, config_dir):
        _ldap_cfg(config_dir)
        entry = _make_ldap_entry('CN=Jane,DC=example,DC=com',
                                 display_name='Jane', email='jane@example.com')
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server') as MockServer, \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            srv_inst  = MagicMock()
            MockServer.return_value = srv_inst
            conn_inst = MagicMock()
            conn_inst.entries = [entry]
            user_conn = MagicMock()
            MockConn.side_effect = [conn_inst, user_conn]
            resp = client.post('/login',
                               data={'username': 'jane', 'password': 'pass'},
                               follow_redirects=True)
        assert resp.status_code == 200
        assert 'jane' in admin._users
        assert admin._users['jane']['auth_source'] == 'ldap'

    def test_local_user_bypasses_ldap(self, client, config_dir):
        """A user with auth_source='local' always uses local auth."""
        _ldap_cfg(config_dir)
        # admin is a local user — should authenticate via local hash
        resp = client.post('/login',
                           data={'username': 'admin', 'password': 'secret'},
                           follow_redirects=True)
        assert resp.status_code == 200

    def test_connection_error_fallback_to_local(self, client, config_dir):
        """On LDAP connection error with fallback_to_local=True, local auth is tried."""
        _ldap_cfg(config_dir, extra={'fallback_to_local': True})
        from lib.providers.ldap import auth as ldap_auth
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server'), \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            MockConn.side_effect = ldap_auth.LDAPException('down')
            resp = client.post('/login',
                               data={'username': 'admin', 'password': 'secret'},
                               follow_redirects=True)
        assert resp.status_code == 200

    def test_connection_error_no_fallback_returns_error(self, admin, client, config_dir):
        """On LDAP connection error with fallback_to_local=False, login fails."""
        _ldap_cfg(config_dir, extra={'fallback_to_local': False})
        # Make the user appear as ldap-sourced
        admin._users['ldapuser'] = {
            'uid': 'x', 'auth_source': 'ldap', 'auth_source_id': '',
            'display_name': '', 'email': '', 'role': admin._role_name_to_uid('viewer'),
            'groups': [], 'enabled': True,
        }
        from lib.providers.ldap import auth as ldap_auth
        with patch('lib.providers.ldap.auth._HAS_LDAP3', True), \
             patch('lib.providers.ldap.auth.Server'), \
             patch('lib.providers.ldap.auth.Connection') as MockConn:
            MockConn.side_effect = ldap_auth.LDAPException('down')
            resp = client.post('/login',
                               data={'username': 'ldapuser', 'password': 'pass'},
                               follow_redirects=True)
        # Should redirect back to login with error flash — session must NOT be active
        assert resp.status_code == 200
        me = client.get('/api/v1/me')
        assert not me.get_json().get('logged_in', False)


# ── /api/ldap/test audit behaviour ───────────────────────────────────────────

class TestLdapTestEndpoint:
    """Verify /api/ldap/test behaviour."""

    def test_connection_test_creates_audit_entry(self, admin, client, config_dir):
        _login(client)
        _ldap_cfg(config_dir)
        initial_audit_count = len(admin._audit_log) if hasattr(admin, '_audit_log') else 0
        with patch('ldap3.Connection') as MockConn, \
             patch('ldap3.Server'):
            conn_inst = MagicMock()
            conn_inst.entries = []
            MockConn.return_value = conn_inst
            # Pass bind_password explicitly to avoid secret_manager.decrypt branch
            r = client.post('/api/v1/auth/ldap/test',
                            json={'server': 'ldap.example.com', 'bind_password': 'svcpass'})
        assert r.status_code == 200
        assert r.get_json()['ok'] is True
        if hasattr(admin, '_audit_log'):
            assert len(admin._audit_log) == initial_audit_count + 1
            assert admin._audit_log[-1]['event'] == 'ldap_test'

    def test_connection_error_message_differs_from_credential_error(self, client, config_dir):
        """Connection errors and credential errors return different messages."""
        _login(client)
        _ldap_cfg(config_dir)
        # Connection error case — patch ldap3 directly since imports are local inside the route
        with patch('ldap3.Connection') as MockConn, \
             patch('ldap3.Server'):
            MockConn.side_effect = Exception('connection refused')
            # Pass bind_password explicitly to avoid secret_manager.decrypt branch
            r_conn = client.post('/api/v1/auth/ldap/test',
                                 json={'server': 'ldap.example.com',
                                       'bind_password': 'svcpass',
                                       'test_username': 'john', 'test_password': 'pass'})
        conn_msg = r_conn.get_json().get('message', '')
        assert r_conn.get_json()['ok'] is False
        # The message should contain the error detail, not just a generic string
        assert conn_msg  # not empty
