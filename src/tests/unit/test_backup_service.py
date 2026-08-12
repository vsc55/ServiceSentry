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


class TestACopyThatStays:
    """Retention answers "how much history"; its floors answer "never leave the task with
    nothing". Neither can say *this particular archive* — the one taken before a migration."""

    def _root(self, tmp_path):
        return os.path.join(str(tmp_path), 'backups')

    def test_the_flag_is_a_file_beside_the_archive(self, db, tmp_path):
        """Beside it, so it survives the panel being stopped, the folder being moved and the
        copy being carried to another machine — and so nothing can claim a copy is protected
        after somebody deleted the file."""
        _make(db, tmp_path)
        assert svc.set_lock(str(tmp_path), 'copia', True, actor='ana')['ok'] is True
        assert os.path.isfile(os.path.join(self._root(tmp_path), 'copia.zip.lock'))
        b = svc.list_backups(str(tmp_path))[0]
        assert b['locked'] is True and b['lock_by'] == 'ana' and b['lock_at']

    def test_locking_something_that_is_not_there_is_an_answer(self, tmp_path):
        assert svc.set_lock(str(tmp_path), 'fantasma', True)['ok'] is False

    def test_a_locked_copy_is_not_deleted_even_by_the_service(self, db, tmp_path):
        """A lock only the route honoured would protect nothing the day some other caller works
        out the doomed list its own way."""
        _make(db, tmp_path)
        svc.set_lock(str(tmp_path), 'copia', True)
        assert svc.delete_backup(str(tmp_path), 'copia') is False
        assert svc.list_backups(str(tmp_path))[0]['name'] == 'copia'
        svc.set_lock(str(tmp_path), 'copia', False)
        assert svc.delete_backup(str(tmp_path), 'copia') is True

    def test_the_markers_do_not_outlive_the_archive(self, db, tmp_path):
        """A `.lock` left behind is the dangerous half: a later copy taking the same name would
        be born protected, never pruned, and nothing on screen would explain why."""
        _make(db, tmp_path)
        svc.set_lock(str(tmp_path), 'copia', True)
        svc.set_lock(str(tmp_path), 'copia', False)
        assert svc.delete_backup(str(tmp_path), 'copia') is True
        assert os.listdir(self._root(tmp_path)) == []

    def test_a_damaged_marker_still_counts_as_locked(self, db, tmp_path):
        """The file's existence is the flag; its contents are a courtesy. Reading a damaged
        courtesy as "not protected" is failing in the one direction a lock must not."""
        _make(db, tmp_path)
        with open(os.path.join(self._root(tmp_path), 'copia.zip.lock'), 'w',
                  encoding='utf-8') as fh:
            fh.write('{ half written')
        b = svc.list_backups(str(tmp_path))[0]
        assert b['locked'] is True and b['lock_by'] == ''
        assert svc.delete_backup(str(tmp_path), 'copia') is False


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


class TestACopyKnowsWhetherItWorked:
    """"It finished" is not an answer to "is it usable". A copy that lost one table is not the
    same thing as one that lost none, and the difference has to survive in the archive: the
    copy is what somebody restores from months later, and the screen that judged it will be
    gone."""

    def test_a_clean_copy_says_ok(self, db, tmp_path):
        man = _make(db, tmp_path)['manifest']
        assert man['status'] == 'ok'
        assert {s['part'] for s in man['steps']} == {'core'}
        assert all(s['ok'] for s in man['steps'])

    def test_a_part_that_produced_nothing_is_not_ok(self, db, tmp_path):
        """`config_file` asked for and absent. Writing the copy anyway and calling it complete
        is how a restore finds out at the worst moment."""
        res = svc.create_backup(db, 'sincfg', var_dir=str(tmp_path),
                                config_dir=str(tmp_path / 'no-such-dir'),
                                parts=['core', 'config_file'], include_secrets=True)
        man = res['manifest']
        assert man['status'] == 'partial'
        bad = [s for s in man['steps'] if not s['ok']]
        assert [s['part'] for s in bad] == ['config_file']
        assert bad[0]['error']

    def test_the_steps_are_per_part_not_per_table(self):
        """The part is the unit somebody ticked; the table is how it gets written."""
        parts = {p['id'] for p in svc.parts_catalogue()}
        assert 'core' in parts and 'syslog' in parts


class TestCheckingACopy:
    """A copy is a file that gets moved to another disk, another machine, a tape — and none of
    those tell you it arrived intact."""

    def test_every_member_carries_a_digest(self, db, tmp_path):
        man = _make(db, tmp_path)['manifest']
        assert man['sha256'], 'nothing to check the contents against'
        assert all(len(v) == 64 for v in man['sha256'].values())

    def test_the_archive_gets_a_sidecar_in_sha256sum_format(self, db, tmp_path):
        """`sha256sum -c` on the target machine validates it without this panel involved."""
        _make(db, tmp_path)
        side = os.path.join(str(tmp_path), 'backups', 'copia.zip.sha256')
        assert os.path.isfile(side)
        line = open(side, encoding='utf-8').read().split()
        assert len(line[0]) == 64 and line[1] == 'copia.zip'

    def test_a_good_copy_verifies(self, db, tmp_path):
        _make(db, tmp_path)
        out = svc.verify_backup(str(tmp_path), 'copia')
        assert out['ok'] is True and out['file'] == 'ok' and out['bad'] == []

    def test_a_tampered_member_is_caught(self, db, tmp_path):
        """Intact as a FILE and altered inside — the failure a sidecar alone cannot see."""
        _make(db, tmp_path)
        path = os.path.join(str(tmp_path), 'backups', 'copia.zip')
        with zipfile.ZipFile(path) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        members['db/hosts.json'] = b'{"columns":[],"rows":[]}'
        with zipfile.ZipFile(path, 'w') as zf:
            for n, b in members.items():
                zf.writestr(n, b)
        out = svc.verify_backup(str(tmp_path), 'copia')
        assert out['ok'] is False
        assert [b['member'] for b in out['bad']] == ['db/hosts.json']

    def test_a_damaged_file_is_caught(self, db, tmp_path):
        _make(db, tmp_path)
        path = os.path.join(str(tmp_path), 'backups', 'copia.zip')
        with open(path, 'ab') as fh:
            fh.write(b'rubbish')
        assert svc.verify_backup(str(tmp_path), 'copia')['file'] == 'bad'

    def test_a_missing_sidecar_is_reported_not_failed(self, db, tmp_path):
        """Copies written before checksums existed have none, and calling those corrupt would
        be the check lying."""
        _make(db, tmp_path)
        os.remove(os.path.join(str(tmp_path), 'backups', 'copia.zip.sha256'))
        out = svc.verify_backup(str(tmp_path), 'copia')
        assert out['file'] == 'missing' and out['ok'] is True

    def test_verifying_something_that_is_not_there(self, db, tmp_path):
        assert svc.verify_backup(str(tmp_path), 'nope')['ok'] is False


class TestRestoringACopyFromAnotherVersion:
    """The schema moves on almost every build, so a copy and the install it lands on rarely
    match. Nothing is REFUSED over that — a panel that turned down "old" copies would be
    useless on the one day it is needed — but what could not be taken is reported, because
    silent is what turns a version jump into data loss instead of a decision.
    """

    def test_it_says_which_way_the_jump_goes(self):
        assert svc.version_relation('0.0.1+build.58', '0.0.1+build.58') == 'same'
        assert svc.version_relation('0.0.1+build.40', '0.0.1+build.58') == 'older'
        assert svc.version_relation('0.0.1+build.80', '0.0.1+build.58') == 'newer'

    def test_it_says_unknown_rather_than_guessing(self):
        """A copy from before the build counter, or one whose version did not travel, is not
        "older" — it is unanswerable, and answering anyway is how a warning stops meaning
        anything."""
        assert svc.version_relation('', '0.0.1+build.58') == 'unknown'
        assert svc.version_relation('1.2.3', '0.0.1+build.58') == 'unknown'

    def test_the_list_carries_it(self, db, tmp_path):
        _make(db, tmp_path, app_version='0.0.1+build.80')
        got = svc.list_backups(str(tmp_path), '', '0.0.1+build.58')[0]
        assert got['version_rel'] == 'newer'

    def test_a_column_the_live_schema_lost_is_reported_not_hidden(self, db, tmp_path):
        """This is exactly what restoring a copy from a LATER build does: the columns this
        schema does not have yet go, and the operator has to be told which."""
        _make(db, tmp_path)
        db.execute('DROP TABLE hosts')
        db.reconcile_table(_spec('hosts', ['uid', 'name']))     # `address` is gone
        db.commit()
        out = svc.restore_backup(db, str(tmp_path), 'copia')
        assert out['ok']
        assert out['skipped']['hosts'] == {'columns': ['address']}
        assert out['tables']['hosts'] == 1, 'the rest of the row still went in'

    def test_a_table_the_install_no_longer_has_is_reported_with_its_rows(self, db, tmp_path):
        """Its rows are the number that matters: "the table is gone" is a shrug, "1 row did
        not go in" is something to decide about."""
        _make(db, tmp_path)
        db.execute('DROP TABLE credentials')
        db.commit()
        out = svc.restore_backup(db, str(tmp_path), 'copia')
        assert out['skipped']['credentials'] == {'missing': True, 'rows': 1}

    def test_nothing_skipped_when_the_schema_matches(self, db, tmp_path):
        """Empty is the normal answer; anything in it is the difference between "restored" and
        "restored, and here is what did not survive the trip"."""
        _make(db, tmp_path)
        assert svc.restore_backup(db, str(tmp_path), 'copia')['skipped'] == {}

    def test_the_result_names_the_build_that_made_it(self, db, tmp_path):
        """So the log can say where the rows came from, months after the answer on screen is
        gone."""
        _make(db, tmp_path, app_version='0.0.1+build.40')
        assert svc.restore_backup(db, str(tmp_path), 'copia')['app_version'] \
            == '0.0.1+build.40'


class TestARestoreSaysWhereItIs:
    """The copy reports which table it is writing; putting one back had to as well — it is the
    longer of the two, and the one that is replacing what the install already holds."""

    def test_it_reports_every_step(self, db, tmp_path):
        _make(db, tmp_path, parts=['core', 'config_file'])
        seen = []
        svc.restore_backup(db, str(tmp_path), 'copia', config_dir=str(tmp_path),
                           progress_cb=seen.append)
        assert seen, 'nothing to draw a bar against'
        assert seen[0]['step'] == 1 and seen[-1]['step'] == seen[-1]['total']
        assert 'config.json' in [s['table'] for s in seen], 'only the tables are counted'

    def test_the_shape_is_the_one_the_copy_uses(self, db, tmp_path):
        """One shape means one dialog: the two are the same wait to whoever is watching."""
        _make(db, tmp_path)
        seen = []
        svc.restore_backup(db, str(tmp_path), 'copia', progress_cb=seen.append)
        assert set(seen[0]) == {'step', 'total', 'table', 'steps'}

    def test_a_broken_reporter_does_not_lose_the_restore(self, db, tmp_path):
        """Here it would abort a transaction — the same rule the copy follows, for a worse
        reason."""
        _make(db, tmp_path)

        def _boom(_):
            raise RuntimeError('the screen went away')

        assert svc.restore_backup(db, str(tmp_path), 'copia', progress_cb=_boom)['ok']

    def test_a_copy_that_is_not_there_is_answered_not_started(self, tmp_path):
        assert svc.backup_exists(str(tmp_path), 'nope') is False


class TestItSaysWhatItIsDoingOnTheLog:
    """A copy and a restore take minutes, run on a thread and rewrite the install — and they
    used to go past in total silence, so a screen that failed to open its dialog left nothing
    anywhere to say whether anything had happened at all."""

    @staticmethod
    def _lines(capsys):
        return [l for l in capsys.readouterr().out.splitlines() if 'Backup' in l]

    def test_a_copy_says_it_started_and_how_it_ended(self, db, tmp_path, capsys):
        _make(db, tmp_path)
        out = '\n'.join(self._lines(capsys))
        assert "create >> 'copia'" in out
        assert 'rows in' in out and 'ok' in out

    def test_a_refusal_says_why(self, db, tmp_path, capsys):
        _make(db, tmp_path)
        self._lines(capsys)
        _make(db, tmp_path)                       # the same name twice
        assert 'already exists' in '\n'.join(self._lines(capsys))

    def test_a_restore_names_the_copy_and_the_build_that_made_it(self, db, tmp_path, capsys):
        _make(db, tmp_path, app_version='0.0.1+build.40')
        self._lines(capsys)
        svc.restore_backup(db, str(tmp_path), 'copia')
        out = '\n'.join(self._lines(capsys))
        assert "restore >> 'copia'" in out and '0.0.1+build.40' in out
        assert 'done,' in out

    def test_what_could_not_be_applied_is_logged_as_a_warning(self, db, tmp_path, capsys):
        """The line somebody greps for. Buried in a summary it goes unnoticed, which is the
        whole failure this reports against."""
        _make(db, tmp_path)
        db.execute('DROP TABLE credentials')
        db.commit()
        self._lines(capsys)
        svc.restore_backup(db, str(tmp_path), 'copia')
        out = '\n'.join(self._lines(capsys))
        assert 'credentials' in out and 'table is gone' in out
        assert 'WARNING' in out


class TestARestoreTicksOffTheSameChecklist:
    """The copy reports one entry per PART — the unit somebody ticked in the form. Putting one
    back reported "148 rows" and left them to work out which of the six things they asked for
    had actually arrived."""

    def test_every_part_gets_an_entry(self, db, tmp_path):
        (tmp_path / 'config.json').write_text('{}', encoding='utf-8')
        _make(db, tmp_path, parts=['core', 'config_file', 'syslog'])
        out = svc.restore_backup(db, str(tmp_path), 'copia', config_dir=str(tmp_path))
        assert {s['part'] for s in out['steps']} == {'core', 'config_file', 'syslog'}
        assert all(s['ok'] for s in out['steps']), out['steps']

    def test_the_entries_carry_what_went_in(self, db, tmp_path):
        _make(db, tmp_path)
        core = next(s for s in svc.restore_backup(db, str(tmp_path), 'copia')['steps']
                    if s['part'] == 'core')
        assert core['rows'] > 0 and core['tables'] > 0

    def test_a_part_that_lost_something_is_not_ok_and_says_what(self, db, tmp_path):
        _make(db, tmp_path)
        db.execute('DROP TABLE credentials')
        db.commit()
        core = next(s for s in svc.restore_backup(db, str(tmp_path), 'copia')['steps']
                    if s['part'] == 'core')
        assert not core['ok']
        assert 'credentials' in core['error']

    def test_it_keeps_the_first_reason_not_the_last(self, db, tmp_path):
        """The first thing that went wrong explains the rest; a message overwritten five times
        says only what happened at the end."""
        _make(db, tmp_path)
        db.execute('DROP TABLE audit')      # its own part, so `core` keeps two failures
        db.execute('DROP TABLE credentials')
        db.execute('DROP TABLE hosts')
        db.commit()
        core = next(s for s in svc.restore_backup(db, str(tmp_path), 'copia')['steps']
                    if s['part'] == 'core')
        assert core['error'].startswith('credentials'), core['error']

    def test_the_checklist_travels_as_it_goes(self, db, tmp_path):
        """So the dialog ticks entries off while it runs, instead of showing them all at the
        end — which is a checklist that arrives after the wait it existed for."""
        _make(db, tmp_path)
        seen = []
        svc.restore_backup(db, str(tmp_path), 'copia',
                           progress_cb=lambda p: seen.append(len(p['steps'])))
        assert seen and seen[-1] >= 1

    def test_a_config_part_that_is_not_in_the_archive_is_not_ok(self, db, tmp_path):
        """Asked for and not there: silence would be a panel that comes back with the old
        settings and nothing to say why."""
        _make(db, tmp_path, parts=['core', 'config_file'])
        # The copy carries the part but the file never existed, so the member is absent.
        out = svc.restore_backup(db, str(tmp_path), 'copia', config_dir=str(tmp_path))
        cfg = next(s for s in out['steps'] if s['part'] == 'config_file')
        assert not cfg['ok'] and 'config.json' in cfg['error']


class TestSyslogInADatabaseOfItsOwn:
    """Reported: with a second database configured, the restore brought no syslog back.

    `syslog_db|enabled` sends that feed to its own database, and the copy only ever read the
    system one — so the `syslog` part found no such table, copied nothing, said nothing was
    wrong, and the emptiness surfaced at restore time. Which is the one moment nobody can
    afford to find out.
    """

    @pytest.fixture
    def two(self, tmp_path):
        """A system database WITHOUT the syslog tables, and a second one that has them."""
        main = SQLiteConnector(str(tmp_path / 'data.db'))
        main.reconcile_table(_spec('hosts', ['uid', 'name']))
        main.execute("INSERT INTO hosts (uid, name) VALUES ('h1','PVE01')")
        main.commit()
        side = SQLiteConnector(str(tmp_path / 'syslog.db'))
        side.reconcile_table(_spec('syslog', ['uid', 'msg']))
        side.reconcile_table(_spec('syslog_drops', ['uid', 'reason']))
        side.execute("INSERT INTO syslog (uid, msg) VALUES ('s1','noisy')")
        side.execute("INSERT INTO syslog_drops (uid, reason) VALUES ('d1','rate')")
        side.commit()
        yield main, side
        main.close()
        side.close()

    def test_the_copy_reaches_the_second_database(self, two, tmp_path):
        main, side = two
        res = svc.create_backup(main, 'copia', var_dir=str(tmp_path), config_dir=str(tmp_path),
                                parts=['core', 'syslog'], include_secrets=True,
                                connectors={'syslog': side})
        assert res['ok'], res.get('message')
        assert res['manifest']['tables'].get('syslog') == 1, res['manifest']['tables']
        assert res['manifest']['tables'].get('syslog_drops') == 1

    def test_without_the_map_the_part_comes_back_empty(self, two, tmp_path):
        """The bug itself, kept as a test: the same call without the second connector finds
        nothing — which is why the fix is passing it, not hoping the tables are there."""
        main, _side = two
        res = svc.create_backup(main, 'copia', var_dir=str(tmp_path), config_dir=str(tmp_path),
                                parts=['core', 'syslog'], include_secrets=True)
        assert 'syslog' not in res['manifest']['tables']

    def test_the_restore_puts_them_back_where_they_live(self, two, tmp_path):
        main, side = two
        svc.create_backup(main, 'copia', var_dir=str(tmp_path), config_dir=str(tmp_path),
                          parts=['core', 'syslog'], include_secrets=True,
                          connectors={'syslog': side})
        side.execute('DELETE FROM syslog')
        side.commit()
        out = svc.restore_backup(main, str(tmp_path), 'copia', connectors={'syslog': side})
        assert out['ok'], out.get('message')
        assert side.fetchone('SELECT msg FROM syslog')[0] == 'noisy'
        assert main.fetchone('SELECT name FROM hosts')[0] == 'PVE01'

    def test_the_second_database_does_not_pollute_core(self, two, tmp_path):
        """`core` is every table nobody claimed IN THE SYSTEM DATABASE. Asking the wrong one
        would sweep a syslog table into it and restore it to the wrong place."""
        main, side = two
        by_part = dict(svc._tables_by_part(main, {'core', 'syslog'}, {'syslog': side}))
        assert by_part['core'] == ['hosts']
        assert by_part['syslog'] == ['syslog', 'syslog_drops']

    def test_each_database_gets_its_own_transaction(self, two):
        """Two databases cannot share one, and the guarantee that matters — the system tables
        land together or not at all — is kept where it means something."""
        main, side = two
        groups = svc._by_database([('core', ['hosts']), ('syslog', ['syslog'])], main,
                                  {'syslog': side})
        assert [c for c, _g in groups] == [main, side]

    def test_one_database_stays_one_transaction(self, db):
        """With `syslog_db` off the web admin hands back the main connector for both, and a
        restore that split them into two transactions would give up the atomicity for nothing."""
        groups = svc._by_database([('core', ['hosts']), ('syslog', ['syslog'])], db, {})
        assert len(groups) == 1

    def test_an_unreachable_second_database_costs_only_its_part(self, two, tmp_path):
        """The copy of everything else is still worth having."""
        main, side = two
        side.close()
        res = svc.create_backup(main, 'copia', var_dir=str(tmp_path), config_dir=str(tmp_path),
                                parts=['core', 'syslog'], include_secrets=True,
                                connectors={'syslog': side})
        assert res['ok'] and 'hosts' in res['manifest']['tables']
