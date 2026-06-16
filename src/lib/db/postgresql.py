#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PostgreSQL connector — uses ``psycopg2``.

psycopg2 uses ``%s`` as the positional placeholder, so all incoming ``?``
markers are replaced before execution.

Install: ``pip install psycopg2-binary``
"""

from __future__ import annotations

import threading

from lib.config.spec import cfg_default
from .base import BaseConnector
from .schema import ColumnInfo, IndexInfo

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
            'host':     cfg.get('host', cfg_default('database|host')),
            'port':     int(cfg.get('port', 5432)),  # driver-specific default
            'dbname':   cfg.get('name', cfg_default('database|name')),
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

    def list_columns(self, table: str) -> set[str]:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_name=%s',
                (table,),
            )
            return {row[0] for row in cur.fetchall()}

    def describe_table(self, table: str) -> list[ColumnInfo]:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT a.attname FROM pg_index i "
                'JOIN pg_attribute a '
                '  ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) '
                'WHERE i.indrelid = %s::regclass AND i.indisprimary',
                (table,),
            )
            pk_cols = {r[0] for r in cur.fetchall()}
            cur.execute(
                'SELECT column_name, data_type, is_nullable, column_default '
                'FROM information_schema.columns '
                'WHERE table_name=%s ORDER BY ordinal_position',
                (table,),
            )
            return [
                ColumnInfo(
                    name=r[0], type=r[1] or '',
                    nullable=(str(r[2]).upper() == 'YES'),
                    default=r[3], pk=(1 if r[0] in pk_cols else 0),
                )
                for r in cur.fetchall()
            ]

    def list_indexes(self, table: str) -> list[IndexInfo]:
        conn = self._conn()
        grouped: dict[str, list] = {}
        unique_flag: dict[str, bool] = {}
        with conn.cursor() as cur:
            cur.execute(
                'SELECT ic.relname, a.attname, ix.indisunique, k.ord '
                'FROM pg_index ix '
                'JOIN pg_class ic ON ic.oid = ix.indexrelid '
                'JOIN pg_class tc ON tc.oid = ix.indrelid '
                'JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord)'
                '  ON true '
                'JOIN pg_attribute a '
                '  ON a.attrelid = tc.oid AND a.attnum = k.attnum '
                'WHERE tc.relname = %s AND NOT ix.indisprimary '
                'ORDER BY ic.relname, k.ord',
                (table,),
            )
            for name, col, is_unique, _ord in cur.fetchall():
                grouped.setdefault(name, []).append(col)
                unique_flag[name] = bool(is_unique)
        return [
            IndexInfo(name=n, columns=tuple(cols), unique=unique_flag[n])
            for n, cols in grouped.items()
        ]

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
