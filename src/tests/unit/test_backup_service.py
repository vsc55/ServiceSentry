#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A copy of this installation, and putting it back.

The archive is a zip of JSON and not a dump of the database file, because the panel runs on
four engines and the copy has to survive the move: an install that grew on SQLite and is being
lifted onto MySQL is exactly when a backup is asked for, and a `.db` file answers that with
nothing.

These drive a real SQLite connector rather than a fake one. The whole feature is "rows out
through the connector, rows back in through the connector", so a fake would be testing the
fake — and the two bugs that matter (a column the live schema no longer has, a row that never
came back) only exist against something that really stores.

Flask-free: the service takes a connector and paths and answers with data.
"""

import json
import os
import zipfile

import pytest

from lib.core.backup import service as svc
from lib.db.sqlite import SQLiteConnector
from lib.db.schema import Column, TableSpec


def _spec(name, cols):
    return TableSpec(name=name, columns=[Column(c, 'TEXT', nullable=True) for c in cols])


@pytest.fixture
def db(tmp_path):
    con = SQLiteConnector(str(tmp_path / 'data.db'))
    con.reconcile_table(_spec('hosts', ['uid', 'name', 'address']))
    con.reconcile_table(_spec('credentials', ['uid', 'name', 'data']))
    con.reconcile_table(_spec('syslog', ['uid', 'msg']))
    con.reconcile_table(_spec('audit', ['uid', 'event']))
    con.execute("INSERT INTO hosts (uid, name, address) VALUES ('h1','PVE01','10.0.0.1')")
    con.execute("INSERT INTO credentials (uid, name, data) VALUES ('c1','SNMP',?)",
                (json.dumps({'version': '2c', 'community': 'enc:gAAAAAsecret'}),))
    con.execute("INSERT INTO syslog (uid, msg) VALUES ('s1','noisy')")
    con.execute("INSERT INTO audit (uid, event) VALUES ('a1','login_ok')")
    con.commit()
    yield con
    con.close()


def _make(db, tmp_path, **kw):
    kw.setdefault('parts', ['core'])
    kw.setdefault('include_secrets', True)
    return svc.create_backup(db, kw.pop('name', 'copia'), var_dir=str(tmp_path),
                             config_dir=str(tmp_path), **kw)


class TestWhatGoesIn:

    def test_core_is_everything_nobody_else_claimed(self, db, tmp_path):
        """Inverted on purpose: a table added tomorrow — including the ones modules create at
        runtime — is in the backup by default instead of being silently missed. A backup that
        quietly skips what it did not recognise is the failure you find out about once."""
        res = _make(db, tmp_path)
        assert res['ok'], res.get('message')
        tables = set(res['manifest']['tables'])
        assert {'hosts', 'credentials'} <= tables
        assert 'syslog' not in tables and 'audit' not in tables

    def test_the_bulky_parts_are_opt_in(self, db, tmp_path):
        res = _make(db, tmp_path, parts=['core', 'syslog', 'audit'])
        assert {'syslog', 'audit'} <= set(res['manifest']['tables'])

    def test_a_required_part_goes_in_whether_asked_for_or_not(self, db, tmp_path):
        """A copy without `core` restores nothing, and the caller finds that out later."""
        res = _make(db, tmp_path, parts=['syslog'])
        assert 'core' in res['manifest']['parts']
        assert 'hosts' in res['manifest']['tables']

    def test_engine_bookkeeping_is_never_dumped(self):
        """`sqlite_sequence` and friends describe the storage, not the install, and writing
        SQLite's own statistics into a MySQL restore is at best noise.

        Driven through a stub because SQLite refuses to let anyone CREATE one of these: the
        rule under test is which names the selection drops, and the engine will not let the
        fixture set the situation up."""
        class _Stub:
            @staticmethod
            def list_tables():
                return ['hosts', 'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4']

        assert svc._tables_for(_Stub(), {'core'}) == ['hosts']

    def test_the_manifest_is_written_last(self, db, tmp_path):
        """An archive interrupted half way has no manifest at all, so `read_manifest` refuses
        it instead of reporting a copy that holds less than it claims."""
        _make(db, tmp_path)
        with zipfile.ZipFile(os.path.join(str(tmp_path), 'backups', 'copia.zip')) as zf:
            assert zf.namelist()[-1] == svc.MANIFEST_NAME


class TestSecrets:

    def _cred(self, db):
        return json.loads(db.fetchone('SELECT data FROM credentials')[0])

    def test_included_they_travel_as_stored(self, db, tmp_path):
        """Still ciphertext: only the same SS_SECRET_KEY reads it back."""
        _make(db, tmp_path, include_secrets=True)
        with zipfile.ZipFile(os.path.join(str(tmp_path), 'backups', 'copia.zip')) as zf:
            payload = json.loads(zf.read('db/credentials.json'))
        data = json.loads(payload['rows'][0][2])
        assert data['community'].startswith('enc:')

    def test_excluded_nothing_encrypted_survives_at_any_depth(self, db, tmp_path):
        """The secret is a value INSIDE a JSON column, not the column itself: the credential
        store keeps its fields in a `data` blob. A pass that only looked at column values
        would ship the secret while reporting a copy that holds none."""
        _make(db, tmp_path, include_secrets=False)
        with zipfile.ZipFile(os.path.join(str(tmp_path), 'backups', 'copia.zip')) as zf:
            raw = zf.read('db/credentials.json').decode()
        assert 'enc:' not in raw, 'an encrypted value survived a secret-free backup'
        assert 'gAAAAAsecret' not in raw
        payload = json.loads(raw)
        assert json.loads(payload['rows'][0][2])['version'] == '2c', 'the rest went too'

    def test_the_manifest_says_which_it_was(self, db, tmp_path):
        """A copy without secrets that looks complete is the trap this flag exists to avoid."""
        assert _make(db, tmp_path, include_secrets=False)['manifest']['secrets'] is False
        assert _make(db, tmp_path, name='dos',
                     include_secrets=True)['manifest']['secrets'] is True


class TestPuttingItBack:

    def test_a_round_trip_restores_the_rows(self, db, tmp_path):
        _make(db, tmp_path)
        db.execute("DELETE FROM hosts")
        db.commit()
        out = svc.restore_backup(db, str(tmp_path), 'copia')
        assert out['ok'], out.get('message')
        assert db.fetchone('SELECT name FROM hosts')[0] == 'PVE01'

    def test_a_table_is_replaced_not_merged(self, db, tmp_path):
        """A backup is a statement about what the install looked like. Merging would produce a
        third state that never existed anywhere."""
        _make(db, tmp_path)
        db.execute("INSERT INTO hosts (uid, name, address) VALUES ('h2','LATER','10.0.0.2')")
        db.commit()
        svc.restore_backup(db, str(tmp_path), 'copia')
        assert [r[0] for r in db.fetchall('SELECT uid FROM hosts')] == ['h1']

    def test_restoring_one_part_leaves_the_others_alone(self, db, tmp_path):
        _make(db, tmp_path, parts=['core', 'syslog'])
        db.execute("DELETE FROM hosts")
        db.execute("DELETE FROM syslog")
        db.commit()
        svc.restore_backup(db, str(tmp_path), 'copia', parts=['syslog'])
        assert db.fetchone('SELECT COUNT(*) FROM syslog')[0] == 1
        assert db.fetchone('SELECT COUNT(*) FROM hosts')[0] == 0

    def test_a_column_the_schema_dropped_does_not_sink_the_restore(self, db, tmp_path):
        """The backup somebody reaches for is an old one, and refusing it over a schema that
        moved on would make the feature useless at the one moment it matters."""
        _make(db, tmp_path)
        db.execute('DROP TABLE hosts')
        db.reconcile_table(_spec('hosts', ['uid', 'name']))     # `address` is gone
        db.commit()
        out = svc.restore_backup(db, str(tmp_path), 'copia')
        assert out['ok'], out.get('message')
        assert db.fetchone('SELECT name FROM hosts')[0] == 'PVE01'

    def test_a_newer_format_is_refused_not_half_applied(self, db, tmp_path):
        _make(db, tmp_path)
        path = os.path.join(str(tmp_path), 'backups', 'copia.zip')
        with zipfile.ZipFile(path) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        man = json.loads(members[svc.MANIFEST_NAME])
        man['format'] = svc.FORMAT + 1
        members[svc.MANIFEST_NAME] = json.dumps(man).encode()
        with zipfile.ZipFile(path, 'w') as zf:
            for n, b in members.items():
                zf.writestr(n, b)
        out = svc.restore_backup(db, str(tmp_path), 'copia')
        assert out['ok'] is False and 'newer' in out['message']

    def test_an_unknown_name_is_an_answer_not_a_crash(self, db, tmp_path):
        assert svc.restore_backup(db, str(tmp_path), 'nope')['ok'] is False


class TestTheNameIsAFilename:
    """It is used as one and echoed back in URLs, so anything outside the pattern cannot be a
    name — which is what keeps `..` and separators out of every path built from it."""

    @pytest.mark.parametrize('bad', ['../etc/passwd', 'a/b', 'a\\b', '', '.hidden', 'x' * 65])
    def test_a_name_that_could_escape_is_refused(self, bad):
        assert svc.valid_name(bad) is False

    def test_creating_under_a_bad_name_writes_nothing(self, db, tmp_path):
        out = _make(db, tmp_path, name='../escapado')
        assert out['ok'] is False
        assert not os.path.isdir(os.path.join(str(tmp_path), 'backups'))

    def test_a_second_copy_never_overwrites_the_first(self, db, tmp_path):
        assert _make(db, tmp_path)['ok'] is True
        assert _make(db, tmp_path)['ok'] is False


class TestTheList:

    def test_it_reads_the_directory_not_a_table(self, db, tmp_path):
        """A catalogue in the database would be a second source of truth about files somebody
        can copy in or delete with the panel stopped, and the day the two disagreed the one
        that lies is the one that says a backup exists."""
        _make(db, tmp_path, name='uno')
        _make(db, tmp_path, name='dos')
        assert {b['name'] for b in svc.list_backups(str(tmp_path))} == {'uno', 'dos'}

    def test_a_stranger_zip_is_not_listed(self, db, tmp_path):
        _make(db, tmp_path)
        root = os.path.join(str(tmp_path), 'backups')
        with zipfile.ZipFile(os.path.join(root, 'ajeno.zip'), 'w') as zf:
            zf.writestr('hola.txt', 'no soy una copia')
        assert [b['name'] for b in svc.list_backups(str(tmp_path))] == ['copia']

    def test_deleting_one_needs_a_real_name(self, db, tmp_path):
        _make(db, tmp_path)
        assert svc.delete_backup(str(tmp_path), '../copia') is False
        assert svc.delete_backup(str(tmp_path), 'copia') is True
        assert svc.list_backups(str(tmp_path)) == []


class TestTheDriveListIsNotProbed:
    """Measured on a box with two network mappings: probing A–Z with `os.path.exists` took
    **6.6 seconds** the first time, because a disconnected mapping blocks until it gives up.
    The roots are rebuilt for every listing, so every step through the folder tree paid it
    again — which is what "why does the picker take so long" turned out to be. Listing the
    folders themselves is 1–13 ms.
    """

    @staticmethod
    def _roots_src() -> str:
        import io as _io
        import os as _os
        src = _io.open(_os.path.join(_os.path.dirname(_os.path.abspath(svc.__file__)),
                                     'service.py'), encoding='utf-8').read()
        return src[src.index('def _roots()'):]

    def test_it_asks_the_kernel_on_windows(self):
        body = self._roots_src()
        assert 'GetLogicalDrives' in body, 'back to probing every drive letter'
        # Checked against `ascii_uppercase`, which appears ONLY in the slow fallback. The
        # obvious signal — `os.path.exists` — also appears in the docstring that explains why
        # the fallback is slow, and a guard that trips over the prose explaining the rule it
        # is checking is a guard that fails for being right.
        i_slow = body.find('ascii_uppercase')
        assert i_slow == -1 or i_slow > body.index('GetLogicalDrives'), \
            'the slow probe runs before the kernel call'

    def test_unix_offers_more_than_the_root(self):
        """One button reading "/" is correct and useless at the same time: it starts every
        operator at the top to walk down to /mnt/nas/backups. The extras are the places a
        backup actually goes, and only when they exist."""
        body = self._roots_src()
        for place in ("'/mnt'", "'/media'", "expanduser('~')"):
            assert place in body, f'{place} is not offered'
        assert 'os.path.isdir(d)' in body, 'it offers folders that may not exist'

    def test_it_is_cached(self):
        """A drive appearing is not something to rescan for on every click, and the picker
        takes a typed path regardless."""
        svc._ROOTS_CACHE = []
        first = svc._roots()
        svc._ROOTS_CACHE = ['SENTINEL']
        assert svc._roots() == ['SENTINEL'], 'the cache is not consulted'
        svc._ROOTS_CACHE = list(first)

    def test_the_caller_cannot_corrupt_the_cache(self):
        """It hands back a copy: a caller that appended to the returned list would grow the
        cached roots on every request."""
        svc._ROOTS_CACHE = ['SENTINEL']
        svc._roots().append('OTRA')
        assert svc._roots() == ['SENTINEL']
        svc._ROOTS_CACHE = []
