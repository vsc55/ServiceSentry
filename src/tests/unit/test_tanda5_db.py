#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Table-rebuild defects deferred from the 2026-10 audits, fixed once the owner approved them.

- P9: a rebuild copies the table (``INSERT … SELECT``) and then swaps the copy in. A row
  another session wrote after the copy's snapshot was in neither — the rebuild lost it.
  PostgreSQL now locks the table ACCESS EXCLUSIVE before the copy; MySQL/MariaDB (where
  ``RENAME TABLE`` is refused under ``LOCK TABLES``) copy the late rows across by primary key,
  once before the swap and once after it from the backup table.
- PostgreSQL: an old index that cannot be recreated (an expression index) was "skipped" by
  swallowing the error, but there a failed statement aborts the whole transaction, so every
  later statement failed and the rebuild rolled back. It is now fenced by a SAVEPOINT.

No server engine here: both connectors are checked on the SQL they emit, with a fake that
behaves as PostgreSQL does after a failed statement. The live MariaDB check of P9 is
``tests/e2e/test_db_portability_live.py``.
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.db.mysql import MySQLConnector                           # noqa: E402
from lib.db.postgresql import PostgreSQLConnector                 # noqa: E402
from lib.db.schema import Column, ColumnInfo, IndexInfo, TableSpec  # noqa: E402

_SPEC = TableSpec(name='t', columns=(
    Column('id', 'AUTOINCREMENT', primary_key=True),
    Column('a', 'TEXT', nullable=False, default="''")))
_ACTUAL = [ColumnInfo('id', 'INTEGER', False, None, 1), ColumnInfo('a', 'TEXT', True, None)]


class _InFailedSqlTransaction(Exception):
    """What psycopg2 raises for every statement after a failed one, until a rollback."""


class _PgFake(PostgreSQLConnector):
    """The PostgreSQL connector's own transaction logic, with a fake server under it that
    aborts the transaction on a failed statement, exactly as PostgreSQL does."""

    def __init__(self, failing=()):  # pylint: disable=super-init-not-called
        self._config = {}
        self._local = threading.local()
        self.failing = failing
        self.sql = []
        self.aborted = False
        self.savepoints = set()
        self.outcome = None

    def execute(self, sql, params=()):
        self.sql.append(sql)
        if sql.startswith('ROLLBACK TO SAVEPOINT'):
            name = sql.rsplit(' ', 1)[-1]
            assert name in self.savepoints
            self.aborted = False
            return 0
        if self.aborted:
            raise _InFailedSqlTransaction(sql)
        if sql.startswith('SAVEPOINT'):
            self.savepoints.add(sql.rsplit(' ', 1)[-1])
        if any(f in sql for f in self.failing):
            self.aborted = True
            raise RuntimeError(f'cannot create {sql}')
        self._tx().pending = True
        return 0

    def sync_autoincrement(self, table):
        self.execute(f'SELECT setval(pg_get_serial_sequence({table!r}, \'id\'), …)')

    def commit(self):
        # PostgreSQL turns the COMMIT of an aborted transaction into a ROLLBACK.
        self.outcome = 'rolled back' if self.aborted else 'committed'
        self._settled()

    def rollback(self):
        self.outcome = 'rolled back'
        self.aborted = False
        self._settled()


class _MyFake(MySQLConnector):
    """The MySQL connector's rebuild, recording its SQL instead of running it."""

    def __init__(self):  # pylint: disable=super-init-not-called
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        return 0

    def execute_ddl(self, ddl):
        self.sql.append(ddl)

    def commit(self):
        self.sql.append('COMMIT')


# ── P9: no row written during the copy is lost ───────────────────────────────

class TestRebuildKeepsLateRows:

    def test_postgresql_locks_the_table_before_it_copies_it(self):
        pg = _PgFake()
        pg._apply_rebuild(_SPEC, _ACTUAL, [])           # pylint: disable=protected-access
        lock = [i for i, s in enumerate(pg.sql) if s.startswith('LOCK TABLE')]
        copy = [i for i, s in enumerate(pg.sql) if s.startswith('INSERT INTO "__ssreb_t"')]
        assert lock and copy and lock[0] < copy[0]
        assert pg.sql[lock[0]] == 'LOCK TABLE "t" IN ACCESS EXCLUSIVE MODE'
        assert pg.outcome == 'committed'

    def test_mysql_copies_the_late_rows_before_and_after_the_swap(self):
        my = _MyFake()
        my._apply_rebuild(_SPEC, _ACTUAL, [])           # pylint: disable=protected-access
        rename = next(i for i, s in enumerate(my.sql) if s.startswith('RENAME TABLE'))
        drop = max(i for i, s in enumerate(my.sql) if s.startswith('DROP TABLE IF EXISTS `__ssbak_t`'))
        before = [i for i, s in enumerate(my.sql)
                  if s.startswith('INSERT INTO `__ssreb_t`') and 'NOT EXISTS' in s]
        after = [i for i, s in enumerate(my.sql)
                 if s.startswith('INSERT IGNORE INTO `t`') and 'FROM `__ssbak_t` AS s' in s]
        assert before and before[0] < rename, 'old -> copy pass missing before the swap'
        assert after and rename < after[0] < drop, 'backup -> live pass missing after the swap'
        assert 'd.`id` = s.`id`' in my.sql[after[0]]
        # The NOT NULL column keeps its COALESCE in the catch-up as in the copy.
        assert "COALESCE(`a`, '')" in my.sql[after[0]]

    def test_mysql_without_a_primary_key_has_nothing_to_match_on(self):
        spec = TableSpec(name='t', columns=(Column('a', 'TEXT', nullable=False, default="''"),))
        my = _MyFake()
        my._apply_rebuild(spec, [ColumnInfo('a', 'TEXT', True, None)], [])  # pylint: disable=protected-access
        assert not any('NOT EXISTS' in s for s in my.sql)
        assert any(s.startswith('RENAME TABLE') for s in my.sql)


# ── PostgreSQL: a skipped index does not roll the rebuild back ───────────────

class TestRebuildSkipsAnIndexWithoutAbortingIt:

    _EXPR = IndexInfo('ix_lower_a', ('lower(a)',), False)

    def test_a_failing_old_index_is_skipped_and_the_rebuild_commits(self):
        pg = _PgFake(failing=('"ix_lower_a"',))
        pg._apply_rebuild(_SPEC, _ACTUAL, [self._EXPR])  # pylint: disable=protected-access
        assert pg.outcome == 'committed'
        assert any(s.startswith('SELECT setval') for s in pg.sql)   # ran after the failure
        i = next(i for i, s in enumerate(pg.sql) if '"ix_lower_a"' in s)
        assert pg.sql[i - 1].startswith('SAVEPOINT') and pg.sql[i + 1].startswith('ROLLBACK TO')

    def test_an_index_that_succeeds_releases_its_savepoint(self):
        pg = _PgFake()
        pg._apply_rebuild(_SPEC, _ACTUAL, [self._EXPR])  # pylint: disable=protected-access
        assert pg.outcome == 'committed'
        i = next(i for i, s in enumerate(pg.sql) if '"ix_lower_a"' in s)
        assert pg.sql[i + 1].startswith('RELEASE SAVEPOINT')

    def test_outside_a_transaction_no_savepoint_is_taken(self):
        pg = _PgFake(failing=('boom',))
        assert pg._execute_optional('CREATE INDEX boom') is False  # pylint: disable=protected-access
        assert not any(s.startswith('SAVEPOINT') for s in pg.sql)

    @pytest.mark.parametrize('ok', [True, False])
    def test_the_base_hook_reports_whether_it_ran(self, ok):
        from lib.db.base import BaseConnector

        class _C:
            def execute(self, sql, params=()):
                if not ok:
                    raise RuntimeError(sql)
                return 0

        assert BaseConnector._execute_optional(_C(), 'X') is ok  # pylint: disable=protected-access
