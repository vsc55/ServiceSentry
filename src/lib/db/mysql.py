#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MySQL / MariaDB connector — uses ``PyMySQL``.

PyMySQL uses ``%s`` as the positional placeholder.

Install: ``pip install PyMySQL``
"""

from __future__ import annotations

import threading

from .base import BaseConnector

try:
    import pymysql
    import pymysql.cursors
    _HAS_PYMYSQL = True
except ImportError:  # pragma: no cover
    _HAS_PYMYSQL = False


class MySQLConnector(BaseConnector):
    """Thread-safe MySQL/MariaDB connector via PyMySQL."""

    DDL_AUTOINCREMENT = 'INT AUTO_INCREMENT PRIMARY KEY'
    DDL_REAL          = 'DOUBLE'
    DDL_TEXT          = 'TEXT'
    DDL_INTEGER       = 'INT'

    def __init__(self, config: dict) -> None:
        if not _HAS_PYMYSQL:
            raise RuntimeError(
                'PyMySQL is required for MySQL/MariaDB support. '
                'Install it with: pip install PyMySQL'
            )
        self._config = config
        self._local  = threading.local()
        self._conn()

    def _connect_kwargs(self) -> dict:
        cfg = self._config
        return {
            'host':    cfg.get('host', 'localhost'),
            'port':    int(cfg.get('port', 3306)),
            'db':      cfg.get('name', 'servicesentry'),
            'user':    cfg.get('user', ''),
            'password': cfg.get('password', ''),
            'charset': 'utf8mb4',
            'autocommit': False,
        }

    def _conn(self):
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = pymysql.connect(**self._connect_kwargs())
            self._local.conn = conn
        else:
            try:
                conn.ping(reconnect=True)
            except Exception:  # pylint: disable=broad-except
                conn = pymysql.connect(**self._connect_kwargs())
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
                'SELECT COUNT(*) FROM information_schema.columns '
                'WHERE table_schema=DATABASE() '
                'AND table_name=%s AND column_name=%s',
                (table, column),
            )
            if cur.fetchone()[0] == 0:
                cur.execute(
                    f'ALTER TABLE `{table}` ADD COLUMN `{column}` {col_type}'
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
            cur.executemany(self._adapt_sql(sql), params_list)
            return cur.rowcount

    def commit(self) -> None:
        self._conn().commit()

    def rollback(self) -> None:
        self._conn().rollback()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
