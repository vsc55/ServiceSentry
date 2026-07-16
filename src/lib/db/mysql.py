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
    from pymysql.constants import CLIENT as _PYMYSQL_CLIENT
    _HAS_PYMYSQL = True
except ImportError:  # pragma: no cover
    _HAS_PYMYSQL = False


class MySQLConnector(BaseConnector):
    """Thread-safe MySQL/MariaDB connector via PyMySQL."""

    KIND              = 'mysql'
    DDL_AUTOINCREMENT = 'INT AUTO_INCREMENT PRIMARY KEY'
    DDL_REAL          = 'DOUBLE'
    DDL_TEXT          = 'TEXT'
    DDL_INTEGER       = 'INT'
    NEEDS_THREAD_CLEANUP = True    # per-thread network connection → close on thread exit
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
            # Report MATCHED rows (not just CHANGED) from UPDATE, matching SQLite/PostgreSQL —
            # so the "UPDATE; if rowcount == 0: INSERT" upsert pattern (event cursor/cooldowns)
            # doesn't wrongly INSERT (→ UNIQUE violation) when re-writing an unchanged value.
            'client_flag': _PYMYSQL_CLIENT.FOUND_ROWS,
            # InnoDB defaults to REPEATABLE READ: a long-lived read-only connection
            # (e.g. a service's config-watch thread) pins its snapshot at the first
            # SELECT and never sees another process's committed writes — so a config
            # change made in the web pod is invisible to the worker/syslog/events
            # pods until they reconnect (it made an external syslog start flip back to
            # stopped). This control plane shares one DB across processes, so every
            # reader must see the latest committed state: use READ COMMITTED.
            # NB: use the standard statement form (not the ``transaction_isolation`` system
            # variable) — it works on both MySQL 5.7/8 AND MariaDB 10.x (whose variable is
            # ``tx_isolation`` until 11.1). String concatenation portability (``||`` vs
            # ``CONCAT``) is handled per-dialect in the queries that need it (see
            # history.get_index), NOT by flipping sql_mode here.
            'init_command': 'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED',
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

    def _apply_rebuild(self, spec, actual_cols, actual_indexes) -> None:
        """Atomic table rebuild for MySQL/MariaDB, where DDL auto-commits (so the base's
        drop-then-rename inside a transaction is NOT atomic and could lose data if it fails
        mid-way).  Build the populated replacement, then swap it in with a single
        ``RENAME TABLE old→backup, new→old`` (MySQL guarantees the multi-table rename is
        atomic); the original stays intact as a backup until the swap succeeds, then is dropped.
        """
        from .schema import create_table_ddl  # noqa: PLC0415
        q = self.quote_ident
        tmp, extras, collist, select_list, has_common = self._rebuild_copy_plan(spec, actual_cols)
        bak = f'__ssbak_{spec.name}'
        self.execute_ddl(f'DROP TABLE IF EXISTS {q(tmp)}')
        self.execute_ddl(f'DROP TABLE IF EXISTS {q(bak)}')
        self.execute(create_table_ddl(spec, self._type_map, q, name=tmp, extra_columns=extras))
        if has_common:
            self.execute(f'INSERT INTO {q(tmp)} ({collist}) '
                         f'SELECT {select_list} FROM {q(spec.name)}')
        self.commit()
        # Atomic swap — if anything above failed, the original table is untouched.
        self.execute_ddl(f'RENAME TABLE {q(spec.name)} TO {q(bak)}, {q(tmp)} TO {q(spec.name)}')
        self._recreate_indexes_after_rebuild(spec, actual_indexes)
        self.execute_ddl(f'DROP TABLE IF EXISTS {q(bak)}')

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
        """Introspect *table*'s columns from ``information_schema.columns`` (current
        database), ordered by ``ordinal_position``; PK columns are flagged from
        ``column_key = 'PRI'``."""
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
        """List *table*'s secondary indexes from ``information_schema.statistics``
        (current database), grouping multi-column indexes by name in
        ``seq_in_index`` order. The implicit ``PRIMARY`` index is excluded."""
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
