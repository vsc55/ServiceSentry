#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistence defects found by the 2026-10-12 audit — the connectors, rebuilds and history.

- PostgreSQL: resynchronising a sequence after a restore pulled it DOWN to the restored
  maximum, so new `audit`/syslog rows reused ids the events worker had already passed.
- PostgreSQL listed the index behind a UNIQUE constraint as a manual index, and every table
  rebuild recreated it beside the new table's own constraint: one more duplicate per rebuild.
- `Rows.list(offset=n)` with no limit wrote `LIMIT -1`, which only SQLite accepts.
- A history sample was committed without its measurements when writing those failed.

No server engine here: PostgreSQL is checked on the SQL it emits (as in
``test_db_autoincrement_sync``), the rest on an in-memory SQLite.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.core.history.store import HistoryStore                   # noqa: E402
from lib.db import get_connector                                  # noqa: E402
from lib.db.base import BaseConnector                             # noqa: E402
from lib.db.postgresql import PostgreSQLConnector                 # noqa: E402
from lib.db.rows import Rows                                      # noqa: E402
from lib.db.schema import Column, Index, IndexInfo, TableSpec     # noqa: E402


# ── P7: a sequence is never moved backwards ──────────────────────────────────

class _PgSeq(PostgreSQLConnector):
    """The PostgreSQL connector's SQL with no server: one serial column, a table maximum and
    a sequence state, all made up."""

    def __init__(self, table_max, last_value, is_called):  # pylint: disable=super-init-not-called
        self.state = (table_max, last_value, is_called)
        self.reads = []

    def fetchall(self, sql, params=()):
        self.reads.append((sql, params))
        return [('id',)]

    def fetchone(self, sql, params=()):
        self.reads.append((sql, params))
        table_max, last_value, is_called = self.state
        if 'pg_get_serial_sequence' in sql:
            return ('public.audit_id_seq',)
        if 'is_called' in sql:
            return (last_value, is_called)
        if 'MAX(' in sql and 'setval' not in sql:
            return (table_max,)
        return (1,)

    def setval(self):
        """The value the last ``setval`` asked for (``nextval`` hands it out next)."""
        sql, params = [r for r in self.reads if 'setval' in r[0]][-1]
        assert ', false)' in sql
        return params[-1]


class TestSequenceKeepsItsHighWaterMark:

    def test_a_restore_with_a_lower_maximum_does_not_pull_the_sequence_down(self):
        # 500 ids were handed out; the restored copy only reaches 100.
        pg = _PgSeq(table_max=100, last_value=500, is_called=True)
        pg.sync_autoincrement('audit')
        assert pg.setval() == 501

    def test_rows_past_the_sequence_still_move_it_forward(self):
        pg = _PgSeq(table_max=900, last_value=500, is_called=True)
        pg.sync_autoincrement('audit')
        assert pg.setval() == 901

    def test_a_fresh_sequence_of_a_rebuilt_table_starts_past_the_copied_rows(self):
        pg = _PgSeq(table_max=42, last_value=1, is_called=False)
        pg.sync_autoincrement('audit')
        assert pg.setval() == 43


# ── P11: a rebuild does not multiply unique indexes ──────────────────────────

class _Recorder:
    """Just what ``_recreate_indexes_after_rebuild`` uses of a connector."""

    def __init__(self):
        self.sql = []

    @staticmethod
    def quote_ident(name):
        return f'"{name}"'

    def execute(self, sql, params=()):
        self.sql.append(sql)
        return 0

    _execute_optional = BaseConnector._execute_optional   # pylint: disable=protected-access


class TestRebuildIndexes:

    _SPEC = TableSpec(
        name='t',
        columns=(Column('id', 'AUTOINCREMENT', primary_key=True),
                 Column('name', 'TEXT', unique=True),
                 Column('a', 'TEXT'), Column('b', 'TEXT')),
        indexes=(Index('ix_t_a', ('a',)),),
        unique_constraints=(('a', 'b'),),
    )

    def _recreated(self, actual):
        rec = _Recorder()
        BaseConnector._recreate_indexes_after_rebuild(  # pylint: disable=protected-access
            rec, self._SPEC, actual)
        return ' | '.join(rec.sql)

    def test_the_old_tables_constraint_indexes_are_not_recreated_beside_the_new_ones(self):
        out = self._recreated([
            IndexInfo('t_name_key', ('name',), True),             # UNIQUE column
            IndexInfo('__ssreb_t_name_key', ('name',), True),     # a previous rebuild's copy
            IndexInfo('t_a_b_key', ('a', 'b'), True),             # UNIQUE (a, b)
        ])
        assert 't_name_key' not in out and 't_a_b_key' not in out

    def test_a_manual_index_still_survives_the_rebuild(self):
        out = self._recreated([IndexInfo('ix_manual', ('b',), False),
                               IndexInfo('ux_manual', ('b', 'a'), True)])
        assert '"ix_manual"' in out and '"ux_manual"' in out
        assert '"ix_t_a"' in out                                  # the spec's, as ever

    def test_postgresql_does_not_list_a_constraint_index_as_a_manual_one(self):
        seen = []

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=()):
                seen.append(sql)

            def fetchall(self):
                return []

        class _Conn:
            def cursor(self):
                return _Cur()

        pg = PostgreSQLConnector.__new__(PostgreSQLConnector)
        pg._conn = _Conn                                          # pylint: disable=protected-access
        pg._fold = lambda name: name                              # pylint: disable=protected-access
        assert pg.list_indexes('t') == []
        assert 'pg_constraint' in seen[0] and 'conindid = ix.indexrelid' in seen[0]


# ── P12: an offset with no limit is portable SQL ─────────────────────────────

class TestOffsetWithoutLimit:

    def test_no_sqlite_only_limit_and_the_rows_after_the_offset_come_back(self):
        db = get_connector(None, default_sqlite_path=':memory:')
        rows = Rows(db, TableSpec(name='t', columns=(
            Column('uid', 'TEXT', primary_key=True), Column('v', 'TEXT'))))
        rows.bootstrap()
        for i in range(5):
            rows.create({'uid': f'u{i}', 'v': str(i)})
        sent = []
        real = db.fetchall
        db.fetchall = lambda sql, params=(): (sent.append(sql), real(sql, params))[1]
        got = rows.list(offset=3)
        assert [r['uid'] for r in got] == ['u3', 'u4']
        assert 'LIMIT -1' not in sent[-1]
        assert 'OFFSET 3' in sent[-1]


# ── P13: a sample and its measurements live or die together ──────────────────

class TestSampleWithoutItsMeasurements:

    def test_a_failed_measurement_write_takes_the_sample_with_it(self):
        st = HistoryStore(get_connector(None, default_sqlite_path=':memory:'))
        st.record('snmp', 'host.h1/sda', status=True, data={'used': 1})   # the series exists
        before = st._db.fetchone('SELECT COUNT(*) FROM history')[0]
        samples = st._db.fetchone('SELECT samples FROM history_series')[0]

        def boom(*_a, **_k):
            raise RuntimeError('disk full')
        st._db.executemany = boom
        st.record('snmp', 'host.h1/sda', status=True, data={'used': 2})
        assert st._db.fetchone('SELECT COUNT(*) FROM history')[0] == before
        assert st._db.fetchone('SELECT samples FROM history_series')[0] == samples

    def test_a_sample_whose_measurements_write_is_recorded_whole(self):
        st = HistoryStore(get_connector(None, default_sqlite_path=':memory:'))
        st.record('snmp', 'host.h1/sda', status=True, data={'used': 1, 'temp': 30})
        assert st._db.fetchone('SELECT COUNT(*) FROM history')[0] == 1
        assert st._db.fetchone('SELECT COUNT(*) FROM history_fact')[0] == 2

    def test_a_sample_with_no_measurements_still_counts(self):
        st = HistoryStore(get_connector(None, default_sqlite_path=':memory:'))
        st.record('ping', 'host.h1', status=False, data={})
        assert st._db.fetchone('SELECT COUNT(*) FROM history')[0] == 1
