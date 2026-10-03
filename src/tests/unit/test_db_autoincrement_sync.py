#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rows that go in WITH their ids must leave the id generator past them.

A schema rebuild copies the old table into a new one (``INSERT INTO tmp SELECT …``) and a
backup restore refills a table from the archive — both with the ids the rows already had.
SQLite and MySQL/MariaDB derive the next id from the table's maximum, so nothing is needed
there. PostgreSQL hands ids out from a sequence that only ``nextval`` moves: after either path
the sequence still said 1, and the next plain INSERT into `audit`, `history`,
`history_series`… collided with a row already there. Audit and history swallow write errors,
so from then on every new entry was lost without a word.

The fix is a connector hook, ``sync_autoincrement(table)``: a no-op by default, a ``setval``
per serial/identity column on PostgreSQL, called by both paths. There is no PostgreSQL to run
against here, so the PostgreSQL half is checked on the SQL it emits; the live check is
``tests/e2e/test_db_portability_live.py``.
"""

from lib.core.backup import restore as bk_restore
from lib.db import get_connector
from lib.db.postgresql import PostgreSQLConnector
from lib.db.schema import Column, TableSpec


class _PgCapture(PostgreSQLConnector):
    """The real PostgreSQL connector's SQL, with no server: reads are recorded, not run."""

    def __init__(self, serial_cols):        # pylint: disable=super-init-not-called
        self.serial_cols = serial_cols
        self.reads = []

    def fetchall(self, sql, params=()):
        self.reads.append((sql, params))
        return [(c,) for c in self.serial_cols]

    def fetchone(self, sql, params=()):
        self.reads.append((sql, params))
        return (1,)


def _recording(db):
    """Make *db* note every table it is asked to resynchronise."""
    calls = []
    db.sync_autoincrement = calls.append
    return calls


class TestPostgreSQLMovesTheSequence:

    def test_each_serial_column_gets_a_setval_past_its_maximum(self):
        pg = _PgCapture(['id'])
        pg.sync_autoincrement('audit')
        lookup, setval = pg.reads
        # The serial columns come from the catalog: default `nextval(…)` or an identity.
        assert 'information_schema.columns' in lookup[0]
        assert lookup[1] == ('audit', 'nextval(%')
        assert "is_identity = 'YES'" in lookup[0]
        sql, params = setval
        assert 'setval(pg_get_serial_sequence(?, ?)' in sql
        assert 'COALESCE((SELECT MAX("id") FROM "audit"), 0) + 1, false' in sql
        assert params == ('"audit"', 'id')

    def test_a_table_without_a_serial_column_emits_no_setval(self):
        pg = _PgCapture([])
        pg.sync_autoincrement('config')
        assert len(pg.reads) == 1 and 'setval' not in pg.reads[0][0]


class TestBothPathsCallTheHook:

    def test_a_rebuild_resynchronises_the_rebuilt_table(self):
        db = get_connector(None, default_sqlite_path=':memory:')
        db.reconcile_table(TableSpec(name='t', columns=(
            Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))))
        db.execute('INSERT INTO t (a) VALUES (?)', ('x',))
        db.commit()
        calls = _recording(db)
        # A nullability change is a rebuild: the copy carries the id across.
        db.reconcile_table(TableSpec(name='t', columns=(
            Column('id', 'AUTOINCREMENT', primary_key=True),
            Column('a', 'TEXT', nullable=False, default="''"))))
        assert calls == ['t']
        assert db.fetchall('SELECT id, a FROM t') == [(1, 'x')]

    def test_a_restore_resynchronises_every_table_it_refills(self):
        db = get_connector(None, default_sqlite_path=':memory:')
        db.reconcile_table(TableSpec(name='t', columns=(
            Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))))
        calls = _recording(db)
        rows, dropped = bk_restore._load_table(   # pylint: disable=protected-access
            db, 't', {'columns': ['id', 'a'], 'rows': [[7, 'x'], [9, 'y']]})
        assert (rows, dropped) == (2, [])
        assert calls == ['t']

    def test_the_default_hook_is_a_no_op_and_sqlite_continues_past_the_maximum(self):
        db = get_connector(None, default_sqlite_path=':memory:')
        db.reconcile_table(TableSpec(name='t', columns=(
            Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))))
        bk_restore._load_table(                   # pylint: disable=protected-access
            db, 't', {'columns': ['id', 'a'], 'rows': [[7, 'x']]})
        db.execute('INSERT INTO t (a) VALUES (?)', ('new',))
        assert db.fetchone('SELECT MAX(id) FROM t') == (8,)
