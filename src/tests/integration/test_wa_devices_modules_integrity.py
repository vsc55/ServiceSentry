#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The device registry and the module configuration keep each other whole.

What the audit found and this file keeps closed:

* a scoped user saved back the SUBSET of modules they were served, and every module they
  could not see counted as deleted — so every save was refused;
* an 'add'-only user could re-class a device or tie it to / cut it from an importer;
* a clone carried the source's importer identity (``source``/``external_id``) and its watched
  rows;
* the module save replaced the whole configuration with no version check, and server-side
  load→modify→save cycles saved stale copies over concurrent writes;
* deleting a device left its company ownership and its DCIM references dangling.

Every test drives the real routes through the test client.
"""

import os

import pytest

from tests.conftest import _login, _login_as

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


@pytest.fixture()
def env(admin):
    """Two devices and a module configuration with a device-bound ping check, keepalived
    (empty) and cpu."""
    admin._modules_dir = os.path.join(_SRC, 'watchfuls')
    ds = admin._devices_store
    a = ds.create({'name': 'A', 'address': '10.0.0.1', 'kind': 'remote', 'profiles': {}})
    b = ds.create({'name': 'B', 'address': '10.0.0.2', 'kind': 'remote', 'profiles': {}})
    mods = {
        'keepalived': {'enabled': True, 'list': {}},
        'ping': {'enabled': True, 'list': {'P1': {'uid': 'P1', 'enabled': True,
                                                  'host': '1.1.1.1', 'label': 'p1'}}},
        'cpu': {'enabled': True, 'alert': 80, 'list': {}},
    }
    admin._save_modules(mods)
    return {'wa': admin, 'A': a, 'B': b}


def _admin_client(wa):
    c = wa.app.test_client()
    _login(c)
    return c


# ── D5: a scoped user saves what they were served ──────────────────────────────────────
class TestScopedSaveKeepsUnseenModules:

    def test_module_scoped_user_can_save_their_module(self, env):
        wa = env['wa']
        k = _login_as(wa, 'ka', perms=['module.keepalived.view', 'module.keepalived.edit'])
        cur = k.get('/api/v1/modules').get_json()
        assert list(cur) == ['keepalived']                   # served the subset only
        cur['keepalived']['list']['new1'] = {'enabled': True, 'label': 'x', 'vip': '10.1.1.1',
                                            'device_uids': []}
        r = k.put('/api/v1/modules', json=cur)
        assert r.status_code == 200, r.get_json()
        saved = wa._load_modules()
        assert [i['vip'] for i in saved['keepalived']['list'].values()] == ['10.1.1.1']
        # the modules they never saw are untouched
        assert saved['ping']['list']['P1']['host'] == '1.1.1.1'
        assert saved['cpu']['alert'] == 80

    def test_server_scoped_user_can_add_a_check_to_their_device(self, env):
        wa, a = env['wa'], env['A']
        e = _login_as(wa, 'se', perms=[f'server.{a}.add', f'server.{a}.view',
                                       'module.ping.view'])
        cur = e.get('/api/v1/modules').get_json()
        cur['ping']['list']['N2'] = {'enabled': True, 'host': '', 'device_uid': a}
        r = e.put('/api/v1/modules', json=cur)
        assert r.status_code == 200, r.get_json()
        saved = wa._load_modules()
        assert [i.get('device_uid') for i in saved['ping']['list'].values()].count(a) == 1
        assert set(saved) >= {'keepalived', 'ping', 'cpu'}

    def test_an_unseen_module_named_in_the_body_is_still_authorised(self, env):
        # Absent means untouched; PRESENT is a change like any other and needs its permission.
        wa = env['wa']
        k = _login_as(wa, 'ka2', perms=['module.keepalived.view', 'module.keepalived.edit'])
        cur = k.get('/api/v1/modules').get_json()
        cur['cpu'] = {'enabled': False, 'alert': 1, 'list': {}}
        r = k.put('/api/v1/modules', json=cur)
        assert r.status_code == 403
        assert wa._load_modules()['cpu']['alert'] == 80


# ── D7: an 'add'-only user may only grow the modules list ──────────────────────────────
class TestAddOnlyDeviceEdit:

    def _put(self, env, **change):
        wa, a = env['wa'], env['A']
        c = _login_as(wa, 'ad', perms=[f'server.{a}.add', f'server.{a}.view'])
        body = dict(wa._devices_store.get(a, decrypt=False))
        body['modules'] = list(body.get('modules') or []) + ['ping']
        body.update(change)
        return c.put(f'/api/v1/devices/{a}', json=body)

    def test_device_type_change_is_refused(self, env):
        assert self._put(env, device_type='switch').status_code == 403

    def test_source_change_is_refused(self, env):
        assert self._put(env, source='freshservice').status_code == 403

    def test_external_id_change_is_refused(self, env):
        assert self._put(env, external_id='999').status_code == 403

    def test_modules_growth_with_the_ui_body_still_passes(self, env):
        # The device form sends neither `source` nor `external_id` (the store keeps them), and
        # the device it edits may come from an importer: absence is not a change.
        wa, a = env['wa'], env['A']
        ds = wa._devices_store
        ds.update(a, dict(ds.get(a), source='freshservice', external_id='42'))
        body = dict(ds.get(a, decrypt=False))
        for k in ('source', 'external_id', 'watch', 'created_at', 'updated_at', 'updated_by'):
            body.pop(k, None)
        body['modules'] = ['ping']
        c = _login_as(wa, 'ad2', perms=[f'server.{a}.add', f'server.{a}.view'])
        r = c.put(f'/api/v1/devices/{a}', json=body)
        assert r.status_code == 200, r.get_json()
        assert ds.get(a)['source'] == 'freshservice'


# ── D8: a clone is a different machine ──────────────────────────────────────────────────
class TestCloneDropsIdentity:

    def test_clone_is_not_maintained_by_the_source_importer(self, env):
        wa, a = env['wa'], env['A']
        ds = wa._devices_store
        ds.update(a, dict(ds.get(a), source='freshservice', external_id='42'))
        ds.set_watch(a, 'snmp', 'if.3', True)
        assert ds.get(a)['watch']
        adm = _admin_client(wa)
        r = adm.post(f'/api/v1/devices/{a}/clone', json={'name': 'A-clone',
                                                         'address': '10.9.9.9'})
        assert r.status_code == 200, r.get_json()
        clone = ds.get(r.get_json()['uid'], decrypt=False)
        assert clone['source'] == '' and clone['external_id'] == ''
        assert clone['watch'] == []
        # …so it can be renamed (a device "maintained by" an importer answers 409)
        r = adm.put(f"/api/v1/devices/{clone['uid']}", json=dict(clone, name='A-clone2'))
        assert r.status_code == 200, r.get_json()
        # and the source keeps its identity
        assert ds.get(a)['external_id'] == '42'


# ── D9: no lost updates on the module configuration ────────────────────────────────────
class TestModulesConfigVersion:

    def test_get_carries_the_version(self, env):
        r = _admin_client(env['wa']).get('/api/v1/modules')
        assert r.status_code == 200
        assert r.headers.get('X-Modules-Version', '').isdigit()

    def test_stale_put_is_refused_with_409(self, env):
        wa = env['wa']
        adm = _admin_client(wa)
        r = adm.get('/api/v1/modules')
        version, mine = r.headers['X-Modules-Version'], r.get_json()
        # somebody else saves in between
        other = wa._load_modules()
        other['cpu']['alert'] = 55
        wa._save_modules(other)
        mine['keepalived']['enabled'] = False
        r = adm.put('/api/v1/modules', json=mine, headers={'If-Match': version})
        assert r.status_code == 409
        body = r.get_json()
        assert body['stale'] is True and body['error']
        saved = wa._load_modules()
        assert saved['cpu']['alert'] == 55                  # their change survives
        assert saved['keepalived']['enabled'] is True       # mine was not written

    def test_current_put_saves_and_returns_the_next_version(self, env):
        adm = _admin_client(env['wa'])
        r = adm.get('/api/v1/modules')
        version, mine = r.headers['X-Modules-Version'], r.get_json()
        mine['cpu']['alert'] = 90
        r = adm.put('/api/v1/modules', json=mine, headers={'If-Match': version})
        assert r.status_code == 200, r.get_json()
        assert int(r.get_json()['version']) > int(version)
        assert r.headers['X-Modules-Version'] == str(r.get_json()['version'])
        # the version the save returned is the one the next save names
        mine['cpu']['alert'] = 91
        r = adm.put('/api/v1/modules', json=mine,
                    headers={'If-Match': r.headers['X-Modules-Version']})
        assert r.status_code == 200, r.get_json()

    def test_put_without_if_match_still_works(self, env):
        adm = _admin_client(env['wa'])
        mine = adm.get('/api/v1/modules').get_json()
        mine['cpu']['alert'] = 70
        assert adm.put('/api/v1/modules', json=mine).status_code == 200

    def test_another_replica_write_is_seen(self, env):
        # A second web replica = another ModulesStore over the same database. Its write moved
        # only ITS per-process counter, so this process kept serving the old configuration.
        from lib.core.modules import DbBackedModules, ModulesStore
        wa = env['wa']
        replica = DbBackedModules(ModulesStore(wa._db_connector), fernet=wa._get_fernet())
        theirs = replica.read()
        theirs['cpu']['alert'] = 33
        replica.save(theirs)
        assert wa._load_modules()['cpu']['alert'] == 33

    def test_device_delete_does_not_overwrite_a_concurrent_module_save(self, env, monkeypatch):
        # Server-side load → modify → save (delete a device with its checks). Another process
        # saves between the load and the save; the stale copy used to be written over it.
        from lib.core.modules import DbBackedModules, ModulesStore
        wa, a = env['wa'], env['A']
        mods = wa._load_modules()
        mods['ping']['list']['PA'] = {'enabled': True, 'host': '', 'device_uid': a}
        wa._save_modules(mods)
        replica = DbBackedModules(ModulesStore(wa._db_connector), fernet=wa._get_fernet())
        real_load = wa._load_modules
        fired = []

        def _load_then_race():
            data = real_load()
            if not fired:
                fired.append(1)
                theirs = replica.read()
                theirs['cpu']['alert'] = 12
                replica.save(theirs)
            return data

        monkeypatch.setattr(wa, '_load_modules', _load_then_race)
        r = _admin_client(wa).delete(f'/api/v1/devices/{a}?with_checks=1')
        assert r.status_code == 200 and r.get_json()['checks_deleted'] == 1
        monkeypatch.setattr(wa, '_load_modules', real_load)
        saved = wa._load_modules()
        assert 'PA' not in saved['ping']['list']             # the delete happened
        assert saved['cpu']['alert'] == 12                   # and the other save survived


# ── D10: a deleted device leaves no dangling references ────────────────────────────────
class TestDeleteForgetsReferences:

    def test_org_owner_and_dcim_device_links_are_cleared(self, env):
        wa, a, b = env['wa'], env['A'], env['B']
        orgs, dcim = wa._orgs_store, wa._dcim_store
        org = orgs.orgs.create({'name': 'Org1', 'short': 'O1'}, actor='t')
        assert orgs.set_owner('device', a, org)
        assert orgs.set_owner('device', b, org)
        item = dcim.items.create({'rack_uid': 'r1', 'name': 'srv', 'device_uid': a})
        pdu = dcim.pdus.create({'rack_uid': 'r1', 'name': 'pdu', 'device_uid': a})
        ups = dcim.sources.create({'name': 'ups', 'device_uid': a})
        other = dcim.items.create({'rack_uid': 'r1', 'name': 'srv-b', 'device_uid': b})

        r = _admin_client(wa).delete(f'/api/v1/devices/{a}')
        assert r.status_code == 200

        assert orgs.said_of('device', a) == ''
        assert orgs.said_of('device', b) == org              # other devices untouched
        assert dcim.items.get(item)['device_uid'] == ''      # the box stays in the rack…
        assert dcim.pdus.get(pdu)['device_uid'] == ''
        assert dcim.sources.get(ups)['device_uid'] == ''
        assert dcim.items.get(other)['device_uid'] == b

