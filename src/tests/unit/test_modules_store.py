#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ModulesStore — the DB-backed module/item configuration store.

Covers the dict <-> rows mapping: round-trip fidelity, promoted columns
(device_uid/label/enabled) kept out of the JSON ``data``, device_uid omitted when
empty, ``__``-meta kept as a module field (not a collection), transactional
sync (add/remove module and item), stable module UIDs, and the version token.
"""

import copy
import json

from lib.config import ConfigControl
from lib.db import get_connector
from lib.core.modules import ModulesStore, DbBackedModules


def _store():
    db = get_connector(None, default_sqlite_path=':memory:')
    return ModulesStore(db), db


def _strip_audit(modules):
    """Drop the read-only per-item audit metadata (created_at/updated_at/
    updated_by) that ``load_all`` enriches each item with, so a saved config can
    be compared exactly against what was written."""
    for mod in (modules or {}).values():
        if not isinstance(mod, dict):
            continue
        for coll in mod.values():
            if not isinstance(coll, dict):
                continue
            for item in coll.values():
                if isinstance(item, dict):
                    for k in ('created_at', 'updated_at', 'updated_by'):
                        item.pop(k, None)
    return modules


def _sample():
    return {
        'cpu': {
            'enabled': True, 'alert': 85, 'interval': 1,
            'list': {
                'u1': {'uid': 'u1', 'label': 'PVE20', 'device_uid': 'h1',
                       'enabled': True, 'alert': 85},
                'u2': {'uid': 'u2', 'label': 'Moria', 'enabled': True, 'alert': 90},  # no device_uid
            },
        },
        'dns': {
            'enabled': False, 'interval': 5,
            'list': {
                'd1': {'uid': 'd1', 'label': 'Router', 'device_uid': 'h2',
                       'enabled': False, 'nameserver': '8.8.8.8'},
            },
        },
    }


class TestModulesStore:

    def test_is_empty(self):
        s, _ = _store()
        assert s.is_empty() is True
        s.save_all(_sample())
        assert s.is_empty() is False

    def test_roundtrip_exact(self):
        s, _ = _store()
        s.save_all(_sample())
        assert _strip_audit(s.load_all()) == _sample()

    def test_promoted_columns_not_duplicated_in_data(self):
        s, db = _store()
        s.save_all(_sample())
        device_uid, label, enabled, data = db.fetchone(
            "SELECT device_uid, label, enabled, data FROM module_config_items WHERE uid='u1'")
        assert (device_uid, label, enabled) == ('h1', 'PVE20', 1)
        d = json.loads(data)
        assert d == {'alert': 85}                       # promoted keys + uid stripped
        for k in ('uid', 'device_uid', 'label', 'enabled'):
            assert k not in d

    def test_device_uid_omitted_when_empty(self):
        s, db = _store()
        s.save_all(_sample())
        assert db.fetchone("SELECT device_uid FROM module_config_items WHERE uid='u2'")[0] == ''
        assert 'device_uid' not in s.load_all()['cpu']['list']['u2']

    def test_enabled_false_preserved(self):
        s, _ = _store()
        s.save_all(_sample())
        assert s.load_all()['dns']['list']['d1']['enabled'] is False

    def test_meta_key_is_module_field_not_collection(self):
        s, db = _store()
        s.save_all({'snmp': {'enabled': True,
                             '__device_profile__': {'foo': 'bar'},
                             'list': {'s1': {'uid': 's1', 'label': 'L', 'enabled': True}}}})
        out = s.load_all()
        assert out['snmp']['__device_profile__'] == {'foo': 'bar'}
        assert 's1' in out['snmp']['list']
        mc = json.loads(db.fetchone("SELECT data FROM module_config WHERE module='snmp'")[0])
        assert '__device_profile__' in mc and 'list' not in mc

    def test_scalar_legacy_items_preserved(self):
        # Legacy format: a collection item can be a bare scalar (name -> bool),
        # not only a dict — must round-trip without loss.
        s, _ = _store()
        data = {
            'ping': {'enabled': True, 'list': {
                'r1': {'uid': 'r1', 'label': 'Router', 'enabled': True},
                'r2': False,                       # legacy scalar item
            }},
            'web': {'enabled': True, 'list': {'www.example.com': True}},
        }
        s.save_all(data)
        assert _strip_audit(s.load_all()) == data

    def test_multiple_collection_keys(self):
        # Real data uses both 'list' and 'servers' (snmp) as collection keys.
        s, db = _store()
        data = {'snmp': {'enabled': True,
                         'servers': {'s1': {'uid': 's1', 'label': 'SW1', 'device_uid': 'h9',
                                            'enabled': True, 'oid': '1.3.6'}}}}
        s.save_all(data)
        assert _strip_audit(s.load_all()) == data
        assert db.fetchone("SELECT collection FROM module_config_items WHERE uid='s1'")[0] == 'servers'

    def test_sync_removes_item(self):
        s, db = _store()
        s.save_all(_sample())
        data = _sample()
        del data['cpu']['list']['u2']
        s.save_all(data)
        out = s.load_all()
        assert set(out['cpu']['list']) == {'u1'}
        assert db.fetchone("SELECT 1 FROM module_config_items WHERE uid='u2'") is None

    def test_sync_removes_module(self):
        s, db = _store()
        s.save_all(_sample())
        data = _sample()
        del data['dns']
        s.save_all(data)
        out = s.load_all()
        assert 'dns' not in out
        assert db.fetchone("SELECT 1 FROM module_config WHERE module='dns'") is None
        assert db.fetchone("SELECT 1 FROM module_config_items WHERE uid='d1'") is None

    def test_module_uid_stable_across_saves(self):
        s, db = _store()
        s.save_all(_sample())
        uid1 = db.fetchone("SELECT uid FROM module_config WHERE module='cpu'")[0]
        s.save_all(_sample())                               # save again
        uid2 = db.fetchone("SELECT uid FROM module_config WHERE module='cpu'")[0]
        assert uid1 == uid2
        assert db.fetchone("SELECT module_uid FROM module_config_items WHERE uid='u1'")[0] == uid1

    def test_version_increments_on_write(self):
        s, _ = _store()
        v0 = s.version()
        s.save_all(_sample())
        assert s.version() == v0 + 1
        s.save_all(_sample())
        assert s.version() == v0 + 2


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(Fernet.generate_key())


def _facade(fernet=None, secret_keys=None):
    db = get_connector(None, default_sqlite_path=':memory:')
    store = ModulesStore(db)
    return DbBackedModules(store, fernet=fernet, secret_keys=secret_keys), store, db


class TestDbBackedModules:

    def test_save_read_roundtrip(self):
        fac, store, _ = _facade()
        fac.save(_sample())
        assert _strip_audit(DbBackedModules(store).read()) == _sample()

    def test_get_conf_parity_with_configcontrol(self):
        fac, _, _ = _facade()
        fac.save(_sample())
        fac.read()
        cc = ConfigControl(None, copy.deepcopy(_sample()))
        for key in (['cpu', 'alert'], ['cpu', 'list', 'u1', 'label'],
                    ['dns', 'enabled'], ['does', 'not', 'exist']):
            assert fac.get_conf(key) == cc.get_conf(key)
        assert fac.is_exist_conf(['cpu', 'list', 'u1']) == cc.is_exist_conf(['cpu', 'list', 'u1'])
        assert fac.is_exist_conf(['cpu', 'list', 'zzz']) == cc.is_exist_conf(['cpu', 'list', 'zzz'])

    def test_set_conf_then_save_persists(self):
        fac, store, _ = _facade()
        fac.save(_sample())
        fac.read()
        fac.set_conf(['cpu', 'alert'], 99)
        fac.save()
        assert DbBackedModules(store).read()['cpu']['alert'] == 99

    def test_secrets_encrypted_at_rest_decrypted_on_read(self):
        f = _fernet()
        fac, store, db = _facade(fernet=f, secret_keys={'password'})
        data = {'web': {'enabled': True,
                        'list': {'w1': {'uid': 'w1', 'label': 'X', 'enabled': True,
                                        'password': 's3cr3t'}}}}
        fac.save(data)
        raw = db.fetchone("SELECT data FROM module_config_items WHERE uid='w1'")[0]
        assert 's3cr3t' not in raw                          # encrypted at rest
        # self.data stays plaintext after save (encrypt_sensitive returns a copy)
        assert fac.data['web']['list']['w1']['password'] == 's3cr3t'
        # a fresh facade decrypts on read
        fac2 = DbBackedModules(store, fernet=f, secret_keys={'password'})
        assert fac2.read()['web']['list']['w1']['password'] == 's3cr3t'

    def test_reload_if_changed(self):
        fac, store, _ = _facade()
        fac.save(_sample())
        fac.read()
        fac.reload_if_changed()                              # no change → stays
        assert fac.data['cpu']['alert'] == 85
        other = DbBackedModules(store)                       # external writer, same store
        changed = _sample()
        changed['cpu']['alert'] = 1
        other.save(changed)
        fac.reload_if_changed()                              # version bumped → re-reads
        assert fac.data['cpu']['alert'] == 1


class TestNoLostUpdates:
    """The configuration is replaced whole on every save, so two writers working from the
    same read must not silently undo each other, and a second process must SEE a write."""

    def test_second_store_sees_the_write_of_another(self):
        # Two ModulesStore instances over one database = two replicas. The version used to be a
        # per-instance counter, so the reader never noticed the other's write.
        db = get_connector(None, default_sqlite_path=':memory:')
        reader = DbBackedModules(ModulesStore(db))
        writer = DbBackedModules(ModulesStore(db))
        writer.save(_sample())
        reader.read()
        changed = _sample()
        changed['cpu']['alert'] = 7
        writer.save(changed)
        assert reader.reload_if_changed()['cpu']['alert'] == 7

    def test_stale_expected_version_is_refused_and_writes_nothing(self):
        import pytest
        from lib.core.modules.store import StaleModulesConfig
        s, _ = _store()
        s.save_all(_sample())
        seen = s.version()
        winner = _sample()
        winner['cpu']['alert'] = 1
        s.save_all(winner)                                   # someone else saves first
        loser = _sample()
        loser['cpu']['alert'] = 2
        with pytest.raises(StaleModulesConfig) as exc:
            s.save_all(loser, expected_version=seen)
        assert exc.value.current == s.version()
        assert s.load_all()['cpu']['alert'] == 1             # the winner's change survives

    def test_current_expected_version_saves_and_returns_the_new_one(self):
        s, _ = _store()
        s.save_all(_sample())
        v = s.version()
        assert s.save_all(_sample(), expected_version=v) == v + 1 == s.version()

    def test_mutate_modules_retries_on_a_concurrent_write(self):
        # A read-modify-write that lost the race runs again on the fresh copy instead of
        # saving its stale one over the other writer's change.
        from lib.core.modules.facade import mutate_modules
        db = get_connector(None, default_sqlite_path=':memory:')
        mine, other = DbBackedModules(ModulesStore(db)), DbBackedModules(ModulesStore(db))
        mine.save(_sample())

        class _WA:
            _modules_facade = mine

            def _load_modules(self):
                return copy.deepcopy(mine.reload_if_changed())

            def _save_modules(self, data):
                return mine.save(copy.deepcopy(data))

        calls = []

        def _edit(mods):
            calls.append(1)
            if len(calls) == 1:                              # another process writes NOW
                theirs = copy.deepcopy(mods)
                theirs['extra'] = {'enabled': True}
                other.save(theirs)
            mods['cpu']['alert'] = 3
            return True

        assert mutate_modules(_WA(), _edit) is True
        final = DbBackedModules(ModulesStore(db)).read()
        assert final['cpu']['alert'] == 3 and 'extra' in final
        assert len(calls) == 2

