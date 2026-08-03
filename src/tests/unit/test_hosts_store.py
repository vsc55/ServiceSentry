#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for HostsStore — the host registry (servers + per-protocol profiles).

Covers CRUD, name uniqueness, profile preservation, and — importantly — that
secret values inside the profiles are encrypted at rest and decrypted on read.
"""

import pytest

from lib.db import get_connector
from lib.core.hosts.store import HostsStore

_SECRET_KEYS = frozenset({'ssh_password', 'password', 'token', 'snmpv3_auth_key'})


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(Fernet.generate_key())


def _store(fernet=None):
    db = get_connector(None, default_sqlite_path=':memory:')
    return HostsStore(db, fernet=fernet, secret_keys=_SECRET_KEYS), db


def _host(name='srv-x'):
    return {
        'name': name, 'address': '10.0.0.1', 'tags': ['prod', 'db'],
        'description': 'primary',
        'profiles': {
            'ssh':  {'user': 'root', 'ssh_password': 's3cr3t', 'port': 22},
            'snmp': {'community': 'public', 'snmpv3_auth_key': 'authk', 'version': '3'},
        },
    }


class TestCrud:

    def test_create_and_get_roundtrip(self):
        s, _ = _store(_fernet())
        uid = s.create(_host(), actor='admin')
        assert uid
        h = s.get(uid)
        assert h['name'] == 'srv-x'
        assert h['address'] == '10.0.0.1'
        assert h['tags'] == ['prod', 'db']
        assert h['profiles']['ssh']['ssh_password'] == 's3cr3t'
        assert h['profiles']['snmp']['snmpv3_auth_key'] == 'authk'
        assert h['updated_by'] == 'admin'
        assert h['created_at'] and h['updated_at']

    def test_create_requires_name(self):
        s, _ = _store()
        assert s.create({'address': '1.2.3.4'}) is None

    def test_duplicate_name_rejected(self):
        s, _ = _store()
        assert s.create(_host('dup'))
        assert s.create(_host('dup')) is None

    def test_list_ordered_by_name(self):
        s, _ = _store()
        s.create(_host('bravo'))
        s.create(_host('alpha'))
        assert [h['name'] for h in s.list()] == ['alpha', 'bravo']

    def test_get_by_name(self):
        s, _ = _store()
        uid = s.create(_host('byname'))
        assert s.get_by_name('byname')['uid'] == uid
        assert s.get_by_name('nope') is None

    def test_count(self):
        s, _ = _store()
        assert s.count() == 0
        s.create(_host('a'))
        s.create(_host('b'))
        assert s.count() == 2

    def test_update_replaces_fields(self):
        s, _ = _store(_fernet())
        uid = s.create(_host('u1'))
        h = s.get(uid)
        h['name'] = 'u1-renamed'
        h['address'] = '10.9.9.9'
        ok = s.update(uid, h, actor='editor')
        assert ok
        out = s.get(uid)
        assert out['name'] == 'u1-renamed'
        assert out['address'] == '10.9.9.9'
        assert out['updated_by'] == 'editor'
        assert out['profiles']['ssh']['ssh_password'] == 's3cr3t'

    def test_update_rejects_name_clash(self):
        s, _ = _store()
        s.create(_host('taken'))
        uid = s.create(_host('mine'))
        h = s.get(uid)
        h['name'] = 'taken'
        assert s.update(uid, h) is False

    def test_update_unknown_uid(self):
        s, _ = _store()
        assert s.update('nope', _host()) is False

    def test_delete(self):
        s, _ = _store()
        uid = s.create(_host('del'))
        assert s.delete(uid) is True
        assert s.get(uid) is None
        assert s.delete(uid) is False


class TestKindAndMaintenance:
    """Local/remote kind and maintenance flag are first-class host columns."""

    def test_kind_defaults_to_local(self):
        s, _ = _store()
        uid = s.create(_host('k1'))
        h = s.get(uid)
        assert h['kind'] == 'local'
        assert h['maintenance'] is False

    def test_create_remote_and_maintenance(self):
        s, _ = _store()
        uid = s.create({**_host('k2'), 'kind': 'remote', 'maintenance': True})
        h = s.get(uid)
        assert h['kind'] == 'remote'
        assert h['maintenance'] is True

    def test_invalid_kind_normalised_to_local(self):
        s, _ = _store()
        uid = s.create({**_host('k3'), 'kind': 'banana'})
        assert s.get(uid)['kind'] == 'local'

    def test_os_defaults_to_auto_and_persists(self):
        s, _ = _store()
        uid = s.create(_host('k3a'))
        assert s.get(uid)['os'] == 'auto'
        uid2 = s.create({**_host('k3b'), 'os': 'linux'})
        assert s.get(uid2)['os'] == 'linux'

    def test_invalid_os_normalised_to_auto(self):
        s, _ = _store()
        uid = s.create({**_host('k3c'), 'os': 'plan9'})
        assert s.get(uid)['os'] == 'auto'

    def test_modules_list_persists(self):
        s, _ = _store()
        uid = s.create({**_host('m1'), 'modules': ['web', 'ping']})
        assert s.get(uid)['modules'] == ['web', 'ping']
        # Defaults to empty when not provided.
        uid2 = s.create(_host('m2'))
        assert s.get(uid2)['modules'] == []
        # Updatable.
        h = s.get(uid)
        h['modules'] = ['cpu']
        assert s.update(uid, h)
        assert s.get(uid)['modules'] == ['cpu']

    def test_update_toggles_kind_and_maintenance(self):
        s, _ = _store()
        uid = s.create(_host('k4'))
        h = s.get(uid)
        h['kind'] = 'remote'
        h['maintenance'] = True
        assert s.update(uid, h)
        out = s.get(uid)
        assert out['kind'] == 'remote' and out['maintenance'] is True


class TestSecretEncryption:

    def test_secrets_encrypted_at_rest(self):
        s, db = _store(_fernet())
        uid = s.create(_host('enc'))
        raw = db.fetchone('SELECT profiles FROM hosts WHERE uid = ?', (uid,))[0]
        # The ciphertext column must not contain the plaintext secrets…
        assert 's3cr3t' not in raw
        assert 'authk' not in raw
        assert 'enc:' in raw
        # …while non-secret fields stay readable.
        assert 'public' in raw and 'root' in raw

    def test_no_fernet_stores_plaintext(self):
        # Without a Fernet the store degrades gracefully (no crypto available).
        s, db = _store(fernet=None)
        uid = s.create(_host('plain'))
        assert s.get(uid)['profiles']['ssh']['ssh_password'] == 's3cr3t'

    def test_persists_across_store_instances(self):
        f = _fernet()
        db = get_connector(None, default_sqlite_path=':memory:')
        s1 = HostsStore(db, fernet=f, secret_keys=_SECRET_KEYS)
        uid = s1.create(_host('persist'))
        # A second store on the SAME connector reads + decrypts what s1 wrote.
        s2 = HostsStore(db, fernet=f, secret_keys=_SECRET_KEYS)
        assert s2.get(uid)['profiles']['ssh']['ssh_password'] == 's3cr3t'
