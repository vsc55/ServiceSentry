#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for HostsStore — the host registry (servers + per-protocol profiles).

Covers CRUD, name uniqueness, profile preservation, and — importantly — that
secret values inside the profiles are encrypted at rest and decrypted on read.
"""


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

    def test_kind_defaults_to_none(self):
        """A device says nothing about running commands until somebody says something.

        It defaulted to `local`, which is not "nothing" — it is the panel's OWN machine. Most
        of a fleet is equipment read over SNMP (a switch, a router, a UPS, a NAS) where there
        is nothing to run a shell command on, so a check bound to a newly added switch
        measured the panel and filed the answer under the switch's name."""
        s, _ = _store()
        uid = s.create(_host('k1'))
        h = s.get(uid)
        assert h['kind'] == 'none'
        assert h['maintenance'] is False

    def test_all_three_kinds_survive_a_round_trip(self):
        s, _ = _store()
        for i, kind in enumerate(('none', 'local', 'remote')):
            uid = s.create({**_host('k1r%d' % i), 'kind': kind})
            assert s.get(uid)['kind'] == kind

    def test_an_existing_local_host_stays_local(self):
        """The default changed; nothing stored did. A machine somebody set to `local` is one
        whose checks are meant to run here, and a new default must not move it."""
        s, _ = _store()
        uid = s.create({**_host('k1keep'), 'kind': 'local'})
        s.update(uid, {'name': 'k1keep', 'kind': 'local'}, actor='t')
        assert s.get(uid)['kind'] == 'local'

    def test_create_remote_and_maintenance(self):
        s, _ = _store()
        uid = s.create({**_host('k2'), 'kind': 'remote', 'maintenance': True})
        h = s.get(uid)
        assert h['kind'] == 'remote'
        assert h['maintenance'] is True

    def test_invalid_kind_normalised_to_none(self):
        """To `none` and not to `local`: the two differ in WHERE a command runs, and reading
        "the panel's own machine" out of a value nobody wrote is how a check comes to measure
        the wrong box quietly. A record that says nothing gets nothing."""
        s, _ = _store()
        for bad in ('banana', '', None, 'LOCALHOST', 0):
            uid = s.create({**_host('k3-%s' % bad), 'kind': bad})
            assert s.get(uid)['kind'] == 'none', bad

    def test_the_kinds_are_written_down_once(self):
        """The form offers them and the runner branches on them; a fourth list somewhere is a
        fourth place for them to stop agreeing."""
        from lib.core.hosts.store import HostsStore              # noqa: PLC0415
        assert HostsStore.KINDS == ('none', 'local', 'remote')

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


class TestWhatTheDeviceIs:
    """`device_type` — a property, and deliberately not a section.

    Everything the panel does with an entry is the same whatever it is, so splitting the
    registry by type would force a decision at creation time that is often wrong (a NAS *is*
    a server; a hypervisor is both). Stored, filtered and drawn — never navigated.
    """

    def test_it_round_trips(self):
        s, _ = _store(_fernet())
        uid = s.create({**_host('nas-1'), 'device_type': 'nas'})
        assert s.get(uid)['device_type'] == 'nas'

    def test_unclassified_is_the_default_and_a_real_value(self):
        """Every device that existed before the field did has this, and so does one added in
        a hurry. Refusing to save without it would be a worse form than none."""
        s, _ = _store(_fernet())
        uid = s.create(_host('plain-1'))
        assert s.get(uid)['device_type'] == ''

    def test_an_undeclared_type_is_dropped_not_stored(self):
        """It reaches the store from a request body. Kept, it would put a word on screen
        that no lang file can translate — the picker would show a raw token and the icon
        lookup would fall through to the generic one, with nothing saying why."""
        s, _ = _store(_fernet())
        uid = s.create({**_host('odd-1'), 'device_type': 'toaster'})
        assert s.get(uid)['device_type'] == ''

    def test_it_is_case_insensitive_on_the_way_in(self):
        s, _ = _store(_fernet())
        uid = s.create({**_host('sw-1'), 'device_type': 'SWITCH'})
        assert s.get(uid)['device_type'] == 'switch'

    def test_an_update_can_set_and_clear_it(self):
        s, _ = _store(_fernet())
        uid = s.create(_host('sw-2'))
        h = s.get(uid)
        assert s.update(uid, {**h, 'device_type': 'switch'})
        assert s.get(uid)['device_type'] == 'switch'
        assert s.update(uid, {**h, 'device_type': ''})
        assert s.get(uid)['device_type'] == '', 'a reclassification cannot be undone'

    def test_every_declared_type_is_storable(self):
        """The catalogue and the validator read the same list; a type offered by the picker
        and refused by the store would be a select that silently does nothing."""
        from lib.core.hosts.manifest import host_type_ids
        s, _ = _store(_fernet())
        for i, tid in enumerate(host_type_ids()):
            uid = s.create({**_host('h-%d' % i), 'device_type': tid})
            assert s.get(uid)['device_type'] == tid, tid


class TestWhatMattersOnThisMachine:
    """A switch port that is down may be a PC switched off at seven — which is not news, and
    made a rack of half-populated switches permanently red — or it may be the link to a server,
    which is a phone call. Nothing in any MIB separates those two: what is at the other end of
    the cable is knowledge about THIS installation."""

    def test_a_machine_starts_watching_nothing(self):
        s, _db = _store()
        uid = s.create({'name': 'sw'})
        assert s.get(uid)['watch'] == []
        assert s.watch(uid) == set()

    def test_a_row_can_be_marked_and_unmarked(self):
        s, _db = _store()
        uid = s.create({'name': 'sw'})
        assert s.set_watch(uid, 'snmp', 'gi3', True)
        assert s.watch(uid) == {s.watch_key('snmp', 'gi3')}
        assert s.set_watch(uid, 'snmp', 'gi3', True), 'marking twice is not an error'
        assert len(s.get(uid)['watch']) == 1, 'and does not file it twice'
        assert s.set_watch(uid, 'snmp', 'gi3', False)
        assert s.watch(uid) == set()

    def test_two_modules_can_name_the_same_row(self):
        """`gi3` of the SNMP module and `gi3` of something else are two rows."""
        s, _db = _store()
        uid = s.create({'name': 'sw'})
        s.set_watch(uid, 'snmp', 'gi3', True)
        s.set_watch(uid, 'other', 'gi3', True)
        assert len(s.watch(uid)) == 2
        s.set_watch(uid, 'snmp', 'gi3', False)
        assert s.watch(uid) == {s.watch_key('other', 'gi3')}

    def test_editing_the_machine_does_not_forget_what_it_watches(self):
        """`update` replaces the record wholesale, and a rename must not silently stop an
        alert somebody set up."""
        s, _db = _store()
        uid = s.create({'name': 'sw'})
        s.set_watch(uid, 'snmp', 'gi3', True)
        assert s.update(uid, {'name': 'sw-core', 'address': '10.0.0.2'})
        assert s.watch(uid) == {s.watch_key('snmp', 'gi3')}

    def test_a_machine_that_is_not_there_is_not_marked(self):
        s, _db = _store()
        assert s.set_watch('nope', 'snmp', 'gi3', True) is False
        uid = s.create({'name': 'sw'})
        assert s.set_watch(uid, '', 'gi3', True) is False
        assert s.set_watch(uid, 'snmp', '  ', True) is False

    def test_rubbish_in_the_column_is_not_a_watched_row(self):
        """It is JSON in a text column: a hand-edited database must not make the sampler
        iterate over strings looking for a module name."""
        s, db = _store()
        uid = s.create({'name': 'sw'})
        db.execute("UPDATE hosts SET watch = ? WHERE uid = ?",
                   ('["gi3", {"module": "snmp"}, {"module": "snmp", "row": "gi4"}]', uid))
        assert s.get(uid)['watch'] == [{'module': 'snmp', 'row': 'gi4'}]
