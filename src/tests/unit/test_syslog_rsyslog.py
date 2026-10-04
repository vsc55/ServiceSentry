#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The syslog table is rsyslog's `SystemEvents`, so rsyslog can write to it and the panel read it.

rsyslog's `ommysql`/`ompgsql` write to the table its `createDB.sql` builds, with a stock
template that names eight columns. The panel's store lives in that same table: the rows
either side writes are rows the other can read, and `syslog_db` can be pointed at a database
rsyslog already fills.

What must hold for that to be true, and what these pin:

- a table rsyslog created is ADOPTED — our columns are appended, never a rebuild of a table
  that may hold millions of rows while rsyslog keeps inserting into it;
- a row inserted with rsyslog's stock template comes out of the API like one of ours;
- a row of ours carries what rsyslog's readers (LogAnalyzer) look for;
- the dates, which carry no zone, are read and written in the configured one;
- PostgreSQL, where rsyslog's unquoted SQL folds every name to lower case, and MySQL, where an
  indexed column added to an existing table must be a VARCHAR, both reach the same table;
- the backup finds the table whatever case the engine lists it in.
"""

import time
from datetime import datetime, timezone

import pytest

from lib.db import get_connector
from lib.db.mysql import MySQLConnector
from lib.db.postgresql import PostgreSQLConnector
from lib.db.schema import Column, Index, TableSpec, canonical_type, fold_spec
from lib.db.sqlite import SQLiteConnector
from lib.core.backup import parts as bk_parts
from lib.services.syslog.store import SyslogStore
from lib.services.syslog.store import messages as msgs
from tests.helpers import RSYSLOG_CREATE, STOCK_INSERT, rsyslog_utc as _utc

def _db():
    return get_connector(None, default_sqlite_path=':memory:')


def _rec(**kw):
    base = {'ts': time.time(), 'source': '10.0.0.1', 'hostname': 'h1', 'app': 'sshd',
            'procid': '42', 'severity': 6, 'facility': 4, 'msgid': 'ID1',
            'message': 'hello', 'raw': '<38>1 - h1 sshd 42 ID1 - hello', 'timestamp': ''}
    base.update(kw)
    return base


class TestATableRsyslogCreatedIsAdopted:

    def test_its_rows_survive_and_it_is_not_rebuilt(self):
        db = _db()
        db.execute_ddl(RSYSLOG_CREATE)
        db.execute(STOCK_INSERT, ('before', 3, 'fw1', 4, '2026-10-04 10:00:00',
                                  '2026-10-04 10:00:01', 1, 'kernel:'))
        db.commit()
        diff = db.reconcile_table(msgs._SCHEMA)
        # Before SyslogStore touched it: what it would do to rsyslog's table.
        assert not diff.needs_rebuild, diff
        assert [c.name for c in diff.missing_columns] == [
            'FromHostIP', 'ProgramName', 'ProcessID', 'MsgID', 'RawMessage']
        store = SyslogStore(db)
        rows = store.query()
        assert [r['message'] for r in rows] == ['before']

    def test_a_second_boot_finds_nothing_to_change(self):
        db = _db()
        db.execute_ddl(RSYSLOG_CREATE)
        SyslogStore(db)
        assert db.reconcile_table(msgs._SCHEMA).is_empty


class TestWhatRsyslogWritesTheUIReads:

    def test_a_stock_template_row_comes_out_like_ours(self):
        db = _db()
        store = SyslogStore(db)
        now = int(time.time())
        db.execute(STOCK_INSERT, ('Accepted password', 4, 'web01', 6, _utc(now), _utc(now),
                                  1, 'sshd[812]:'))
        db.commit()
        row = store.query()[0]
        assert row['hostname'] == 'web01' and row['message'] == 'Accepted password'
        assert row['app'] == 'sshd' and row['procid'] == '812'
        assert row['severity'] == 6 and row['severity_name'] == 'info'
        assert row['facility'] == 4 and row['facility_name'] == 'auth'
        assert row['ts'] == now
        assert row['received_at'] == time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))
        assert row['source'] == '' and row['raw'] == ''

    def test_the_event_worker_cursor_sees_it(self):
        db = _db()
        store = SyslogStore(db)
        store.add(_rec(message='ours'))
        db.execute(STOCK_INSERT, ('theirs', 1, 'fw', 2, _utc(time.time()),
                                  _utc(time.time()), 1, 'kernel:'))
        db.commit()
        assert [r['message'] for r in store.query_since(0)] == ['ours', 'theirs']

    def test_a_row_without_priority_does_not_break_the_charts(self):
        """rsyslog's columns are all nullable: a custom template may leave Priority out."""
        db = _db()
        store = SyslogStore(db)
        db.execute('INSERT INTO SystemEvents (Message, ReceivedAt) VALUES (?, ?)',
                   ('bare', _utc(time.time())))
        db.commit()
        st = store.stats()
        assert st['total'] == 1
        assert st['by_severity'][0]['value'] == 5
        assert store.query()[0]['severity'] == 5


class TestWhatWeWriteRsyslogsReadersFind:

    def test_the_columns_logAnalyzer_reads(self):
        db = _db()
        store = SyslogStore(db)
        now = time.time()
        store.add(_rec(ts=now))
        row = db.fetchone('SELECT Message, Facility, Priority, FromHost, SysLogTag, '
                          'InfoUnitID, ReceivedAt, FromHostIP, ProgramName, ProcessID, MsgID '
                          'FROM SystemEvents')
        assert row == ('hello', 4, 6, 'h1', 'sshd[42]:', 1, _utc(now), '10.0.0.1', 'sshd',
                       '42', 'ID1')

    def test_rsyslogs_varchar_60_is_respected(self):
        """A table rsyslog created has FromHost and SysLogTag as varchar(60)."""
        db = _db()
        store = SyslogStore(db)
        store.add(_rec(hostname='h' * 200, app='a' * 48, procid='9' * 30))
        host, tag = db.fetchone('SELECT FromHost, SysLogTag FROM SystemEvents')
        assert len(host) == 60 and len(tag) == 60

    def test_the_senders_own_time_goes_to_device_reported_time(self):
        db = _db()
        store = SyslogStore(db)
        store.add(_rec(timestamp='2026-10-04T12:00:00+02:00'))
        store.add(_rec(timestamp=''))
        reported = [r[0] for r in db.fetchall(
            'SELECT DeviceReportedTime FROM SystemEvents ORDER BY ID')]
        assert reported[0] == '2026-10-04 10:00:00'
        assert reported[1]           # the received time stands in for a missing one


class TestTheZoneOfTheDates:

    def test_utc_is_the_default(self):
        db = _db()
        now = time.time()
        SyslogStore(db).add(_rec(ts=now))
        assert db.fetchone('SELECT ReceivedAt FROM SystemEvents')[0] == _utc(now)

    def test_local_writes_and_reads_the_machines_time(self):
        db = _db()
        store = SyslogStore(db, time_zone=lambda: 'local')
        now = int(time.time())
        store.add(_rec(ts=now))
        stored = db.fetchone('SELECT ReceivedAt FROM SystemEvents')[0]
        assert stored == datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S')
        assert store.query()[0]['ts'] == now

    def test_since_and_until_compare_in_that_zone(self):
        db = _db()
        store = SyslogStore(db)
        store.add(_rec(ts=1_000_000, message='old'))
        store.add(_rec(ts=2_000_000, message='mid'))
        store.add(_rec(ts=3_000_000, message='new'))
        got = store.query({'since': 1_500_000, 'until': 2_500_000})
        assert [r['message'] for r in got] == ['mid']

    def test_retention_by_age_reads_received_at(self):
        db = _db()
        store = SyslogStore(db)
        store.add(_rec(ts=time.time() - 10 * 86400, message='old'))
        store.add(_rec(message='new'))
        assert store.prune(retention_days=5) == 1
        assert [r['message'] for r in store.query()] == ['new']

    def test_rsyslogs_mysql_date_form_is_read(self):
        """`%timegenerated:::date-mysql%` is `YYYYMMDDHHMMSS`; MySQL converts it, a text
        column keeps it as it came."""
        store = SyslogStore(_db())
        assert store._from_db('20261004100000') == datetime(
            2026, 10, 4, 10, tzinfo=timezone.utc).timestamp()


class TestEveryEngineReachesTheSameTable:

    def test_datetime_is_one_type_under_every_engines_name(self):
        for raw in ('datetime', 'DATETIME', 'timestamp', 'timestamp without time zone'):
            assert canonical_type(raw) == 'DATETIME', raw

    def test_postgresql_folds_the_spec_as_rsyslogs_unquoted_sql_does(self):
        f = fold_spec(msgs._SCHEMA)
        assert f.name == 'systemevents'
        assert 'receivedat' in f.column_names and 'ReceivedAt' not in f.column_names
        assert all(c == c.lower() for i in f.indexes for c in i.columns)
        pg = object.__new__(PostgreSQLConnector)
        assert pg.quote_ident('SystemEvents') == '"systemevents"'
        assert pg._type_map['DATETIME'] == 'TIMESTAMP'

    def test_mysql_adds_an_indexed_text_column_as_varchar(self):
        my = object.__new__(MySQLConnector)
        col = Column('ProgramName', 'TEXT')
        assert my._column_type_clause(col, keyed=True) == 'VARCHAR(255)'
        assert my._column_type_clause(col) == 'TEXT'

    def test_the_reconcile_asks_for_the_keyed_type(self):
        """An index over a column added to an existing table: MySQL cannot index TEXT."""

        class _Recording(SQLiteConnector):
            DDL_TEXT_KEY = 'VARCHAR(255)'
            added: list = []

            def add_column_if_missing(self, table, column, col_type):
                self.added.append((column, col_type))
                super().add_column_if_missing(table, column, col_type)

        db = _Recording(':memory:')
        db.reconcile_table(TableSpec('t', (Column('a', 'TEXT'),)))
        db.reconcile_table(TableSpec('t', (Column('a', 'TEXT'), Column('b', 'TEXT'),
                                           Column('c', 'TEXT')),
                                     indexes=(Index('idx_t_b', ('b',)),)))
        assert dict(db.added) == {'b': 'VARCHAR(255)', 'c': 'TEXT'}


class TestTheBackupFindsItInAnyCase:

    class _Lists:
        def __init__(self, names):
            self._names = names

        def list_tables(self):
            return list(self._names)

    def test_a_lower_case_listing_still_belongs_to_the_syslog_part(self):
        conn = self._Lists(['devices', 'systemevents', 'systemeventsproperties',
                            'syslog_drops'])
        by_part = {pid: tabs for pid, tabs, _err in
                   bk_parts.tables_by_part(conn, {'core', 'syslog'}, {})}
        assert by_part['syslog'] == ['SystemEvents', 'SystemEventsProperties', 'syslog_drops']
        assert by_part['core'] == ['devices']


class TestTheTag:

    def test_split(self):
        assert msgs.split_tag('sshd[123]:') == ('sshd', '123')
        assert msgs.split_tag('kernel:') == ('kernel', '')
        assert msgs.split_tag('CRON[9]') == ('CRON', '9')
        assert msgs.split_tag('') == ('', '')


class TestExternalModeOnlyReads:
    """`syslog_db|mode = external`: rsyslog's database, read and never written or altered."""

    @staticmethod
    def _rsyslog_db():
        db = _db()
        db.execute_ddl(RSYSLOG_CREATE)
        db.execute(STOCK_INSERT, ('Accepted password', 4, 'web01', 6, _utc(time.time()),
                                  _utc(time.time()), 1, 'sshd[812]:'))
        db.commit()
        return db

    def test_the_schema_is_not_touched(self):
        db = self._rsyslog_db()
        before = [c.name for c in db.describe_table('SystemEvents')]
        SyslogStore(db, read_only=True)
        assert [c.name for c in db.describe_table('SystemEvents')] == before
        assert db.list_indexes('SystemEvents') == []
        assert not db.table_exists('SystemEventsProperties')

    def test_its_rows_are_read_without_our_columns(self):
        store = SyslogStore(self._rsyslog_db(), read_only=True)
        row = store.query()[0]
        assert (row['hostname'], row['app'], row['procid'], row['source'], row['raw']) == \
            ('web01', 'sshd', '812', '', '')
        assert store.count() == 1 and store.max_id() == 1
        assert [r['message'] for r in store.query_since(0)] == ['Accepted password']

    def test_filters_sorts_and_facets_on_a_missing_column_do_not_fail(self):
        store = SyslogStore(self._rsyslog_db(), read_only=True)
        assert store.query({'source': '10.0.0.1'}) == []
        assert len(store.query(sort='source')) == 1
        assert len(store.query({'host': 'web01'})) == 1
        assert store.distinct('source') == []
        assert store.distinct('hostname') == ['web01']
        st = store.stats()
        assert st['total'] == 1 and st['by_app'][0]['value'] == 'sshd[812]:'

    def test_nothing_is_written_pruned_or_emptied(self):
        db = self._rsyslog_db()
        store = SyslogStore(db, read_only=True)
        with pytest.raises(msgs.ReadOnlyStore):
            store.add(_rec())
        with pytest.raises(msgs.ReadOnlyStore):
            store.add_many([_rec()])
        assert store.prune(retention_days=0, max_rows=0) == 0
        assert store.prune(max_rows=1) == 0 and store.delete_all() == 0
        assert db.fetchone('SELECT COUNT(*) FROM SystemEvents')[0] == 1

    def test_a_table_that_is_not_there_reads_as_empty(self):
        store = SyslogStore(_db(), read_only=True)
        assert store.query() == [] and store.count() == 0 and store.max_id() == 0
        assert store.query_since(0) == [] and store.distinct('hostname') == []
        assert store.stats()['total'] == 0

    def test_the_syslog_database_mode_needs_the_dedicated_database(self):
        """`syslog_db|mode = external`: the syslog database itself is rsyslog's, read-only."""
        assert msgs.is_read_only({'enabled': True, 'mode': 'external'})
        assert not msgs.is_read_only({'enabled': False, 'mode': 'external'})
        assert not msgs.is_read_only({'enabled': True, 'mode': 'own'})
        assert not msgs.is_read_only({'enabled': True})
        assert not msgs.is_read_only(None)
