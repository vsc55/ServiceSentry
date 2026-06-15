#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host registry API — /api/v1/hosts (GET/POST/PUT/DELETE)."""

import copy
from unittest.mock import patch

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_HOST = {
    'name': 'srv-1', 'address': '10.0.0.5', 'tags': ['prod'],
    'profiles': {'ssh': {'user': 'root', 'ssh_password': 'p@ss', 'port': 22}},
}


class TestApiHosts:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/hosts').status_code == 401

    def test_create_list_and_mask(self, client, admin):
        _login(client)
        r = client.post('/api/v1/hosts', json=_HOST)
        assert r.status_code == 200
        uid = r.get_json()['uid']

        hosts = client.get('/api/v1/hosts').get_json()['hosts']
        h = next(x for x in hosts if x['uid'] == uid)
        assert h['name'] == 'srv-1' and h['address'] == '10.0.0.5'
        assert h['tags'] == ['prod']
        # Secret masked in the API payload, non-secret fields visible.
        assert h['profiles']['ssh']['ssh_password'] is None
        assert h['profiles']['ssh']['user'] == 'root'
        # …but stored (decrypted) for the monitor to use.
        assert admin._hosts_store.get(uid)['profiles']['ssh']['ssh_password'] == 'p@ss'

    def test_kind_and_maintenance_persist(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/hosts', json={
            'name': 'remote-1', 'address': '10.0.0.7', 'kind': 'remote',
            'maintenance': True,
            'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': 'x'}},
        }).get_json()['uid']
        h = admin._hosts_store.get(uid)
        assert h['kind'] == 'remote' and h['maintenance'] is True
        # Round-trips through the API too (masked secret).
        api = next(x for x in client.get('/api/v1/hosts').get_json()['hosts']
                   if x['uid'] == uid)
        assert api['kind'] == 'remote' and api['maintenance'] is True
        assert api['profiles']['ssh']['ssh_password'] is None

    def test_status_derived_from_checks(self, client, admin):
        """The listing carries a per-host monitoring status built from the
        daemon's status file and each check's host_uid binding."""
        import json
        import os

        _login(client)
        uids = {n: client.post('/api/v1/hosts', json={'name': n, 'address': f'10.0.0.{i}'})
                .get_json()['uid']
                for i, n in enumerate(('ok', 'err', 'pend', 'none', 'maint'), start=20)}
        client.put(f"/api/v1/hosts/{uids['maint']}", json={
            'name': 'maint', 'address': '10.0.0.24', 'maintenance': True})

        modules = {'web': {'enabled': True, 'list': {
            'c_ok':    {'host_uid': uids['ok'],    'enabled': True},
            'c_err':   {'host_uid': uids['err'],   'enabled': True},
            'c_pend':  {'host_uid': uids['pend'],  'enabled': True},
            'c_maint': {'host_uid': uids['maint'], 'enabled': True},
            'c_off':   {'host_uid': uids['none'],  'enabled': False},  # disabled → ignored
        }}}
        assert admin._save_config_file(admin._MODULES_FILE, modules)
        admin._check_state_store.persist_status({'web': {
            'c_ok':    {'status': True},
            'c_err':   {'status': False},
            'c_maint': {'status': True},
            # c_pend has no entry → pending/no data
        }})

        hosts = {h['uid']: h for h in client.get('/api/v1/hosts').get_json()['hosts']}
        assert hosts[uids['ok']]['status'] == 'ok'
        assert hosts[uids['err']]['status'] == 'error'
        assert hosts[uids['pend']]['status'] == 'warning'   # checks bound, no data yet
        assert hosts[uids['none']]['status'] == ''          # only a disabled check
        # Maintenance is a UI overlay: the backend still reports the monitoring
        # state (here the check is OK), and the frontend shows "Maintenance".
        assert hosts[uids['maint']]['status'] == 'ok'

    def test_module_counts_in_listing(self, client, admin):
        """The listing reports modules added vs active per host: total = the
        host's saved module list ∪ modules with a bound check; active = those
        with at least one enabled check."""
        _login(client)
        a = client.post('/api/v1/hosts', json={'name': 'a', 'address': '10.1.0.1'}).get_json()['uid']
        b = client.post('/api/v1/hosts', json={'name': 'b', 'address': '10.1.0.2'}).get_json()['uid']
        # Host A: 'web' added with an enabled check + 'cpu' added with no check yet.
        client.put(f'/api/v1/hosts/{a}', json={
            'name': 'a', 'address': '10.1.0.1', 'modules': ['web', 'cpu']})
        modules = {
            'web': {'enabled': True, 'list': {'w1': {'host_uid': a, 'enabled': True}}},
            # Host B: only a disabled check, and 'cpu' not in any saved list.
            'cpu': {'enabled': True, 'list': {'c1': {'host_uid': b, 'enabled': False}}},
        }
        assert admin._save_config_file(admin._MODULES_FILE, modules)

        hosts = {h['uid']: h for h in client.get('/api/v1/hosts').get_json()['hosts']}
        # A: web (active) + cpu (added, no check) → 1 active / 2 total
        assert hosts[a]['modules_total'] == 2 and hosts[a]['modules_active'] == 1
        # B: cpu bound but disabled → 1 total, 0 active
        assert hosts[b]['modules_total'] == 1 and hosts[b]['modules_active'] == 0

    def test_create_requires_name(self, client):
        _login(client)
        assert client.post('/api/v1/hosts', json={'address': '1.2.3.4'}).status_code == 400

    def test_duplicate_name_rejected(self, client):
        _login(client)
        assert client.post('/api/v1/hosts', json={'name': 'dup'}).status_code == 200
        assert client.post('/api/v1/hosts', json={'name': 'dup'}).status_code == 400

    def test_update_restores_masked_secret(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/hosts', json=_HOST).get_json()['uid']
        # Client re-sends the profile with the secret masked (None) — the route
        # must restore the stored value instead of wiping it.
        upd = {'name': 'srv-1b', 'address': '10.0.0.6',
               'profiles': {'ssh': {'user': 'root', 'ssh_password': None, 'port': 22}}}
        assert client.put(f'/api/v1/hosts/{uid}', json=upd).status_code == 200
        h = admin._hosts_store.get(uid)
        assert h['name'] == 'srv-1b' and h['address'] == '10.0.0.6'
        assert h['profiles']['ssh']['ssh_password'] == 'p@ss'   # preserved

    def test_update_unknown_uid(self, client):
        _login(client)
        assert client.put('/api/v1/hosts/nope', json=_HOST).status_code == 404

    def test_delete(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/hosts', json=_HOST).get_json()['uid']
        assert client.delete(f'/api/v1/hosts/{uid}').status_code == 200
        assert admin._hosts_store.get(uid) is None
        assert client.delete(f'/api/v1/hosts/{uid}').status_code == 404


class TestTestSsh:
    """POST /api/v1/hosts/test_ssh probes the SSH connection without saving."""

    def test_probe_uses_submitted_fields(self, client):
        _login(client)
        with patch('lib.ssh_client.test_connection',
                   return_value=(True, 'SSH connection successful', 'linux')) as probe:
            r = client.post('/api/v1/hosts/test_ssh', json={
                'address': '10.0.0.9',
                'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': 'pw',
                                     'ssh_port': 2222}},
            })
        body = r.get_json()
        assert r.status_code == 200 and body['ok'] is True
        assert body['os'] == 'linux'        # OS detected over the connection
        kw = probe.call_args.kwargs
        assert kw['address'] == '10.0.0.9' and kw['user'] == 'root'
        assert kw['password'] == 'pw' and kw['port'] == 2222
        assert kw['detect'] is True

    def test_probe_restores_masked_secret_from_stored_host(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/hosts', json={
            'name': 'rem', 'address': '10.0.0.9', 'kind': 'remote',
            'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': 'storedpw'}},
        }).get_json()['uid']
        # Client sends the secret masked (null) — route restores it from storage.
        with patch('lib.ssh_client.test_connection',
                   return_value=(True, 'ok', '')) as probe:
            client.post('/api/v1/hosts/test_ssh', json={
                'uid': uid, 'address': '10.0.0.9',
                'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': None}},
            })
        assert probe.call_args.kwargs['password'] == 'storedpw'

    def test_probe_requires_edit_permission(self, client, admin):
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        assert client.post('/api/v1/hosts/test_ssh',
                           json={'address': '1.2.3.4'}).status_code == 403


class TestApiMigrate:

    def test_preview_and_apply(self, client, admin):
        _login(client)
        mods = {
            'snmp': {'servers': {'r1': {'host': '10.0.0.1', 'community': 'public',
                                        'version': '2c', 'checks': {}}}},
            'ping': {'list': {'p1': {'host': '10.0.0.1'}}},
        }
        assert client.put('/api/v1/modules', json=mods).status_code == 200

        plan = client.get('/api/v1/hosts/migrate/preview').get_json()
        grp = next(c for c in plan['candidates'] if c['address'] == '10.0.0.1')
        assert grp['is_duplicate'] is True
        assert set(grp['modules']) == {'snmp', 'ping'}

        res = client.post('/api/v1/hosts/migrate/apply',
                          json={'accept': [{'id': grp['id'], 'name': 'host-a'}]})
        assert res.status_code == 200
        assert res.get_json()['created'] == 1

        host = admin._hosts_store.get_by_name('host-a')
        assert host and host['address'] == '10.0.0.1'
        # Host profiles are address-only now; SNMP settings stay on the check.
        assert 'snmp' not in (host.get('profiles') or {})

        newmods = client.get('/api/v1/modules').get_json()
        # Items are now keyed by their uid, so look them up by value.
        r1 = next(iter(newmods['snmp']['servers'].values()))
        assert r1.get('host_uid') and 'host' not in r1
        assert r1['community'] == 'public'         # per-check setting preserved
        p1 = next(iter(newmods['ping']['list'].values()))
        assert p1.get('host_uid') == r1['host_uid'] and 'host' not in p1

    def test_preview_masks_secrets(self, client):
        _login(client)
        # The SSH tunnel is host-owned; its password must be masked in the preview.
        # The candidate host is the SSH server ('jump') — datastore's DB endpoint
        # ('host') is now a per-check field, not a host profile.
        mods = {'datastore': {'list': {'d1': {
            'host': 'db.x', 'db_type': 'postgres', 'conn_type': 'ssh',
            'ssh_host': 'jump', 'ssh_user': 'j', 'ssh_password': 'topsecret'}}}}
        assert client.put('/api/v1/modules', json=mods).status_code == 200
        plan = client.get('/api/v1/hosts/migrate/preview').get_json()
        c = next(c for c in plan['candidates'] if c['address'] == 'jump')
        assert c['profiles']['ssh']['ssh_user'] == 'j'
        assert c['profiles']['ssh']['ssh_password'] is None   # secret masked

    def test_apply_requires_edit_permission(self, client, admin):
        # A viewer (no servers_edit) cannot preview/apply.
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        assert client.get('/api/v1/hosts/migrate/preview').status_code == 403
        assert client.post('/api/v1/hosts/migrate/apply', json={'accept': []}).status_code == 403


class TestHostAudits:
    """Host operations must be audited with meaningful detail (field diffs,
    names, masked secrets) — same convention as config/modules."""

    def _last(self, admin, event):
        return next(e for e in reversed(admin._audit_log) if e['event'] == event)

    def test_update_audits_field_diff_with_masked_secret(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/hosts', json=_HOST).get_json()['uid']
        upd = {'name': 'srv-1', 'address': '10.0.0.99',
               'profiles': {'ssh': {'user': 'root2', 'ssh_password': 'newpw', 'port': 22}}}
        assert client.put(f'/api/v1/hosts/{uid}', json=upd).status_code == 200
        detail = self._last(admin, 'host_updated')['detail']
        fields = {c['field'] for c in detail['changes']}
        assert 'address' in fields
        assert any(f.startswith('profiles') for f in fields)
        # The changed secret must never appear in the audit trail.
        assert 'newpw' not in str(detail)

    def test_added_ssh_profile_secret_masked_in_audit(self, client, admin):
        """Regression: adding a whole SSH profile must NOT log the password /
        key text in plaintext (only one side of the diff is a dict)."""
        _login(client)
        # Create a host with no profiles, then add the SSH profile on update.
        uid = client.post('/api/v1/hosts', json={'name': 'srv-x', 'address': '10.0.0.5'}).get_json()['uid']
        upd = {'name': 'srv-x', 'address': '10.0.0.5', 'kind': 'remote',
               'profiles': {'ssh': {'ssh_user': 'root',
                                    'ssh_password': 'topsecret',
                                    'ssh_key_string': '-----BEGIN OPENSSH PRIVATE KEY-----xyz'}}}
        assert client.put(f'/api/v1/hosts/{uid}', json=upd).status_code == 200
        detail = self._last(admin, 'host_updated')['detail']
        blob = str(detail)
        assert 'topsecret' not in blob and 'BEGIN OPENSSH' not in blob
        assert '***' in blob

    def test_create_and_delete_audit_details(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/hosts', json=_HOST).get_json()['uid']
        created = self._last(admin, 'host_created')['detail']
        assert created['address'] == '10.0.0.5' and created['profiles'] == ['ssh']
        client.delete(f'/api/v1/hosts/{uid}')
        deleted = self._last(admin, 'host_deleted')['detail']
        assert deleted['name'] == 'srv-1' and deleted['address'] == '10.0.0.5'

    def test_migrate_audits_created_hosts(self, client, admin):
        _login(client)
        mods = {'ping': {'list': {'p1': {'host': '10.9.9.1'}, 'p2': {'host': '10.9.9.1'}}}}
        assert client.put('/api/v1/modules', json=mods).status_code == 200
        plan = client.get('/api/v1/hosts/migrate/preview').get_json()
        grp = next(c for c in plan['candidates'] if c['address'] == '10.9.9.1')
        client.post('/api/v1/hosts/migrate/apply',
                    json={'accept': [{'id': grp['id'], 'name': 'mig-host'}]})
        detail = self._last(admin, 'hosts_migrated')['detail']
        assert detail['hosts'] == 1 and detail['checks'] == 2
        assert detail['created'][0]['name'] == 'mig-host'
        # Checks are identified by their uid key now; just assert count + module.
        checks = detail['created'][0]['checks']
        assert len(checks) == 2 and all(c.startswith('ping/') for c in checks)


class TestStateChangeAudits:
    """Previously-unaudited state changes must now leave an audit entry."""

    def test_history_delete_audited(self, client, admin):
        _login(client)
        if not admin._history:
            import pytest
            pytest.skip('history store unavailable')
        admin._history.record('mod_x', 'k1', True, {})
        client.delete('/api/v1/history?module=mod_x&key=k1')
        entry = next(e for e in reversed(admin._audit_log) if e['event'] == 'history_deleted')
        assert entry['detail']['module'] == 'mod_x' and entry['detail']['key'] == 'k1'

    def test_history_delete_all_audited(self, client, admin):
        _login(client)
        if not admin._history:
            import pytest
            pytest.skip('history store unavailable')
        client.delete('/api/v1/history/all')
        assert any(e['event'] == 'history_all_deleted' for e in admin._audit_log)


class TestHostStatus:
    """/api/v1/hosts/<uid>/status — latest recorded data for the modal tab."""

    def test_returns_bound_check_status(self, client, admin):
        _login(client)
        uid = client.post('/api/v1/hosts', json=_HOST).get_json()['uid']
        # Bind a ping check to this host.
        mods = admin._read_config_file(admin._MODULES_FILE) or {}
        mods.setdefault('ping', {}).setdefault('list', {})['chk1'] = {
            'host_uid': uid, 'enabled': True, 'host': '10.0.0.5',
            'label': 'My Ping', 'uid': 'u1'}
        assert admin._save_config_file(admin._MODULES_FILE, mods)
        # Daemon recorded a result for it (in the check_state DB).
        admin._check_state_store.persist_status({'ping': {'chk1': {
            'status': True, 'message': 'pong', 'other_data': {'latency_ms': 1.2}}}})

        r = client.get(f'/api/v1/hosts/{uid}/status')
        assert r.status_code == 200
        e = next(x for x in r.get_json()['results'] if x['key'] == 'chk1')
        assert e['ok'] is True and e['name'] == 'My Ping'
        assert e['message'] == 'pong' and e['data']['latency_ms'] == 1.2

    def test_matches_derived_keys(self, client, admin):
        """ram_swap derived keys (<uid>_ram) match their base bound item."""
        _login(client)
        uid = client.post('/api/v1/hosts', json=_HOST).get_json()['uid']
        mods = admin._read_config_file(admin._MODULES_FILE) or {}
        mods.setdefault('ram_swap', {}).setdefault('list', {})['base1'] = {
            'host_uid': uid, 'enabled': True, 'label': 'NS1', 'uid': 'rs1'}
        assert admin._save_config_file(admin._MODULES_FILE, mods)
        admin._check_state_store.persist_status({'ram_swap': {'base1_ram': {
            'status': True, 'other_data': {'name': 'NS1 - RAM', 'used': 42.0}}}})
        r = client.get(f'/api/v1/hosts/{uid}/status')
        e = next(x for x in r.get_json()['results'] if x['key'] == 'base1_ram')
        assert e['name'] == 'NS1 - RAM' and e['data']['used'] == 42.0


class TestCheckSecretRestore:
    """A test run after reload must use the stored secret, not the masked null."""

    def test_restores_masked_password_from_stored_item(self, admin):
        from lib.web_admin.routes.hosts import _restore_check_secrets
        mods = admin._read_config_file(admin._MODULES_FILE) or {}
        mods.setdefault('datastore', {}).setdefault('list', {})['d1'] = {
            'db_type': 'mysql', 'user': 'u', 'password': 'REALPASS', 'uid': 'u1'}
        assert admin._save_config_file(admin._MODULES_FILE, mods)
        # The modal would send the masked secret (null) on a post-reload test.
        fields = {'db_type': 'mysql', 'user': 'u', 'password': None}
        _restore_check_secrets(admin, 'datastore', 'list', 'd1', fields)
        assert fields['password'] == 'REALPASS'      # restored from storage
        assert fields['user'] == 'u'

    def test_explicit_new_password_is_kept(self, admin):
        from lib.web_admin.routes.hosts import _restore_check_secrets
        mods = admin._read_config_file(admin._MODULES_FILE) or {}
        mods.setdefault('datastore', {}).setdefault('list', {})['d1'] = {
            'password': 'OLDPASS', 'uid': 'u1'}
        assert admin._save_config_file(admin._MODULES_FILE, mods)
        fields = {'password': 'TYPED_NEW'}           # user typed a new one
        _restore_check_secrets(admin, 'datastore', 'list', 'd1', fields)
        assert fields['password'] == 'TYPED_NEW'     # the typed value wins


class TestServerTest:
    """Full/individual server test endpoints reuse each module's check() once."""

    def _mock_check(self):
        # The check path uses host_exec → ssh_client.connect_host + run_command.
        from lib import ssh_client
        return [
            patch.object(ssh_client, 'HAS_PARAMIKO', True),
            patch.object(ssh_client, 'connect_host', return_value=object()),
            patch.object(ssh_client, 'run_command', return_value=('nginx\nnginx\n', '', 0)),
        ]

    def test_test_check_individual(self, client):
        _login(client)
        ctx = self._mock_check()
        for c in ctx:
            c.start()
        try:
            r = client.post('/api/v1/hosts/test_check', json={
                '_host': {'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
                          'profiles': {'ssh': {'ssh_user': 'root'}}},
                'module': 'process', 'collection': 'list', 'key': 'web',
                'fields': {'process': 'nginx', 'min_count': 2},
            })
        finally:
            for c in ctx:
                c.stop()
        assert r.status_code == 200
        d = r.get_json()
        assert d['ok'] is True
        assert d['results'][0]['key'] == 'web'

    def test_full_test_ssh_and_checks(self, client, admin):
        from lib import ssh_client
        _login(client)
        ctx = self._mock_check() + [
            patch.object(ssh_client, 'test_connection', return_value=(True, 'ok', 'linux')),
        ]
        for c in ctx:
            c.start()
        try:
            r = client.post('/api/v1/hosts/test', json={
                '_host': {'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
                          'profiles': {'ssh': {'ssh_user': 'root'}}},
                'checks': [{'module': 'process', 'collection': 'list', 'key': 'web',
                            'fields': {'process': 'nginx', 'min_count': 1}}],
            })
        finally:
            for c in ctx:
                c.stop()
        assert r.status_code == 200
        d = r.get_json()
        assert d['ssh']['ok'] is True
        assert d['ok'] is True
        assert any(x['module'] == 'process' and x['ok'] for x in d['results'])
        # The test is audited with a per-check breakdown (not just a count).
        ev = next(e for e in reversed(admin._audit_log) if e['event'] == 'host_tested')
        det = ev['detail']
        assert det['total'] == 1 and det['passed'] == 1 and det['failed'] == 0
        assert det['results'][0]['module'] == 'process' and det['results'][0]['ok'] is True

    def test_module_test_no_ssh_skips_ssh(self, client):
        """A module-scoped test (no_ssh) runs the checks but not the SSH probe."""
        from lib import ssh_client
        _login(client)
        ctx = self._mock_check() + [
            patch.object(ssh_client, 'test_connection', return_value=(True, 'ok', 'linux')),
        ]
        for c in ctx:
            c.start()
        try:
            r = client.post('/api/v1/hosts/test', json={
                'no_ssh': True,
                '_host': {'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
                          'profiles': {'ssh': {'ssh_user': 'root'}}},
                'checks': [{'module': 'process', 'collection': 'list', 'key': 'web',
                            'fields': {'process': 'nginx', 'min_count': 1}}],
            })
        finally:
            for c in ctx:
                c.stop()
        d = r.get_json()
        assert d['ssh'] is None                       # SSH probe skipped
        assert any(x['module'] == 'process' and x['ok'] for x in d['results'])

    def test_test_requires_edit_permission(self, client, admin):
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        assert client.post('/api/v1/hosts/test', json={}).status_code == 403
        assert client.post('/api/v1/hosts/test_check', json={}).status_code == 403


class TestPerServerPermissions:
    """Per-server overrides (server.<uid>.<view|edit|delete>) gate access the
    same way per-module permissions do — without any global ``servers_*``."""

    def _make_user(self, admin, perms):
        """Assign a custom role holding *perms* to a fresh user; return its name."""
        role_uid = '11111111-1111-4111-8111-111111111111'
        admin._custom_roles[role_uid] = {
            'uid': role_uid, 'name': 'srv-role', 'enabled': True,
            'permissions': list(perms),
        }
        admin._users['srvuser'] = {
            'password_hash': admin._users['admin']['password_hash'],
            'role': role_uid, 'display_name': 'S',
        }
        return 'srvuser'

    # Hosts are created directly through the store so no admin login is needed —
    # the test then logs in *only* as the per-server user (logging in over an
    # active admin session would not switch the session).
    def test_view_scoped_to_granted_server(self, client, admin):
        uid1 = admin._hosts_store.create({**_HOST}, actor='admin')
        uid2 = admin._hosts_store.create(
            {**_HOST, 'name': 'srv-2', 'address': '10.0.0.6'}, actor='admin')
        self._make_user(admin, [f'server.{uid1}.view'])
        _login(client, 'srvuser')
        hosts = client.get('/api/v1/hosts').get_json()['hosts']
        ids = {h['uid'] for h in hosts}
        assert uid1 in ids and uid2 not in ids

    def test_no_server_perm_forbidden(self, client, admin):
        admin._hosts_store.create({**_HOST}, actor='admin')
        self._make_user(admin, [])
        _login(client, 'srvuser')
        assert client.get('/api/v1/hosts').status_code == 403

    def test_view_only_cannot_edit_or_delete(self, client, admin):
        uid = admin._hosts_store.create({**_HOST}, actor='admin')
        self._make_user(admin, [f'server.{uid}.view'])
        _login(client, 'srvuser')
        assert client.put(f'/api/v1/hosts/{uid}',
                          json={'name': 'x', 'address': '10.0.0.5'}).status_code == 403
        assert client.delete(f'/api/v1/hosts/{uid}').status_code == 403

    def test_edit_and_delete_when_granted(self, client, admin):
        uid = admin._hosts_store.create({**_HOST}, actor='admin')
        self._make_user(admin, [f'server.{uid}.view',
                                f'server.{uid}.edit', f'server.{uid}.delete'])
        _login(client, 'srvuser')
        assert client.put(f'/api/v1/hosts/{uid}',
                          json={'name': 'x', 'address': '10.0.0.5'}).status_code == 200
        assert client.delete(f'/api/v1/hosts/{uid}').status_code == 200

    # ── 'add' permission: add modules/checks to a server ─────────────────────
    def _modules_with_check(self, admin, host_uid, key='newchk', **fields):
        """Full modules.json (post-migration) plus one host-bound ping check."""
        data = copy.deepcopy(admin._read_config_file(admin._MODULES_FILE) or {})
        data.setdefault('ping', {}).setdefault('list', {})[key] = {
            'host_uid': host_uid, 'enabled': True, 'host': '10.0.0.5', **fields}
        return data

    def test_server_add_can_add_host_bound_check(self, client, admin):
        uid = admin._hosts_store.create({**_HOST}, actor='admin')
        self._make_user(admin, [f'server.{uid}.view', f'server.{uid}.add'])
        _login(client, 'srvuser')
        data = self._modules_with_check(admin, uid)
        assert client.put('/api/v1/modules', json=data).status_code == 200

    def test_server_view_only_cannot_add_check(self, client, admin):
        uid = admin._hosts_store.create({**_HOST}, actor='admin')
        self._make_user(admin, [f'server.{uid}.view'])
        _login(client, 'srvuser')
        data = self._modules_with_check(admin, uid)
        assert client.put('/api/v1/modules', json=data).status_code == 403

    def test_server_add_cannot_edit_existing_check(self, client, admin):
        uid = admin._hosts_store.create({**_HOST}, actor='admin')
        # Seed an existing host-bound check, then try to modify it with add-only.
        seed = self._modules_with_check(admin, uid, key='chk1', uid='u-chk1')
        admin._save_config_file(admin._MODULES_FILE, seed)
        self._make_user(admin, [f'server.{uid}.view', f'server.{uid}.add'])
        _login(client, 'srvuser')
        data = copy.deepcopy(admin._read_config_file(admin._MODULES_FILE) or {})
        data['ping']['list']['chk1']['enabled'] = False   # modify existing → edit
        assert client.put('/api/v1/modules', json=data).status_code == 403

    def test_server_add_host_modules_growth_allowed_not_field_edit(self, client, admin):
        uid = admin._hosts_store.create({**_HOST, 'modules': []}, actor='admin')
        self._make_user(admin, [f'server.{uid}.view', f'server.{uid}.add'])
        _login(client, 'srvuser')
        cur = admin._hosts_store.get(uid, decrypt=True)
        body = {k: cur.get(k) for k in
                ('name', 'address', 'kind', 'os', 'maintenance',
                 'tags', 'description', 'profiles')}
        body['modules'] = ['ping']                         # only grow the list
        assert client.put(f'/api/v1/hosts/{uid}', json=body).status_code == 200
        body2 = dict(body); body2['address'] = '9.9.9.9'   # edit a field → denied
        assert client.put(f'/api/v1/hosts/{uid}', json=body2).status_code == 403
