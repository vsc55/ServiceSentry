#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MySQL / MariaDB connector — uses ``PyMySQL``.

PyMySQL uses ``%s`` as the positional placeholder.

Install: ``pip install PyMySQL``
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from contextlib import contextmanager
from dataclasses import replace

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


_log = logging.getLogger(__name__)


def _timeouts(cfg: dict) -> dict:
    out = {}
    for key in ('connect_timeout', 'read_timeout'):
        try:
            v = int(cfg.get(key) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            out[key] = v
    return out


class MySQLConnector(BaseConnector):
    """Thread-safe MySQL/MariaDB connector via PyMySQL."""

    KIND              = 'mysql'
    #: Seconds a reconcile waits for another process reconciling the same table (a rebuild of
    #: a big table can take minutes; past this it goes ahead and tolerates a duplicate).
    RECONCILE_LOCK_WAIT = 300
    DDL_AUTOINCREMENT = 'INT AUTO_INCREMENT PRIMARY KEY'
    DDL_REAL          = 'DOUBLE'
    # LONGTEXT, not TEXT: MySQL's TEXT holds 64 KB, and the panel keeps more than that in a
    # text column — an HTML email template with its logo in `config.value`, a config diff in
    # `audit.detail`, ten thousand log lines in `job_history.log`. In strict mode the write
    # failed (the audit row lost, the job left `running`); otherwise it was cut short.
    DDL_TEXT          = 'LONGTEXT'
    DDL_INTEGER       = 'INT'
    DDL_DATETIME      = 'DATETIME'
    NEEDS_THREAD_CLEANUP = True    # per-thread network connection → close on thread exit
    # MySQL/MariaDB can't index a TEXT/BLOB column without a prefix length, so a
    # TEXT column that is a key/index gets a bounded VARCHAR instead (utf8mb4
    # VARCHAR(255) = 1020 bytes, within InnoDB's index-prefix limit).
    #
    # And binary-collated. The server's default collation (`utf8mb4_general_ci`,
    # `utf8mb4_0900_ai_ci`, `uca1400_ai_ci` on MariaDB 11) is case- AND accent-insensitive, so a
    # key compared under it merges what every other engine keeps apart: a history field `Rx`
    # and its sibling `rx` became one (the second sample lost every cycle), the series
    # `Intranet` and `intranet` one series. `utf8mb4_bin` compares bytes, as SQLite and
    # PostgreSQL do. It costs no index length (the bytes per character do not change).
    DDL_TEXT_KEY      = 'VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin'
    KEY_COLLATION     = 'utf8mb4_bin'
    # MySQL/MariaDB reject ``TEXT NOT NULL DEFAULT ''`` — a default on a TEXT/BLOB/JSON
    # column is only accepted as an expression (``DEFAULT ('')``, MySQL 8.0.13+ /
    # MariaDB 10.2+). Without this every table declaring one fails to CREATE.
    DDL_TEXT_DEFAULT_PARENS = True

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
            # `autocommit` is for a database the panel only READS (an external syslog source):
            # without it every SELECT leaves a transaction open, and on MySQL an open
            # transaction holds a metadata lock on the table it read — the owner's next ALTER or
            # DROP (an index the DBA adds) waits on the panel's idle connection for ever.
            'autocommit': bool(cfg.get('autocommit')),
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
            # Optional bounds, in seconds — set for a database the panel only visits (an
            # external syslog source), where an unreachable server must cost a request a few
            # seconds, not the driver's indefinite wait. Absent: the driver's defaults.
            **_timeouts(cfg),
        }

    def _conn(self):
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = pymysql.connect(**self._connect_kwargs())
            self._local.conn = conn
            self._settled()
            return conn
        loc = self._tx()
        if loc.pending or loc.explicit:
            # Mid-transaction: NO ping, and above all no silent reconnect. `ping(reconnect=True)`
            # on a connection the server dropped opened a fresh one: the statements before the
            # drop were gone with the old session, the ones after it went on, and the caller's
            # `commit()` committed half a transaction as if it were whole. A dead connection
            # here has to fail the statement, which the caller's rollback handles.
            return conn
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
        if extras:
            defs = self._column_definitions(spec.name)
            extras = [replace(c, definition=defs.get(c.name) or c.definition) for c in extras]
        bak = f'__ssbak_{spec.name}'
        self.execute_ddl(f'DROP TABLE IF EXISTS {q(tmp)}')
        self.execute_ddl(f'DROP TABLE IF EXISTS {q(bak)}')
        self.execute(create_table_ddl(spec, self._type_map, q, name=tmp, extra_columns=extras,
                                      text_default_parens=self.DDL_TEXT_DEFAULT_PARENS))
        before_swap = after_swap = None
        if has_common:
            self.execute(f'INSERT INTO {q(tmp)} ({collist}) '
                         f'SELECT {select_list} FROM {q(spec.name)}')
            plan = (spec, actual_cols, collist, select_list)
            before_swap = self._rebuild_catch_up_sql(*plan, src=spec.name, dst=tmp, ignore=False)
            after_swap = self._rebuild_catch_up_sql(*plan, src=bak, dst=spec.name, ignore=True)
        self.commit()
        # Rows other sessions wrote to the old table while it was being copied are in neither
        # the copy nor — after the swap — the live table: the rebuild lost them. PostgreSQL
        # locks the table for the whole copy; here that is not available (`RENAME TABLE` is
        # refused under `LOCK TABLES`, error 1192), so the late rows are copied across by
        # primary key instead, in two passes:
        #   1. before the swap, old → copy: catches everything written during the long copy;
        #      a failure here leaves the original untouched, as any failure before the swap.
        #   2. after the swap, backup → live: catches what landed in the short gap between
        #      pass 1 and the RENAME. IGNORE, because the swap has happened and the backup is
        #      about to go — a row that cannot be placed must not abort what is left.
        # Limits, by design: only INSERTs are recovered (an UPDATE or DELETE made to a row
        # already copied is not replayed), only on tables with a primary key, and a late row
        # whose id was meanwhile handed to a new INSERT on the live table (possible only in
        # the gap between the swap and pass 2) loses to it.
        if before_swap:
            self.execute(before_swap)
            self.commit()
        # Atomic swap — if anything above failed, the original table is untouched.
        self.execute_ddl(f'RENAME TABLE {q(spec.name)} TO {q(bak)}, {q(tmp)} TO {q(spec.name)}')
        if after_swap:
            self.execute(after_swap)
            self.commit()
        self._recreate_indexes_after_rebuild(spec, actual_indexes)
        self.execute_ddl(f'DROP TABLE IF EXISTS {q(bak)}')

    # One column line of `SHOW CREATE TABLE`: "  `name` varchar(60) DEFAULT NULL,".
    _CREATE_COL = re.compile(r'^\s*`((?:[^`]|``)+)`\s+(.+?),?\s*$')

    def _column_definitions(self, table: str) -> dict[str, str]:
        """``{column: definition}`` exactly as the engine prints them in ``SHOW CREATE TABLE``.

        What a rebuild recreates a column the spec does not declare from. `information_schema`
        cannot give it back whole: `data_type` is `varchar` without its length (MySQL refuses
        it — error 1064, and a table rsyslog created could never be rebuilt), and MySQL 8
        reports an expression default as `_utf8mb4\'x\'`, which is not SQL. The engine's own
        rendering carries the length, `unsigned`, the charset and collation and a default
        quoted the way the same engine reads it back. Empty when the statement cannot be read
        (the caller falls back to `column_type`, without the default)."""
        try:
            row = self.fetchone(f'SHOW CREATE TABLE {self.quote_ident(table)}')
        except Exception:  # pylint: disable=broad-except
            return {}
        out = {}
        for line in str(row[1] if row else '').splitlines()[1:]:
            m = self._CREATE_COL.match(line)
            if m:
                out[m.group(1).replace('``', '`')] = m.group(2)
        return out

    def _rebuild_catch_up_sql(self, spec, actual_cols, collist, select_list, *,
                              src: str, dst: str, ignore: bool) -> str | None:
        """``INSERT [IGNORE] INTO dst (cols) SELECT … FROM src`` of the rows *src* has and
        *dst* lacks, matched by primary key — both passes of :meth:`_apply_rebuild`.  ``None``
        when there is no key to match on: a table without a primary key, or one whose key
        columns the old table does not have yet."""
        q = self.quote_ident
        pk = list(spec.composite_pk) or [c.name for c in spec.columns if c.primary_key]
        old = {c.name for c in actual_cols}
        if not pk or any(c not in old for c in pk):
            return None
        match = ' AND '.join(f'd.{q(c)} = s.{q(c)}' for c in pk)
        return (f'INSERT {"IGNORE " if ignore else ""}INTO {q(dst)} ({collist}) '
                f'SELECT {select_list} FROM {q(src)} AS s '
                f'WHERE NOT EXISTS (SELECT 1 FROM {q(dst)} AS d WHERE {match})')

    # ── Schema ────────────────────────────────────────────────────────────────

    def execute_ddl(self, ddl: str) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                for stmt in ddl.split(';'):
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)
        except pymysql.Error:
            self._failed(conn)
            raise
        conn.commit()
        # DDL commits implicitly, and so did this: whatever was pending is settled. Left
        # flagged, the next read would never end its transaction.
        self._settled()

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
                try:
                    cur.execute(
                        f'ALTER TABLE `{table}` ADD COLUMN `{column}` {col_type}'
                    )
                except pymysql.MySQLError as exc:
                    # Another process added it between the check and the ALTER: done.
                    if not self._is_duplicate_object(exc):
                        raise
        conn.commit()

    def _is_duplicate_object(self, exc: Exception) -> bool:
        # 1060 duplicate column, 1061 duplicate key name.
        return bool(getattr(exc, 'args', None)) and exc.args[0] in (1060, 1061)

    @contextmanager
    def _reconcile_lock(self, table: str):
        """`GET_LOCK` — a named lock of the session, untouched by the DDL's implicit commits.
        The name is hashed: MySQL caps it at 64 characters."""
        name = 'ss_reconcile_' + hashlib.md5(str(table).encode('utf-8')).hexdigest()
        got = False
        try:
            row = self.fetchone('SELECT GET_LOCK(?, ?)', (name, self.RECONCILE_LOCK_WAIT))
            got = bool(row and row[0] == 1)
            if not got:
                _log.warning('reconcile %s: lock not obtained in %ss — going ahead; a '
                             'concurrent duplicate is tolerated', table, self.RECONCILE_LOCK_WAIT)
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning('reconcile %s: GET_LOCK failed (%s) — going ahead unlocked', table, exc)
        try:
            yield
        finally:
            if got:
                try:
                    self.fetchone('SELECT RELEASE_LOCK(?)', (name,))
                except Exception as exc:  # pylint: disable=broad-except
                    _log.warning('reconcile %s: RELEASE_LOCK failed: %s', table, exc)

    def list_columns(self, table: str) -> set[str]:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_schema=DATABASE() AND table_name=%s',
                (table,),
            )
            return {row[0] for row in cur.fetchall()}

    def _reconcile(self, spec):
        diff = super()._reconcile(spec)
        self._widen_text(spec)
        self._bin_keys(spec)
        return diff

    def _bin_keys(self, spec) -> None:
        """Give the text columns a UNIQUE key or the primary key covers a binary collation.

        A table created before `DDL_TEXT_KEY` carried `COLLATE utf8mb4_bin` keeps the server's
        case/accent-insensitive collation, and the diff compares types, not collations — so
        nothing else would ever fix it. Only unique and primary keys: those are where the
        collation merges two rows into one. A plain index (rsyslog's `FromHost`) is left as it
        is; changing it would rebuild somebody else's table for no lost row.

        Cost: `MODIFY COLUMN` with a new collation on an indexed column copies the table (once
        — the next boot finds it binary). The length is kept from the live column, so the
        index stays within InnoDB's 3072-byte limit exactly as before. A refusal (an old
        COMPACT row format, a duplicate that only differed in case cannot exist under a
        unique key) is logged and the boot carries on with the table as it was.
        """
        from .schema import default_clause                               # noqa: PLC0415
        from .schema import _index_key_cols                              # noqa: PLC0415
        unique = set(spec.pk_columns)
        unique.update(c.name for c in spec.columns if c.unique)
        for uc in spec.unique_constraints:
            unique.update(uc)
        for idx in spec.indexes:
            if idx.unique:
                unique.update(_index_key_cols(idx.columns))
        if not unique:
            return
        actual = {c.name: c for c in self.describe_table(spec.name)}
        q = self.quote_ident
        for col in spec.columns:
            got = actual.get(col.name)
            if (col.name not in unique or col.type.upper() != 'TEXT' or got is None
                    or not got.collation or got.collation == self.KEY_COLLATION):
                continue
            native = (got.definition or 'varchar(255)').replace(' NOT NULL', '')
            if not native.lower().startswith(('varchar', 'char')):
                continue
            clause = f'{native} CHARACTER SET utf8mb4 COLLATE {self.KEY_COLLATION}'
            if not col.nullable or col.primary_key or col.name in spec.composite_pk:
                clause += ' NOT NULL'
            if col.default is not None:
                clause += ' ' + default_clause(col.default, native, self.DDL_TEXT_DEFAULT_PARENS)
            try:
                self.execute_ddl(
                    f'ALTER TABLE {q(spec.name)} MODIFY COLUMN {q(col.name)} {clause}')
            except Exception as exc:  # pylint: disable=broad-except
                import logging  # noqa: PLC0415
                logging.getLogger(__name__).warning(
                    'Table %s: column %s kept its collation %s (%s)',
                    spec.name, col.name, got.collation, exc)

    def _widen_text(self, spec) -> None:
        """Turn this table's plain TEXT columns into LONGTEXT, in place.

        A table created before `DDL_TEXT` became LONGTEXT keeps its TEXT columns, and the
        schema diff calls both «TEXT», so nothing else would ever widen them. Only columns no
        key covers (those are a bounded VARCHAR), and with their nullability and default as
        declared, so the next reconcile sees nothing to change.
        """
        from .schema import _index_key_cols                              # noqa: PLC0415
        from .schema import default_clause                               # noqa: PLC0415
        keyed = {c for idx in spec.indexes for c in _index_key_cols(idx.columns)}
        keyed |= set(spec.composite_pk or ())
        actual = {c.name: c for c in self.describe_table(spec.name)}
        q = self.quote_ident
        for col in spec.columns:
            if (col.type.upper() != 'TEXT' or col.primary_key or col.unique
                    or col.name in keyed):
                continue
            got = actual.get(col.name)
            if got is None or str(got.type).lower() not in ('text', 'tinytext', 'mediumtext'):
                continue
            clause = 'LONGTEXT' + ('' if col.nullable else ' NOT NULL')
            if col.default is not None:
                clause += ' ' + default_clause(col.default, 'LONGTEXT', self.DDL_TEXT_DEFAULT_PARENS)
            self.execute_ddl(f'ALTER TABLE {q(spec.name)} MODIFY COLUMN {q(col.name)} {clause}')

    def describe_table(self, table: str) -> list[ColumnInfo]:
        """Introspect *table*'s columns from ``information_schema.columns`` (current
        database), ordered by ``ordinal_position``; PK columns are flagged from
        ``column_key = 'PRI'``."""
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name, data_type, is_nullable, column_default, '
                'column_key, column_type, collation_name FROM information_schema.columns '
                'WHERE table_schema=DATABASE() AND table_name=%s '
                'ORDER BY ordinal_position',
                (table,),
            )
            rows = cur.fetchall()
        self._end_read(conn)
        out = []
        for r in rows:
            nullable = str(r[2]).upper() == 'YES'
            # The type with its length (`varchar(60)`, `int(10) unsigned`), for a rebuild that
            # has to recreate this column without the spec's help. No default here: MySQL
            # reports it in a form that is not always SQL (see `_column_definitions`).
            out.append(ColumnInfo(
                name=r[0], type=r[1] or '', nullable=nullable,
                default=r[3], pk=(1 if r[4] == 'PRI' else 0),
                definition=(f'{r[5]}{"" if nullable else " NOT NULL"}' if r[5] else None),
                collation=r[6]))
        return out

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
        """What PostgreSQL's connector does on a failed statement, for the same reason.

        MySQL does not abort the transaction on an error: the statement fails and the
        transaction stays open. So a caller that swallowed an expected error (a lost race on a
        unique key) and went on reading left it open for good — `pending` stayed set, no read
        ever ended it, and the metadata lock it held made the next `ALTER` on that table wait
        (error 1205 after `lock_wait_timeout`) behind an idle connection. Outside `begin()` it
        is rolled back here; inside, `transaction()` does it."""
        if not self._tx().explicit:
            try:
                conn.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
            self._settled()

    def _run(self, sql, params, how, *, write: bool = False, many: bool = False):
        self._trace_sql(sql)
        conn = self._conn()
        if write:
            self._tx().pending = True
        try:
            with conn.cursor() as cur:
                if many:
                    cur.executemany(self._adapt_sql(sql), params)
                else:
                    cur.execute(self._adapt_sql(sql), params)
                out = how(cur)
        except pymysql.Error:
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
        """Stream a SELECT through an unbuffered cursor (``SSCursor``): PyMySQL's default
        cursor reads the whole result into memory before the first row is handed over."""
        self._trace_sql(sql)
        conn = self._conn()
        cur = conn.cursor(pymysql.cursors.SSCursor)
        try:
            cur.execute(self._adapt_sql(sql), params)
            while True:
                rows = cur.fetchmany(max(1, int(size)))
                if not rows:
                    break
                yield list(rows)
        except pymysql.Error:
            self._failed(conn)
            raise
        finally:
            try:
                cur.close()            # drains what is left, or the connection is unusable
            except Exception:  # pylint: disable=broad-except
                pass
        self._end_read(conn)

    # ── Write ─────────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> int:
        return self._run(sql, params, lambda cur: cur.rowcount, write=True)[1]

    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        return self._run(sql, params_list, lambda cur: cur.rowcount, write=True, many=True)[1]

    def commit(self) -> None:
        self._conn().commit()
        self._settled()

    def rollback(self) -> None:
        # Settled even when the driver raises (a connection the server dropped): left flagged,
        # `_conn` would keep handing out the dead connection without the ping that replaces it.
        try:
            self._conn().rollback()
        finally:
            self._settled()

    # ── Maintenance ───────────────────────────────────────────────────────────

    def list_tables(self) -> list[str]:
        """The base tables of the connected database, from the catalog.

        Filtered to BASE TABLE so a view is never handed to OPTIMIZE, which does not accept
        one and would fail the whole statement rather than skip it.
        """
        rows = self.fetchall(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name")
        return [r[0] for r in rows]

    def maintenance_targets(self, op: str) -> list[str]:
        """Both statements are per-table here — MySQL has no database-wide form of either."""
        return self.list_tables()

    def compact(self, table: str | None = None) -> None:
        """``OPTIMIZE TABLE`` — one table, or every table. MySQL has no database-wide form.

        On InnoDB this is a full table rebuild (``ALTER TABLE … FORCE`` plus an analyze),
        which is what actually returns space, and it is why this is the expensive action.
        Tables are named one statement at a time rather than in a single comma-separated
        list: one unsupported engine among them fails the entire statement, and a maintenance
        action that stops halfway through leaves the admin with no idea which tables it got to.
        """
        self._per_table('OPTIMIZE TABLE', [table] if table else None)

    def optimize(self, table: str | None = None) -> None:
        """``ANALYZE TABLE`` — statistics only, no rebuild. One table, or all of them."""
        self._per_table('ANALYZE TABLE', [table] if table else None)

    def _per_table(self, statement: str, tables=None) -> None:
        """Run *statement* against each table, skipping the ones that refuse it.

        These return a RESULT SET rather than raising on a table that does not support them,
        so the cursor has to be drained; leaving rows unread poisons the connection for the
        next query with "Commands out of sync".

        *tables* narrows it to a given list; ``None`` means every table in the database.
        """
        conn = self._conn()
        for table in (tables if tables is not None else self.list_tables()):
            sql = f'{statement} {self.quote_ident(table)}'
            self._trace_sql(sql)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.fetchall()
            except Exception as exc:  # pylint: disable=broad-except
                self._dbg_maintenance(table, statement, exc)
        conn.commit()
        self._settled()

    @staticmethod
    def _dbg_maintenance(table: str, statement: str, exc: Exception) -> None:
        """One table refusing maintenance is not a failed maintenance run — say so and move
        on, rather than aborting the other thirty because of it."""
        import sys  # noqa: PLC0415
        print(f'> DB >> {statement} skipped {table}: {type(exc).__name__}: {exc}',
              file=sys.stderr)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
