#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistence defects of the second 2026-10-12 audit (DB-1 … DB-7 and the minors).

Everything here runs on a temporary SQLite file or on a fake MySQL connection that records
what the connector asks of it. The engine-specific halves — the MariaDB rebuild that recreated
`varchar` without a length, the collation that merged `Rx` and `rx`, the transaction a swallowed
error left open — are proven on the real engines in ``tests/e2e/test_db_portability_live.py``.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import zipfile

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.db.mysql import MySQLConnector                           # noqa: E402
from lib.db.schema import (Column, ColumnInfo, Index, TableSpec,  # noqa: E402
                           create_table_ddl)
from lib.db.sqlite import SQLiteConnector                         # noqa: E402


@pytest.fixture
def sq(tmp_path):
    db = SQLiteConnector(str(tmp_path / 't6db.db'))
    yield db
    db.close()


# ── A fake PyMySQL connection: what the connector asked of it ────────────────

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.conn.log.append(sql)
        if self.conn.fail_on and self.conn.fail_on in sql:
            import pymysql  # noqa: PLC0415
            raise pymysql.err.IntegrityError(1062, 'Duplicate entry')
        return 1

    def fetchall(self):
        return list(self.conn.rows)

    def fetchone(self):
        return self.conn.rows[0] if self.conn.rows else None


class _FakeMyConn:
    def __init__(self):
        self.log, self.rows, self.fail_on = [], [], None
        self.pings = self.commits = self.rollbacks = 0

    def cursor(self, *_a):
        return _FakeCursor(self)

    def ping(self, reconnect=False):
        self.pings += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _fake_mysql():
    my = object.__new__(MySQLConnector)
    my._config = {}
    my._local = threading.local()
    my._local.conn = _FakeMyConn()
    return my, my._local.conn


# ── DB-1: the rebuild recreates a column it does not declare from the engine's own text ──

class TestDb1RebuildKeepsTheColumnWhole:

    def test_an_extra_column_is_recreated_from_its_whole_definition(self):
        """`data_type` alone is `varchar`, which MySQL refuses (1064) — and that was the DDL."""
        spec = TableSpec('t', (Column('id', 'AUTOINCREMENT', primary_key=True),))
        extra = ColumnInfo('EventUser', 'varchar', True, None,
                           definition='varchar(60) DEFAULT NULL')
        ddl = create_table_ddl(spec, {'AUTOINCREMENT': 'INT AUTO_INCREMENT PRIMARY KEY'},
                               lambda n: f'`{n}`', extra_columns=[extra])
        assert '`EventUser` varchar(60) DEFAULT NULL' in ddl

    def test_mysql_reads_each_definition_from_show_create_table(self):
        my, conn = _fake_mysql()
        conn.rows = [('t', 'CREATE TABLE `t` (\n'
                           '  `ID` int(10) unsigned NOT NULL AUTO_INCREMENT,\n'
                           "  `EventUser` varchar(60) DEFAULT NULL,\n"
                           "  `odd``name` varchar(5) NOT NULL DEFAULT 'x,y',\n"
                           '  PRIMARY KEY (`ID`)\n) ENGINE=InnoDB')]
        defs = my._column_definitions('t')
        assert defs['EventUser'] == 'varchar(60) DEFAULT NULL'
        assert defs['odd`name'] == "varchar(5) NOT NULL DEFAULT 'x,y'"
        assert 'PRIMARY' not in ' '.join(defs)

    def test_the_spec_names_rsyslogs_column_as_rsyslog_does(self, sq):
        """`EventUser`, as createDB.sql has it: a table rsyslog made reconciles with no
        rebuild and no column of its own left over."""
        from lib.services.syslog.store import messages as m
        from tests.helpers import RSYSLOG_CREATE
        sq.execute_ddl(RSYSLOG_CREATE)
        diff = sq.reconcile_table(m._SCHEMA)
        assert not diff.needs_rebuild, diff
        assert [c.name for c in diff.extra_columns] == []
        assert 'EventUser' in sq.list_columns('SystemEvents')

    def test_a_table_the_panel_made_with_the_old_name_is_renamed(self, sq):
        from dataclasses import replace
        from lib.services.syslog.store import messages as m
        old = replace(m._SCHEMA, renames={}, columns=tuple(
            replace(c, name='EventUserID') if c.name == 'EventUser' else c
            for c in m._SCHEMA.columns))
        sq.reconcile_table(old)
        sq.execute("INSERT INTO SystemEvents (EventUserID, Message) VALUES ('ana', 'm')")
        sq.commit()
        sq.reconcile_table(m._SCHEMA)
        cols = sq.list_columns('SystemEvents')
        assert 'EventUser' in cols and 'EventUserID' not in cols
        assert sq.fetchone('SELECT EventUser FROM SystemEvents')[0] == 'ana'


# ── DB-2: keys compared byte for byte on MySQL ───────────────────────────────

class TestDb2BinaryKeys:

    def test_a_key_column_is_created_binary_collated(self):
        assert 'COLLATE utf8mb4_bin' in MySQLConnector.DDL_TEXT_KEY
        spec = TableSpec('f', (Column('id', 'AUTOINCREMENT', primary_key=True),
                               Column('name', 'TEXT', nullable=False)),
                         indexes=(Index('ix_f', ('name',), unique=True),))
        my = object.__new__(MySQLConnector)
        ddl = create_table_ddl(spec, my._type_map, my.quote_ident)
        assert '`name` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL' in ddl

    def test_an_existing_unique_key_is_migrated_and_a_plain_index_is_not(self, monkeypatch):
        my, _conn = _fake_mysql()
        spec = TableSpec('f', (Column('id', 'AUTOINCREMENT', primary_key=True),
                               Column('name', 'TEXT', nullable=False),
                               Column('host', 'TEXT')),
                         indexes=(Index('ix_f', ('name',), unique=True),
                                  Index('ix_h', ('host',))))
        live = [ColumnInfo('id', 'int', False, None, 1, 'int(11) NOT NULL', None),
                ColumnInfo('name', 'varchar', False, None, 0, 'varchar(255) NOT NULL',
                           'utf8mb4_general_ci'),
                ColumnInfo('host', 'varchar', True, None, 0, 'varchar(63)',
                           'utf8mb4_general_ci')]
        ddl = []
        monkeypatch.setattr(my, 'describe_table', lambda _t: live)
        monkeypatch.setattr(my, 'execute_ddl', ddl.append)
        my._bin_keys(spec)
        assert ddl == ['ALTER TABLE `f` MODIFY COLUMN `name` varchar(255) CHARACTER SET '
                       'utf8mb4 COLLATE utf8mb4_bin NOT NULL']
        ddl.clear()
        live[1] = ColumnInfo('name', 'varchar', False, None, 0, 'varchar(255) NOT NULL',
                             'utf8mb4_bin')
        my._bin_keys(spec)
        assert ddl == [], 'a column already binary is left alone'

    def test_every_reconcile_runs_the_migration(self, monkeypatch):
        class _Spec:
            name = 't'
        from lib.db.base import BaseConnector
        my, _conn = _fake_mysql()
        seen = []
        from contextlib import nullcontext
        monkeypatch.setattr(BaseConnector, '_reconcile', lambda self, spec: 'diff')
        monkeypatch.setattr(my, '_reconcile_lock', lambda table: nullcontext())
        monkeypatch.setattr(my, '_widen_text', lambda spec: None)
        monkeypatch.setattr(my, '_bin_keys', seen.append)
        assert my.reconcile_table(_Spec()) == 'diff' and [s.name for s in seen] == ['t']


# ── DB-3: a field id is only cached once the transaction that made it committed ──

class TestDb3FieldIdsAfterRollback:

    def test_a_rolled_back_field_does_not_lend_its_id_to_the_next(self, sq, monkeypatch):
        from lib.core.history.store import HistoryStore
        h = HistoryStore(sq)
        real = h.facts.write
        calls = {'n': 0}

        def failing_once(*a, **kw):
            calls['n'] += 1
            out = real(*a, **kw)
            if calls['n'] == 1:
                raise RuntimeError('the sample fails after its field was registered')
            return out

        monkeypatch.setattr(h.facts, 'write', failing_once)
        h.record('m', 'k', True, {'alpha': 1})        # rolled back: `alpha` never existed
        h.record('m', 'k', True, {'beta': 2})         # SQLite hands `beta` the same id
        h.record('m', 'k', True, {'alpha': 3})
        got = [p['data'] for p in h.query('m', 'k', 0, time.time() + 5)]
        assert got == [{'beta': 2}, {'alpha': 3}], got

    def test_settle_keeps_committed_ids_and_drops_rolled_back_ones(self, sq):
        from lib.core.history.facts import FactStore
        f = FactStore(sq)
        f.bootstrap()
        with sq.transaction():
            f.field_ids(['a'])
        f.settle(committed=True)
        sq.begin()
        f.field_ids(['b'])
        sq.rollback()
        f.settle(committed=False)
        assert 'a' in f._field_ids and 'b' not in f._field_ids


# ── DB-4: a copy without secrets leaves out the configuration's too ──────────

class TestDb4ConfigSecrets:

    def test_a_json_string_secret_is_blanked(self):
        from lib.core.backup.archive import clean_cell
        assert clean_cell('"enc:gAAAAAsecret"', False) == '""'
        assert clean_cell('"enc:gAAAAAsecret"', True) == '"enc:gAAAAAsecret"'

    def test_a_cell_with_nothing_to_strip_keeps_its_bytes(self):
        from lib.core.backup.archive import clean_cell
        for raw in ('"plain"', '{"a": "café"}', '[1, 2]', '"enc"'):
            assert clean_cell(raw, False) == raw

    def test_the_config_table_goes_out_without_its_secrets(self, sq, tmp_path):
        from lib.core.backup import create as bk_create
        sq.reconcile_table(TableSpec('config', (Column('key', 'TEXT', primary_key=True),
                                                Column('value', 'TEXT'))))
        sq.execute("INSERT INTO config VALUES ('email|password', ?)",
                   (json.dumps('enc:gAAAAAsmtp'),))
        sq.execute("INSERT INTO config VALUES ('web_admin|lang', '\"es_ES\"')")
        sq.commit()
        out = bk_create.create_backup(sq, 'nosec', var_dir=str(tmp_path), config_dir='',
                                      parts=['core'], include_secrets=False)
        assert out['ok'], out
        with zipfile.ZipFile(tmp_path / 'backups' / 'nosec.zip') as zf:
            raw = zf.read('db/config.json').decode('utf-8')
        assert 'enc:' not in raw
        assert dict(json.loads(raw)['rows']) == {'email|password': '""',
                                                 'web_admin|lang': '"es_ES"'}


# ── DB-5: a write is diffed against what ITS caller read ─────────────────────

class TestDb5PerCallerBaseline:

    def test_another_threads_read_does_not_become_my_baseline(self, tmp_path):
        """Thread A reads; another process changes `theme`; thread B's read refreshes the
        shared cache; A writes `lang` from its old copy. Diffed against the cache, A's old
        `theme` looked like a change of A's — and was written back over the other one."""
        from lib.core.config.store import ConfigStore
        from lib.config.manager import ConfigManager
        from lib.db import get_connector
        path = str(tmp_path / 'shared.db')
        conns = []

        def make(n):
            db = get_connector(None, default_sqlite_path=path)
            conns.append(db)
            mgr = ConfigManager(ConfigStore(db), str(tmp_path / f'c{n}.json'))
            mgr.STAMP_TTL = 0
            return mgr

        mine, other = make(1), make(2)
        mine.write({'web_admin': {'lang': 'en_EN', 'theme': 'dark'}})
        box = {}
        step = threading.Event()
        go = threading.Event()

        def thread_a():
            box['cfg'] = mine.read()
            step.set()
            go.wait(10)
            box['cfg']['web_admin']['lang'] = 'es_ES'
            box['ok'] = mine.write(box['cfg'])

        t = threading.Thread(target=thread_a)
        t.start()
        step.wait(10)
        cfg = other.read()
        cfg['web_admin']['theme'] = 'light'
        assert other.write(cfg)
        assert mine.read()['web_admin']['theme'] == 'light'   # thread B refreshes the cache
        go.set()
        t.join(10)
        assert box['ok']
        now = make(3).read()['web_admin']
        for db in conns:
            db.close()
        assert now == {'lang': 'es_ES', 'theme': 'light'}, now

    def test_an_explicit_baseline_wins(self, tmp_path):
        from lib.core.config.store import ConfigStore
        from lib.config.manager import ConfigManager
        from lib.db import get_connector
        db = get_connector(None, default_sqlite_path=str(tmp_path / 's.db'))
        mgr = ConfigManager(ConfigStore(db), str(tmp_path / 'c.json'))
        mgr.write({'web_admin': {'lang': 'en_EN', 'theme': 'dark'}})
        mgr.read()
        # The caller says it read theme=dark and changes nothing: nothing is written.
        assert mgr.write({'web_admin': {'lang': 'en_EN', 'theme': 'dark'}},
                         baseline={'web_admin|lang': 'en_EN', 'web_admin|theme': 'dark'})
        assert mgr.read()['web_admin'] == {'lang': 'en_EN', 'theme': 'dark'}
        db.close()


# ── DB-6 and the ping: MySQL's transaction state after a failure ─────────────

class TestDb6MySQLFailureSettles:

    def test_a_swallowed_error_outside_begin_rolls_back_and_settles(self):
        my, conn = _fake_mysql()
        conn.fail_on = 'INSERT'
        with pytest.raises(Exception):
            my.execute("INSERT INTO t VALUES ('a', 2)")
        assert conn.rollbacks == 1
        assert my._tx().pending is False
        my.fetchall('SELECT 1')
        assert conn.commits == 1, 'the read after it did not end its transaction'

    def test_inside_begin_the_transaction_decides(self):
        my, conn = _fake_mysql()
        conn.fail_on = 'INSERT'
        my.begin()
        with pytest.raises(Exception):
            my.execute("INSERT INTO t VALUES ('a', 2)")
        assert conn.rollbacks == 0 and my._tx().explicit is True

    def test_ddl_settles_what_was_pending(self):
        my, conn = _fake_mysql()
        my.execute('UPDATE t SET a = 1')
        my.execute_ddl('CREATE INDEX i ON t (a)')
        assert my._tx().pending is False

    def test_no_ping_and_no_reconnect_mid_transaction(self):
        my, conn = _fake_mysql()
        my.fetchall('SELECT 1')
        assert conn.pings == 1                     # idle: checked (and reconnected if dead)
        my.execute('UPDATE t SET a = 1')
        my.execute('UPDATE t SET b = 2')
        my.fetchall('SELECT 1')
        assert conn.pings == 2, 'pinged — and could have reconnected — mid-transaction'
        my.commit()
        my.fetchall('SELECT 1')
        assert conn.pings == 3

    def test_a_failed_rollback_still_settles(self):
        my, conn = _fake_mysql()
        my.begin()

        def boom():
            raise OSError('gone')
        conn.rollback = boom
        with pytest.raises(OSError):
            my.rollback()
        assert my._tx().explicit is False


# ── DB-7: the copy and the restore stream ────────────────────────────────────

def _rows_table(sq, name, n, *, pk=True):
    cols = ((Column('id', 'INTEGER', primary_key=True),) if pk
            else (Column('id', 'INTEGER'),)) + (Column('v', 'TEXT'),)
    sq.reconcile_table(TableSpec(name, cols))
    sq.executemany(f'INSERT INTO {name} (id, v) VALUES (?, ?)',
                   [(i, f'v{i}\nline') for i in range(n)])
    sq.commit()


class TestDb7Streaming:

    def test_a_table_is_read_in_keyset_pages_never_whole(self, sq, monkeypatch):
        from lib.core.backup import create as bk_create
        _rows_table(sq, 'big', 23)
        seen = []
        real = sq.fetchall

        def spy(sql, params=()):
            seen.append(sql)
            return real(sql, params)
        monkeypatch.setattr(sq, 'fetchall', spy)
        got = [r for b in bk_create._table_batches(sq, 'big', ['id', 'v'], ['id'], size=5)
               for r in b]
        assert [r[0] for r in got] == list(range(23))
        pages = [s for s in seen if 'FROM "big"' in s]
        assert len(pages) == 5 and all('LIMIT 5' in s for s in pages)
        assert all('ORDER BY "id"' in s for s in pages)

    def test_a_composite_key_pages_by_row_value(self, sq):
        from lib.core.backup import create as bk_create
        sq.reconcile_table(TableSpec('cpk', (Column('a', 'INTEGER'), Column('b', 'INTEGER')),
                                     composite_pk=('a', 'b')))
        sq.executemany('INSERT INTO cpk (a, b) VALUES (?, ?)',
                       [(a, b) for a in range(3) for b in range(4)])
        sq.commit()
        got = [tuple(r) for bt in bk_create._table_batches(sq, 'cpk', ['a', 'b'], ['a', 'b'],
                                                         size=5) for r in bt]
        assert got == [(a, b) for a in range(3) for b in range(4)]

    def test_a_table_without_a_key_is_streamed_by_the_cursor(self, sq, monkeypatch):
        from lib.core.backup import create as bk_create
        _rows_table(sq, 'nokey', 12, pk=False)
        monkeypatch.setattr(sq, 'fetchall', lambda *a: pytest.fail('read whole'))
        sizes = [len(b) for b in bk_create._table_batches(sq, 'nokey', ['id', 'v'], [],
                                                          size=5)]
        assert sizes == [5, 5, 2]

    def test_the_member_has_one_row_per_line_and_is_still_one_json(self, sq, tmp_path):
        from lib.core.backup import create as bk_create
        _rows_table(sq, 'big', 7)
        out = bk_create.create_backup(sq, 'cp', var_dir=str(tmp_path), config_dir='',
                                      parts=['core'], include_secrets=True)
        assert out['ok'] and out['manifest']['tables']['big'] == 7
        with zipfile.ZipFile(tmp_path / 'backups' / 'cp.zip') as zf:
            raw = zf.read('db/big.json').decode('utf-8')
        lines = raw.split('\n')
        assert lines[0].endswith('"rows":[') and lines[-1] == ']}' and len(lines) == 9
        whole = json.loads(raw)                 # an older reader loads it whole, unchanged
        assert whole['columns'] == ['id', 'v'] and whole['rows'][3] == [3, 'v3\nline']
        from lib.core.backup import verify as bk_verify
        assert bk_verify.verify_backup(str(tmp_path), 'cp')['ok'] is True

    def test_the_restore_refills_in_batches(self, sq, tmp_path, monkeypatch):
        from lib.core.backup import archive as bk_archive
        from lib.core.backup import create as bk_create
        from lib.core.backup import restore as bk_restore
        _rows_table(sq, 'big', 11)
        assert bk_create.create_backup(sq, 'cp', var_dir=str(tmp_path), config_dir='',
                                       parts=['core'], include_secrets=True)['ok']
        sq.execute('DELETE FROM big')
        sq.commit()
        real_iter = bk_archive.iter_table_member
        monkeypatch.setattr(bk_restore, 'iter_table_member',
                            lambda zf, m: real_iter(zf, m, size=4))
        batches = []
        real_many = sq.executemany

        def spy(sql, rows):
            if 'INSERT INTO "big"' in sql:
                batches.append(len(rows))
            return real_many(sql, rows)
        monkeypatch.setattr(sq, 'executemany', spy)
        out = bk_restore.restore_backup(sq, str(tmp_path), 'cp', tables=['big'])
        assert out['ok'] and out['tables']['big'] == 11, out
        assert batches == [4, 4, 3]
        assert [r[1] for r in sq.fetchall('SELECT id, v FROM big ORDER BY id')][10] == \
            'v10\nline'

    def test_an_archive_in_the_old_layout_still_restores(self, sq, tmp_path):
        from lib.core.backup import archive as bk_archive
        from lib.core.backup import restore as bk_restore
        _rows_table(sq, 'big', 0)
        os.makedirs(tmp_path / 'backups')
        with zipfile.ZipFile(tmp_path / 'backups' / 'old.zip', 'w') as zf:
            zf.writestr('db/big.json', json.dumps(
                {'columns': ['id', 'v'], 'rows': [[1, 'a'], [2, 'b\nc']]},
                separators=(',', ':')))
            zf.writestr(bk_archive.MANIFEST_NAME, json.dumps(
                {'format': 1, 'name': 'old', 'parts': ['core'], 'tables': {'big': 2}}))
        out = bk_restore.restore_backup(sq, str(tmp_path), 'old', tables=['big'])
        assert out['ok'] and out['tables']['big'] == 2, out
        assert sq.fetchall('SELECT id, v FROM big ORDER BY id') == [(1, 'a'), (2, 'b\nc')]

    def test_the_member_reader_reads_both_layouts(self):
        from lib.core.backup.archive import iter_table_member, write_table_member
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            write_table_member(zf, 'new.json', ['a'], [[[1], [2]], [[3]]])
            zf.writestr('old.json', '{"columns":["a"],"rows":[[1],[2],[3]]}')
        with zipfile.ZipFile(buf) as zf:
            for member in ('new.json', 'old.json'):
                cols, batches = iter_table_member(zf, member, size=2)
                assert cols == ['a'] and list(batches) == [[[1], [2]], [[3]]]


# ── The minors ───────────────────────────────────────────────────────────────

class TestSessionsAreNotRewrittenAtBoot:

    def test_dropping_expired_ones_touches_nothing_else(self, sq):
        from lib.core.sessions.store import SessionsStore
        s = SessionsStore(sq)
        s.upsert('old', {'uid': 'u-old', 'last_seen': '2000-01-01'})
        s.upsert('live', {'uid': 'u-live', 'last_seen': '2999-01-01'})
        s.log_access('u-old', ts='2000', ip='', method='GET', path='/', status=200)
        s.log_access('u-live', ts='2999', ip='', method='GET', path='/', status=200)
        assert s.delete_tokens(['old']) == 1
        assert set(s.load()) == {'live'}
        assert s.access_for('u-old') == [] and s.access_for('u-live')

    def test_boot_does_not_sign_out_a_session_opened_meanwhile(self, sq):
        """The other replica's sign-in lands between this process's read and its prune."""
        pytest.importorskip('flask')
        from lib.core.sessions.mixin import _SessionsMixin
        from lib.core.sessions.store import SessionsStore
        store = SessionsStore(sq)
        store.upsert('stale', {'uid': 'u1', 'last_seen': '2000-01-01T00:00:00'})
        real_load = store.load

        def load_then_other_replica_signs_in():
            out = real_load()
            store.upsert('fresh', {'uid': 'u2', 'last_seen': '2999-01-01T00:00:00'})
            return out
        store.load = load_then_other_replica_signs_in

        class _Wa(_SessionsMixin):
            _REMEMBER_ME_DAYS = 30

        wa = _Wa.__new__(_Wa)
        wa._sessions_store = store
        wa._sessions = {}
        wa._load_sessions()
        assert set(real_load()) == {'fresh'}

    def test_save_all_updates_in_place_and_removes_only_the_rest(self, sq):
        from lib.core.sessions.store import SessionsStore
        s = SessionsStore(sq)
        s.upsert('a', {'uid': 'ua', 'last_seen': '1'})
        s.upsert('b', {'uid': 'ub', 'last_seen': '1'})
        assert s.save_all({'a': {'uid': 'ua', 'last_seen': '2'},
                           'c': {'uid': 'uc', 'last_seen': '3'}})
        got = s.load()
        assert set(got) == {'a', 'c'} and got['a']['last_seen'] == '2'
        assert s.save_all({}) and s.load() == {}


class TestOwnerIsSetAtomically:

    def test_a_failed_insert_keeps_the_previous_owner(self, sq, monkeypatch):
        from lib.core.orgs.store import OrgsStore
        o = OrgsStore(sq)
        assert o.set_owner('rack', 'r1', 'org-a', actor='t')
        real = sq.execute

        def failing(sql, params=()):
            if sql.startswith('INSERT INTO org_owner'):
                raise RuntimeError('disk full')
            return real(sql, params)
        monkeypatch.setattr(sq, 'execute', failing)
        with pytest.raises(RuntimeError):
            o.set_owner('rack', 'r1', 'org-b', actor='t')
        monkeypatch.undo()
        assert o.said_of('rack', 'r1') == 'org-a'


class TestAttachmentSaysWhoAndWhen:

    def test_created_by_is_the_actor_and_created_at_the_time(self, sq):
        from lib.core.dcim.files import FileStore
        f = FileStore(sq)
        uid = f.add('type-1', 'abc.pdf', 'Manual.pdf', 10, kind='other', actor='ana')
        row = f.get(uid)
        assert row['created_by'] == 'ana'
        assert row['created_at'][:2] == '20' and row['created_at'] != 'ana'


# ── July leftover: a lost race for the leader row is not a second read ────────────────────────

class TestLeaderInsertRace:
    """Two instances found no leader row and both INSERTed; the loser re-read the row inside a
    transaction its failed INSERT had already aborted on PostgreSQL. It now answers "not the
    leader" straight away: the winner holds the lease."""

    def test_the_loser_answers_false_without_reading_again(self):
        from contextlib import contextmanager
        from lib.services.manager.leader import ServiceLeaderStore

        class _DB:
            reads = 0

            @contextmanager
            def transaction(self):
                yield

            def fetchone(self, sql, params=()):
                _DB.reads += 1
                return None

            def execute(self, sql, params=()):
                raise RuntimeError('duplicate key')

        store = ServiceLeaderStore.__new__(ServiceLeaderStore)
        store._db = _DB()
        assert store.try_acquire('monitoring', 'b') is False
        assert _DB.reads == 1, 'it read again after the failed INSERT'
