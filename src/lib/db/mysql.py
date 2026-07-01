#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MySQL / MariaDB connector — uses ``PyMySQL``.

PyMySQL uses ``%s`` as the positional placeholder.

Install: ``pip install PyMySQL``
"""

from __future__ import annotations

import threading

from lib.config.spec import cfg_get
from .base import BaseConnector
from .schema import ColumnInfo, IndexInfo

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
    # MySQL/MariaDB can't index a TEXT/BLOB column without a prefix length, so a
    # TEXT column that is a key/index gets a bounded VARCHAR instead (utf8mb4
    # VARCHAR(255) = 1020 bytes, within InnoDB's index-prefix limit).
    DDL_TEXT_KEY      = 'VARCHAR(255)'

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
            'host':    cfg_get(cfg, 'database|host'),
            'port':    int(cfg.get('port', 3306)),  # driver-specific default
            'db':      cfg_get(cfg, 'database|name'),
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

    def list_columns(self, table: str) -> set[str]:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_schema=DATABASE() AND table_name=%s',
                (table,),
            )
            return {row[0] for row in cur.fetchall()}

    def describe_table(self, table: str) -> list[ColumnInfo]:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name, data_type, is_nullable, column_default, '
                'column_key FROM information_schema.columns '
                'WHERE table_schema=DATABASE() AND table_name=%s '
                'ORDER BY ordinal_position',
                (table,),
            )
            return [
                ColumnInfo(
                    name=r[0], type=r[1] or '',
                    nullable=(str(r[2]).upper() == 'YES'),
                    default=r[3], pk=(1 if r[4] == 'PRI' else 0),
                )
                for r in cur.fetchall()
            ]

    def list_indexes(self, table: str) -> list[IndexInfo]:
        conn = self._conn()
        grouped: dict[str, list] = {}
        unique_flag: dict[str, bool] = {}
        with conn.cursor() as cur:
            cur.execute(
                'SELECT index_name, seq_in_index, column_name, non_unique '
                'FROM information_schema.statistics '
                "WHERE table_schema=DATABASE() AND table_name=%s "
                "AND index_name <> 'PRIMARY' ORDER BY index_name, seq_in_index",
                (table,),
            )
            for name, _seq, col, non_unique in cur.fetchall():
                grouped.setdefault(name, []).append(col)
                unique_flag[name] = (non_unique == 0)
        return [
            IndexInfo(name=n, columns=tuple(cols), unique=unique_flag[n])
            for n, cols in grouped.items()
        ]

    def quote_ident(self, name: str) -> str:
        return f'`{name}`'

    def _drop_index(self, name: str, table: str) -> None:
        self.execute_ddl(f'DROP INDEX `{name}` ON `{table}`')

    # ── Read ──────────────────────────────────────────────────────────────────

    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        self._trace_sql(sql)
        with self._conn().cursor() as cur:
            cur.execute(self._adapt_sql(sql), params)
            return cur.fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        self._trace_sql(sql)
        with self._conn().cursor() as cur:
            cur.execute(self._adapt_sql(sql), params)
            return cur.fetchone()

    # ── Write ─────────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> int:
        self._trace_sql(sql)
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(self._adapt_sql(sql), params)
            return cur.rowcount

    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        self._trace_sql(sql)
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
