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


class SQLiteConnector(BaseConnector):
    """Thread-safe SQLite connector backed by ``threading.local``."""

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

    # ── Read ──────────────────────────────────────────────────────────────────

    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self._conn().execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        return self._conn().execute(sql, params).fetchone()

    # ── Write ─────────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> int:
        cur = self._conn().execute(sql, params)
        return cur.rowcount

    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        cur = self._conn().executemany(sql, params_list)
        return cur.rowcount

    def commit(self) -> None:
        self._conn().commit()

    def rollback(self) -> None:
        self._conn().rollback()

    # ── Maintenance ───────────────────────────────────────────────────────────

    def vacuum(self) -> None:
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
