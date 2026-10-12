#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PostgreSQL connector — uses ``psycopg2``.

psycopg2 uses ``%s`` as the positional placeholder, so all incoming ``?``
markers are replaced before execution.

Install: ``pip install psycopg2-binary``
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from lib.config.spec import cfg_get
from .base import BaseConnector
from .schema import ColumnInfo, IndexInfo, SchemaDiff, TableSpec, fold_spec

try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:  # pragma: no cover
    _HAS_PSYCOPG2 = False


_log = logging.getLogger(__name__)


class PostgreSQLConnector(BaseConnector):
    """Thread-safe PostgreSQL connector via psycopg2."""

    KIND              = 'postgresql'
    DDL_AUTOINCREMENT = 'SERIAL PRIMARY KEY'
    DDL_REAL          = 'DOUBLE PRECISION'
    DDL_TEXT          = 'TEXT'
    DDL_INTEGER       = 'INTEGER'
    DDL_DATETIME      = 'TIMESTAMP'
    NEEDS_THREAD_CLEANUP = True    # per-thread network connection → close on thread exit

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
        dsn = {
            'host':     cfg_get(cfg, 'database|host'),
            'port':     int(cfg.get('port', 5432)),  # driver-specific default
            'dbname':   cfg_get(cfg, 'database|name'),
            'user':     cfg.get('user', ''),
            'password': cfg.get('password', ''),
        }
        # Optional bounds, in seconds — set for a database the panel only visits (an external
        # syslog source). `read_timeout` becomes the server-side statement_timeout, the
        # nearest thing PostgreSQL has. Absent: the driver's defaults.
        try:
            connect = int(cfg.get('connect_timeout') or 0)
            read = int(cfg.get('read_timeout') or 0)
        except (TypeError, ValueError):
            connect = read = 0
        if connect > 0:
            dsn['connect_timeout'] = connect
        if read > 0:
            dsn['options'] = f'-c statement_timeout={read * 1000}'
        return dsn

    def _conn(self):
        conn = getattr(self._local, 'conn', None)
        if conn is None or conn.closed:
            conn = psycopg2.connect(**self._dsn())
            # Autocommit only for a database the panel only reads (see MySQLConnector): an idle
            # transaction there holds a lock its owner's DDL would wait on.
            conn.autocommit = bool(self._config.get('autocommit'))
            self._local.conn = conn
            self._settled()
        return conn

    def _adapt_sql(self, sql: str) -> str:
        return sql.replace('?', '%s')

    # ── Identifier case ───────────────────────────────────────────────────────
    # PostgreSQL folds an unquoted name to lower case, and everything that writes to a table
    # this panel shares with another program writes unquoted: rsyslog's `INSERT INTO
    # SystemEvents (ReceivedAt, …)` lands in `systemevents (receivedat, …)`. A spec spelled the
    # way that program spells it (`SystemEvents`) has to name the same table here, so every
    # identifier this connector quotes or looks up is folded first — which changes nothing for
    # the panel's own tables, all of them lower case already.

    @staticmethod
    def _fold(name: str) -> str:
        return str(name).lower()

    def quote_ident(self, name: str) -> str:
        return f'"{str(name).lower()}"'

    def reconcile_table(self, spec: TableSpec) -> SchemaDiff:
        return super().reconcile_table(fold_spec(spec))

    # ── Schema ────────────────────────────────────────────────────────────────

    def execute_ddl(self, ddl: str) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                for stmt in ddl.split(';'):
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)
        except psycopg2.Error:
            self._failed(conn)
            raise
        conn.commit()
        # The commit ended whatever was pending; left flagged, the next read would not.
        self._settled()

    def add_column_if_missing(
        self, table: str, column: str, col_type: str
    ) -> None:
        table, column = self._fold(table), self._fold(column)
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_name=%s AND column_name=%s AND table_schema=current_schema()',
                (table, column),
            )
            if not cur.fetchone():
                try:
                    cur.execute(
                        f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'
                    )
                except psycopg2.Error as exc:
                    # The failed ALTER aborted the transaction: roll it back either way, or
                    # the next statement on this thread fails with InFailedSqlTransaction.
                    self._failed(conn)
                    if self._is_duplicate_object(exc):
                        return      # another process added it between the check and here
                    raise
        conn.commit()

    def _is_duplicate_object(self, exc: Exception) -> bool:
        # 42701 duplicate_column, 42P07 duplicate_table (an index is a relation).
        return getattr(exc, 'pgcode', None) in ('42701', '42P07')

    @contextmanager
    def _reconcile_lock(self, table: str):
        """A session advisory lock keyed by the table: it outlives the commits the DDL makes,
        and a second process reconciling the same table waits here, then reads it done."""
        key = f'ss_reconcile:{self._fold(table)}'
        got = False
        try:
            self.fetchone('SELECT pg_advisory_lock(hashtext(?))', (key,))
            got = True
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning('reconcile %s: advisory lock failed (%s) — going ahead unlocked',
                         table, exc)
        try:
            yield
        finally:
            if got:
                try:
                    self._failed(self._conn())      # a failed reconcile left it aborted
                    self.fetchone('SELECT pg_advisory_unlock(hashtext(?))', (key,))
                except Exception as exc:  # pylint: disable=broad-except
                    _log.warning('reconcile %s: advisory unlock failed: %s', table, exc)

    def list_columns(self, table: str) -> set[str]:
        table = self._fold(table)
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_name=%s AND table_schema=current_schema()',
                (table,),
            )
            return {row[0] for row in cur.fetchall()}

    def describe_table(self, table: str) -> list[ColumnInfo]:
        """Introspect *table*'s columns from ``information_schema.columns`` (current
        schema), ordered by ``ordinal_position``. PK membership is resolved
        separately from ``pg_index``/``pg_attribute`` and flagged on each column."""
        table = self._fold(table)
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
                'WHERE table_name=%s AND table_schema=current_schema() '
                'ORDER BY ordinal_position',
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
        """List *table*'s secondary indexes from the ``pg_index``/``pg_class``/
        ``pg_attribute`` catalogs (current schema), preserving column order via the
        unnested ``indkey`` ordinality. Primary-key indexes are excluded."""
        table = self._fold(table)
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
                # Nor the index behind a UNIQUE constraint: it belongs to the table's DDL, and
                # a rebuild that took it for a manual one recreated it beside the constraint
                # the new table already had — one more duplicate unique index per rebuild.
                'AND NOT EXISTS (SELECT 1 FROM pg_constraint c '
                "  WHERE c.conindid = ix.indexrelid AND c.conrelid = ix.indrelid "
                "  AND c.contype IN ('p', 'u', 'x')) "
                'AND tc.relnamespace = current_schema()::regnamespace '
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

    def sync_autoincrement(self, table: str) -> None:
        """Set every serial/identity sequence of *table* to MAX(column) + 1.

        PostgreSQL hands out ids from a sequence that only ``nextval`` moves; a row inserted
        WITH its id (a rebuild copying the old table, a restore refilling it) leaves it where
        it was. The sequence of a freshly rebuilt table is at 1, so the next plain INSERT on
        `audit`, `history`, `history_series`… collided with a row already there — and the
        stores that swallow write errors lost every new row from then on, silently.

        The columns are found in the catalog, not passed in: a restore knows only the table
        name, and the catalog is what actually owns a sequence.
        """
        q = self.quote_ident
        table = self._fold(table)
        cols = self.fetchall(
            'SELECT column_name FROM information_schema.columns '
            'WHERE table_name = ? AND table_schema = current_schema() '
            "AND (column_default LIKE ? OR is_identity = 'YES')",
            (table, 'nextval(%'))
        for (col,) in cols:
            seq = self.fetchone('SELECT pg_get_serial_sequence(?, ?)', (q(table), col))
            seq = seq[0] if seq else None
            if not seq:
                continue
            top = self.fetchone(f'SELECT COALESCE(MAX({q(col)}), 0) FROM {q(table)}')
            nxt = int((top[0] if top else 0) or 0) + 1
            # Never BACKWARDS. A restore that refills `audit` or the syslog tables with an
            # older copy has a lower maximum than the ids already handed out; pulling the
            # sequence down to it gave the next rows ids the events worker had already passed
            # (and still remembered as evaluated), so no rule saw them. SQLite's AUTOINCREMENT
            # and InnoDB's counter keep their high-water mark the same way. A rebuilt table's
            # fresh sequence is unused (`is_called` false), so there MAX + 1 still wins.
            # `seq` comes from the catalog already quoted and schema-qualified.
            cur = self.fetchone(f'SELECT last_value, is_called FROM {seq}')
            if cur and cur[1]:
                nxt = max(nxt, int(cur[0] or 0) + 1)
            self.fetchone('SELECT setval(CAST(? AS regclass), ?, false)', (seq, nxt))

    # ── Read ──────────────────────────────────────────────────────────────────


    # ── Transaction state ─────────────────────────────────────────────────────
    #
    # The driver opens a transaction at the first statement and keeps it until a commit. A
    # thread that only READS —a service's config watch, a polling loop— never committed, so
    # it held its table locks (PostgreSQL's AccessShareLock, MySQL's metadata lock) forever,
    # and an upgrade's ALTER on that table waited for ever behind them, with every later query
    # queued behind the ALTER. So a read that is not inside `begin()` and follows no
    # uncommitted write ends its transaction at once — what SQLite, in autocommit, always did.

    def _tx(self):
        loc = self._local
        if not hasattr(loc, 'pending'):
            loc.pending = loc.explicit = False
        return loc

    def begin(self) -> None:
        self._tx().explicit = True

    def _settled(self) -> None:
        loc = self._tx()
        loc.pending = loc.explicit = False

    def _end_read(self, conn) -> None:
        loc = self._tx()
        if not loc.pending and not loc.explicit and not self._config.get('autocommit'):
            conn.commit()

    def _failed(self, conn) -> None:
        """A failed statement aborts PostgreSQL's transaction, and every later one on this
        connection fails (`InFailedSqlTransaction`) until a rollback. The callers that swallow
        an expected error —two processes inserting the same counter row on first boot, a
        series created by two threads at once— never rolled back, and that thread's
        connection was dead from then on. Outside `begin()` it is rolled back here; inside,
        `transaction()` does it."""
        if not self._tx().explicit:
            try:
                conn.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
            self._settled()

    def _run(self, sql, params, how):
        self._trace_sql(sql)
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(self._adapt_sql(sql), params)
                out = how(cur)
        except psycopg2.Error:
            self._failed(conn)
            raise
        return conn, out

    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        conn, rows = self._run(sql, params, lambda cur: cur.fetchall())
        self._end_read(conn)
        return rows

    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        conn, row = self._run(sql, params, lambda cur: cur.fetchone())
        self._end_read(conn)
        return row

    def iter_query(self, sql: str, params: tuple = (), size: int = 5000):
        """Stream a SELECT through a server-side (named) cursor: psycopg2's default cursor
        transfers the whole result to the client on `execute`."""
        import uuid  # noqa: PLC0415
        self._trace_sql(sql)
        conn = self._conn()
        if conn.autocommit:            # a named cursor needs a transaction to live in
            yield from super().iter_query(sql, params, size)
            return
        cur = conn.cursor(name=f'ss_iter_{uuid.uuid4().hex[:12]}')
        cur.itersize = max(1, int(size))
        try:
            cur.execute(self._adapt_sql(sql), params)
            while True:
                rows = cur.fetchmany(max(1, int(size)))
                if not rows:
                    break
                yield rows
        except psycopg2.Error:
            self._failed(conn)
            raise
        finally:
            try:
                cur.close()
            except Exception:  # pylint: disable=broad-except
                pass
        self._end_read(conn)

    # ── Write ─────────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> int:
        _, n = self._run(sql, params, lambda cur: cur.rowcount)
        self._tx().pending = True
        return n

    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        self._trace_sql(sql)
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, self._adapt_sql(sql), params_list)
                n = cur.rowcount
        except psycopg2.Error:
            self._failed(conn)
            raise
        self._tx().pending = True
        return n

    def _lock_for_rebuild(self, table: str) -> None:
        """A rebuild copies the table with INSERT…SELECT, then drops it: under READ COMMITTED a
        row another session committed after the copy's snapshot was in neither, and the
        rebuild lost it. ACCESS EXCLUSIVE from the start of the transaction makes readers and
        writers of that table wait until the swapped-in table commits — accepted: a rebuild
        is a schema migration, and waiting is better than a lost row."""
        self.execute(f'LOCK TABLE {self.quote_ident(table)} IN ACCESS EXCLUSIVE MODE')

    def _execute_optional(self, sql: str) -> bool:
        """Inside a transaction a failed statement aborts it here (`InFailedSqlTransaction`
        on every statement after it), so the tolerated failure is fenced by a SAVEPOINT and
        rolled back to it — the rest of the transaction carries on. Outside one, `_failed`
        already rolls the lone statement back."""
        if not self._tx().explicit:
            return super()._execute_optional(sql)
        self.execute('SAVEPOINT ss_optional')
        try:
            self.execute(sql)
        except Exception:  # pylint: disable=broad-except
            self.execute('ROLLBACK TO SAVEPOINT ss_optional')
            return False
        self.execute('RELEASE SAVEPOINT ss_optional')
        return True

    def commit(self) -> None:
        self._conn().commit()
        self._settled()

    def rollback(self) -> None:
        self._conn().rollback()
        self._settled()

    # ── Maintenance ───────────────────────────────────────────────────────────

    def vacuum(self) -> None:
        """Run ``VACUUM ANALYZE`` to reclaim space and refresh planner statistics.

        VACUUM cannot run inside a transaction block, so autocommit is toggled on for
        the call and restored afterwards.
        """
        self._outside_transaction('VACUUM ANALYZE')

    def maintenance_targets(self, op: str) -> list[str]:
        """Both statements take an optional table here, so both can report per-table progress.

        It matters more for VACUUM FULL than for ANALYZE: the lock is held per table rather
        than across the whole run, so naming them one at a time also shortens how long any
        single table is unavailable.
        """
        return self.list_tables()

    def compact(self, table: str | None = None) -> None:
        """``VACUUM FULL`` — the only form that returns space to the filesystem.

        Plain ``VACUUM`` marks space reusable INSIDE the file; the file itself never shrinks.
        So this is the one an admin means by "compact", and it is also the one that takes an
        ACCESS EXCLUSIVE lock on every table it rewrites — readers included. That is why it is
        an explicit action behind a warning and never the automatic post-delete step.
        """
        self._outside_transaction(
            f'VACUUM FULL {self.quote_ident(table)}' if table else 'VACUUM FULL')

    def optimize(self, table: str | None = None) -> None:
        """``ANALYZE`` — refresh planner statistics without touching storage."""
        self._outside_transaction(
            f'ANALYZE {self.quote_ident(table)}' if table else 'ANALYZE')

    def list_tables(self) -> list[str]:
        rows = self.fetchall(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
            "ORDER BY tablename")
        return [r[0] for r in rows]

    def _outside_transaction(self, sql: str) -> None:
        """Run *sql* with autocommit on, restoring it afterwards.

        VACUUM and ANALYZE cannot run inside a transaction block, and this connector keeps one
        open. Shared so the three maintenance statements cannot drift on the one detail that
        makes them work at all.

        Turning autocommit on is not enough by itself: psycopg2 refuses the flip while a
        transaction is open ("set_session cannot be used inside a transaction"), and one is
        always open — the driver starts it on the first read. So the transaction is ended
        first. **Committed, not rolled back**: what is open here is the read that preceded the
        request, and throwing away a caller's pending work in order to run maintenance would
        be a worse surprise than keeping it. Maintenance is an explicit admin action, never
        something that fires mid-write.

        Every maintenance call on PostgreSQL raised without this — proven only by running it
        against a real server, since the statement itself is valid and the failure lives in
        the driver.
        """
        conn = self._conn()
        try:
            conn.commit()          # no-op when nothing is open
        except Exception:          # pylint: disable=broad-except
            pass
        self._settled()
        old_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
        finally:
            conn.autocommit = old_autocommit

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        conn = getattr(self._local, 'conn', None)
        if conn and not conn.closed:
            conn.close()
            self._local.conn = None
