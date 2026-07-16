#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite connector — uses the stdlib ``sqlite3`` module.

Thread-safety is achieved by maintaining one connection per thread via
``threading.local``.  WAL journal mode is enabled for concurrent read/write.
"""

from __future__ import annotations

import os
import sqlite3
import threading

from .base import BaseConnector
from .schema import ColumnInfo, IndexInfo, TableSpec


class SQLiteConnector(BaseConnector):
    """Thread-safe SQLite connector backed by ``threading.local``."""

    KIND              = 'sqlite'
    DDL_AUTOINCREMENT = 'INTEGER PRIMARY KEY AUTOINCREMENT'
    DDL_REAL          = 'REAL'
    DDL_TEXT          = 'TEXT'
    DDL_INTEGER       = 'INTEGER'

    def __init__(self, db_path: str) -> None:
        self._path  = db_path
        self._local = threading.local()
        if db_path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn()  # open + configure connection on the calling thread

    # ── Internal connection management ────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30, isolation_level=None)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=-4096')
            self._local.conn = conn
        return conn

    # ── Schema ────────────────────────────────────────────────────────────────

    def execute_ddl(self, ddl: str) -> None:
        conn = self._conn()
        for stmt in ddl.split(';'):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()

    def add_column_if_missing(
        self, table: str, column: str, col_type: str
    ) -> None:
        conn = self._conn()
        existing = {
            row[1]
            for row in conn.execute(f'PRAGMA table_info({table})').fetchall()
        }
        if column not in existing:
            conn.execute(
                f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'
            )
            conn.commit()

    def list_columns(self, table: str) -> set[str]:
        return {
            row[1]
            for row in self._conn().execute(
                f'PRAGMA table_info({table})'
            ).fetchall()
        }

    def describe_table(self, table: str) -> list[ColumnInfo]:
        """Introspect *table*'s columns via ``PRAGMA table_info``, in physical order."""
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        rows = self._conn().execute(f'PRAGMA table_info({table})').fetchall()
        return [
            ColumnInfo(
                name=r[1], type=r[2] or '', nullable=(r[3] == 0),
                default=r[4], pk=r[5],
            )
            for r in rows
        ]

    def list_indexes(self, table: str) -> list[IndexInfo]:
        """List *table*'s explicit ``CREATE INDEX`` indexes via ``PRAGMA index_list`` /
        ``index_info``. Autoindexes backing PRIMARY KEY / UNIQUE constraints (origin
        != 'c') and expression columns are skipped."""
        conn = self._conn()
        out: list[IndexInfo] = []
        # PRAGMA index_list: (seq, name, unique, origin, partial)
        for row in conn.execute(f'PRAGMA index_list({table})').fetchall():
            name, unique, origin = row[1], row[2], row[3]
            if origin != 'c':           # skip PK / UNIQUE-constraint autoindexes
                continue
            cols = [
                ci[2]                   # (seqno, cid, name)
                for ci in conn.execute(f'PRAGMA index_info({name})').fetchall()
                if ci[2] is not None    # skip expression columns
            ]
            out.append(IndexInfo(name=name, columns=tuple(cols), unique=bool(unique)))
        return out

    def _apply_rebuild(self, spec: TableSpec, actual_cols, actual_indexes) -> None:
        # The official SQLite table-rebuild procedure requires foreign-key
        # enforcement to be OFF, and the PRAGMA is a no-op inside a transaction —
        # so toggle it around the (transaction-wrapped) generic rebuild.
        conn = self._conn()
        if conn.in_transaction:
            conn.commit()
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            super()._apply_rebuild(spec, actual_cols, actual_indexes)
        finally:
            conn.execute('PRAGMA foreign_keys=ON')

    # ── Read ──────────────────────────────────────────────────────────────────

    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        self._trace_sql(sql)
        return self._conn().execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        self._trace_sql(sql)
        return self._conn().execute(sql, params).fetchone()

    # ── Write ─────────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> int:
        self._trace_sql(sql)
        cur = self._conn().execute(sql, params)
        return cur.rowcount

    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        self._trace_sql(sql)
        cur = self._conn().executemany(sql, params_list)
        return cur.rowcount

    def begin(self) -> None:
        # Autocommit mode (isolation_level=None) means no implicit transaction
        # is open, so an explicit BEGIN is needed to batch statements atomically.
        conn = self._conn()
        if not conn.in_transaction:
            conn.execute('BEGIN')

    def commit(self) -> None:
        self._conn().commit()

    def rollback(self) -> None:
        self._conn().rollback()

    # ── Maintenance ───────────────────────────────────────────────────────────

    def vacuum(self) -> None:
        """Rebuild the database file to reclaim free space (``VACUUM``).

        Commits any open transaction first (VACUUM cannot run inside one) and then
        drops this thread's connection, since the file is rebuilt in place and some
        ``sqlite3`` versions keep a stale cache afterwards.
        """
        # VACUUM must run outside an open transaction.
        conn = self._conn()
        conn.commit()
        conn.execute('VACUUM')
        # Reset connection after VACUUM — DB file is rebuilt in-place and
        # some sqlite3 versions exhibit stale-cache issues post-VACUUM.
        conn.close()
        self._local.conn = None

    def checkpoint(self) -> None:
        self._conn().execute('PRAGMA wal_checkpoint(PASSIVE)')

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
