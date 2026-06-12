#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host registry API — /api/v1/hosts (GET/POST/PUT/DELETE)."""

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
        assert host['profiles']['snmp']['community'] == 'public'

        newmods = client.get('/api/v1/modules').get_json()
        r1 = newmods['snmp']['servers']['r1']
        assert r1.get('host_uid') and 'host' not in r1 and 'community' not in r1
        p1 = newmods['ping']['list']['p1']
        assert p1.get('host_uid') == r1['host_uid'] and 'host' not in p1

    def test_preview_masks_secrets(self, client):
        _login(client)
        # The SSH tunnel is host-owned; its password must be masked in the preview.
        mods = {'datastore': {'list': {'d1': {
            'host': 'db.x', 'db_type': 'postgres', 'conn_type': 'ssh',
            'ssh_host': 'jump', 'ssh_user': 'j', 'ssh_password': 'topsecret'}}}}
        assert client.put('/api/v1/modules', json=mods).status_code == 200
        plan = client.get('/api/v1/hosts/migrate/preview').get_json()
        c = next(c for c in plan['candidates'] if c['address'] == 'db.x')
        assert c['profiles']['ssh']['ssh_user'] == 'j'
        assert c['profiles']['ssh']['ssh_password'] is None   # secret masked

    def test_apply_requires_edit_permission(self, client, admin):
        # A viewer (no modules_edit) cannot preview/apply.
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        assert client.get('/api/v1/hosts/migrate/preview').status_code == 403
        assert client.post('/api/v1/hosts/migrate/apply', json={'accept': []}).status_code == 403
