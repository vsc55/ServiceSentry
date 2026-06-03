#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PostgreSQL connector — uses ``psycopg2``.

psycopg2 uses ``%s`` as the positional placeholder, so all incoming ``?``
markers are replaced before execution.

Install: ``pip install psycopg2-binary``
"""

from __future__ import annotations

import threading

from .base import BaseConnector

try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:  # pragma: no cover
    _HAS_PSYCOPG2 = False


class PostgreSQLConnector(BaseConnector):
    """Thread-safe PostgreSQL connector via psycopg2."""

    DDL_AUTOINCREMENT = 'SERIAL PRIMARY KEY'
    DDL_REAL          = 'DOUBLE PRECISION'
    DDL_TEXT          = 'TEXT'
    DDL_INTEGER       = 'INTEGER'

    def __init__(self, config: dict) -> None:
        if not _HAS_PSYCOPG2:
            raise RuntimeError(
                'psycopg2 is required for PostgreSQL support. '
                'Install it with: pip install psycopg2-binary'
            )
        self._config = config
        self._local  = threading.local()
        # Verify connectivity on init
        self._conn()

    def _dsn(self) -> dict:
        cfg = self._config
        return {
            'host':     cfg.get('host', 'localhost'),
            'port':     int(cfg.get('port', 5432)),
            'dbname':   cfg.get('name', 'servicesentry'),
            'user':     cfg.get('user', ''),
            'password': cfg.get('password', ''),
        }

    def _conn(self):
        conn = getattr(self._local, 'conn', None)
        if conn is None or conn.closed:
            conn = psycopg2.connect(**self._dsn())
            conn.autocommit = False
            self._local.conn = conn
        return conn

    def _adapt_sql(self, sql: str) -> str:
        return sql.replace('?', '%s')

    # ── Schema ────────────────────────────────────────────────────────────────

    def execute_ddl(self, ddl: str) -> None:
        conn = self._conn()
        with conn.cursor() as cur:
            for stmt in ddl.split(';'):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
        conn.commit()

    def add_column_if_missing(
        self, table: str, column: str, col_type: str
    ) -> None:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_name=%s AND column_name=%s',
                (table, column),
            )
            if not cur.fetchone():
                cur.execute(
                    f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'
                )
        conn.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._conn().cursor() as cur:
            cur.execute(self._adapt_sql(sql), params)
            return cur.fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        with self._conn().cursor() as cur:
            cur.execute(self._adapt_sql(sql), params)
            return cur.fetchone()

    # ── Write ─────────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> int:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(self._adapt_sql(sql), params)
            return cur.rowcount

    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        conn = self._conn()
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, self._adapt_sql(sql), params_list)
            return cur.rowcount

    def commit(self) -> None:
        self._conn().commit()

    def rollback(self) -> None:
        self._conn().rollback()

    # ── Maintenance ───────────────────────────────────────────────────────────

    def vacuum(self) -> None:
        conn = self._conn()
        old_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute('VACUUM ANALYZE')
        finally:
            conn.autocommit = old_autocommit

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        conn = getattr(self._local, 'conn', None)
        if conn and not conn.closed:
            conn.close()
            self._local.conn = None
