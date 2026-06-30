#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Abstract database connector interface.

All SQL passed to these methods must use ``?`` as the positional parameter
placeholder.  Concrete connectors translate to their native style internally
(``%s`` for PostgreSQL/MySQL, ``?`` for SQLite).

DDL should use the symbolic type tokens defined on each connector so that
``CREATE TABLE`` statements remain portable:

    connector.DDL_AUTOINCREMENT  — primary key with auto-increment
    connector.DDL_REAL           — floating-point column type
    connector.DDL_TEXT           — variable-length text column
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager

from .schema import (
    ColumnInfo, IndexInfo, SchemaDiff, TableSpec,
    create_index_ddl, create_table_ddl, diff_table,
)

_log = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract database connector.

    All implementations must be thread-safe.  The recommended approach is
    to maintain a per-thread connection via ``threading.local``.

    Transaction model
    -----------------
    Backends differ in their default commit behaviour (SQLite runs in
    autocommit mode; PostgreSQL/MySQL accumulate until ``commit()``).  To
    write portable stores, wrap every multi-statement write in
    ``with connector.transaction():`` — on success it commits, on any
    exception it rolls back.  Single-statement writes outside a transaction
    must still call ``commit()`` so they persist on PG/MySQL.
    """

    # DDL type tokens — override in subclasses
    DDL_AUTOINCREMENT: str = 'INTEGER PRIMARY KEY AUTOINCREMENT'
    DDL_REAL:          str = 'REAL'
    DDL_TEXT:          str = 'TEXT'
    DDL_INTEGER:       str = 'INTEGER'

    # ── Schema management ────────────────────────────────────────────────────

    @abstractmethod
    def execute_ddl(self, ddl: str) -> None:
        """Execute one or more DDL statements (CREATE TABLE, CREATE INDEX…).

        DDL is split on ``;`` and each statement is run individually.
        Implementations must handle ``IF NOT EXISTS`` / ``IF EXISTS``
        gracefully.  DDL does NOT use ``?`` placeholders.
        """

    @abstractmethod
    def add_column_if_missing(
        self, table: str, column: str, col_type: str
    ) -> None:
        """Add a column to *table* if it does not already exist.

        Used for non-destructive schema migrations.
        """

    def list_columns(self, table: str) -> set[str]:
        """Return the set of column names for *table*.

        Returns an empty set if the table does not exist.  Used for
        schema-migration decisions (e.g. renaming a legacy column).
        Default returns ``set()``; concrete connectors override this.
        """
        return set()

    def table_exists(self, table: str) -> bool:
        """Return True if *table* exists (has at least one column)."""
        return bool(self.list_columns(table))

    def describe_table(self, table: str) -> list[ColumnInfo]:
        """Return the table's columns, in physical order, as ColumnInfo.

        Concrete connectors override this with backend introspection.
        """
        raise NotImplementedError

    def list_indexes(self, table: str) -> list[IndexInfo]:
        """Return the table's explicit secondary indexes as IndexInfo.

        Implicit indexes backing PRIMARY KEY / UNIQUE constraints are excluded.
        Concrete connectors override this with backend introspection.
        """
        raise NotImplementedError

    def rename_column(self, table: str, old: str, new: str) -> None:
        """Rename a column, preserving its data.  Portable across modern
        SQLite (3.25+), MySQL (8+/MariaDB 10.5+) and PostgreSQL."""
        q = self.quote_ident
        self.execute_ddl(
            f'ALTER TABLE {q(table)} RENAME COLUMN {q(old)} TO {q(new)}'
        )

    def _trace_sql(self, sql: str) -> None:
        """Trace a SQL statement at debug level (gated by global|log_level).

        Logs the statement only — NEVER the params, which may carry secrets,
        password hashes or other sensitive values.
        """
        from lib.core.object_base import ObjectBase  # noqa: PLC0415
        if not ObjectBase.debug.enabled:
            return
        from lib.debug import DebugLevel  # noqa: PLC0415
        ObjectBase.debug.print('> SQL >> ' + ' '.join(str(sql).split())[:200], DebugLevel.debug)

    # ── Read ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Execute a SELECT and return all matching rows."""

    @abstractmethod
    def fetchone(self, sql: str, params: tuple = ()) -> tuple | None:
        """Execute a SELECT and return the first matching row, or ``None``."""

    # ── Write ────────────────────────────────────────────────────────────────

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> int:
        """Execute a DML statement (INSERT/UPDATE/DELETE).

        Returns the number of rows affected.
        """

    @abstractmethod
    def executemany(self, sql: str, params_list: list[tuple]) -> int:
        """Execute a DML statement once per item in *params_list*.

        Returns the total number of rows affected.
        """

    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""

    @abstractmethod
    def rollback(self) -> None:
        """Roll back the current transaction."""

    # ── Transactions ─────────────────────────────────────────────────────────

    def begin(self) -> None:
        """Open an explicit transaction.

        Default: no-op.  SQLite (autocommit) overrides this to issue ``BEGIN``;
        PG/MySQL are already inside an implicit transaction so nothing is needed.
        """

    @contextmanager
    def transaction(self):
        """Context manager: BEGIN on entry, COMMIT on success, ROLLBACK on error."""
        self.begin()
        try:
            yield self
            self.commit()
        except Exception:
            try:
                self.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
            raise

    # ── Declarative schema reconciliation ────────────────────────────────────

    def quote_ident(self, name: str) -> str:
        """Quote an SQL identifier.  Default uses double quotes (SQLite/PG);
        MySQL overrides with backticks."""
        return f'"{name}"'

    @property
    def _type_map(self) -> dict:
        """Map symbolic spec types to this backend's native DDL tokens."""
        return {
            'TEXT':          self.DDL_TEXT,
            'INTEGER':       self.DDL_INTEGER,
            'REAL':          self.DDL_REAL,
            'AUTOINCREMENT': self.DDL_AUTOINCREMENT,
        }

    def reconcile_table(self, spec: TableSpec) -> SchemaDiff:
        """Make the physical table match *spec*.

        Creates the table if missing; otherwise applies declared renames, diffs
        the live schema against *spec*, and reconciles columns, order, types,
        nullability, defaults and indexes — rebuilding the table when an
        in-place ``ALTER`` cannot express the change.  Columns present in the DB
        but absent from *spec* are preserved and reported, never dropped.
        Returns the computed :class:`SchemaDiff`.
        """
        q = self.quote_ident
        if not self.table_exists(spec.name):
            self.execute_ddl(create_table_ddl(spec, self._type_map, q))
            for idx in spec.indexes:
                self.execute_ddl(create_index_ddl(
                    idx.name, spec.name, idx.columns, idx.unique, q))
            return SchemaDiff(table=spec.name)

        # Apply declared renames before diffing (old->new, data preserved).
        if spec.renames:
            present = self.list_columns(spec.name)
            for old, new in spec.renames.items():
                if old in present and new not in present:
                    self.rename_column(spec.name, old, new)

        actual_cols = self.describe_table(spec.name)
        actual_idx = self.list_indexes(spec.name)
        diff = diff_table(spec, actual_cols, actual_idx)

        if not diff.is_empty:
            if diff.needs_rebuild:
                _log.info('Table %s out of sync (%s) — rebuilding',
                          spec.name, self._diff_summary(diff))
                self._apply_rebuild(spec, actual_cols, actual_idx)
            else:
                _log.info('Table %s out of sync (%s) — applying in place',
                          spec.name, self._diff_summary(diff))
                self._apply_incremental(spec, diff)

        for extra in diff.extra_columns:
            _log.warning("Table %s has column '%s' not in schema — kept (not "
                         'dropped)', spec.name, extra.name)
        for extra in diff.extra_indexes:
            _log.info("Table %s has index '%s' not in schema — kept",
                      spec.name, extra.name)
        return diff

    @staticmethod
    def _diff_summary(diff: SchemaDiff) -> str:
        bits = []
        if diff.missing_columns:
            bits.append('missing=' + ','.join(c.name for c in diff.missing_columns))
        if diff.type_mismatches:
            bits.append('types=' + ','.join(m[0] for m in diff.type_mismatches))
        if diff.nullable_mismatches:
            bits.append('nullable=' + ','.join(m[0] for m in diff.nullable_mismatches))
        if diff.default_mismatches:
            bits.append('defaults=' + ','.join(m[0] for m in diff.default_mismatches))
        if diff.pk_mismatch:
            bits.append('pk')
        if diff.order_wrong:
            bits.append('order')
        if diff.missing_indexes:
            bits.append('idx+=' + ','.join(i.name for i in diff.missing_indexes))
        if diff.changed_indexes:
            bits.append('idx~=' + ','.join(i.name for i in diff.changed_indexes))
        return '; '.join(bits) or 'no-op'

    def _column_type_clause(self, col) -> str:
        """Native type plus inline constraints for a single ADD COLUMN."""
        native = self._type_map.get(col.type.upper(), col.type)
        parts = [native]
        if not col.nullable:
            parts.append('NOT NULL')
        if col.default is not None:
            parts.append(f'DEFAULT {col.default}')
        if col.unique:
            parts.append('UNIQUE')
        return ' '.join(parts)

    def _drop_index(self, name: str, table: str) -> None:
        """Drop an index.  SQLite/PG ignore the table; MySQL overrides."""
        self.execute_ddl(f'DROP INDEX {self.quote_ident(name)}')

    def _apply_incremental(self, spec: TableSpec, diff: SchemaDiff) -> None:
        """Add trailing columns and reconcile indexes without a rebuild."""
        for col in diff.missing_columns:
            self.add_column_if_missing(
                spec.name, col.name, self._column_type_clause(col))
        for idx in diff.changed_indexes:
            self._drop_index(idx.name, spec.name)
        for idx in list(diff.missing_indexes) + list(diff.changed_indexes):
            self.execute_ddl(create_index_ddl(
                idx.name, spec.name, idx.columns, idx.unique, self.quote_ident))

    def _apply_rebuild(
        self, spec: TableSpec,
        actual_cols: list[ColumnInfo], actual_indexes: list[IndexInfo],
    ) -> None:
        """Rebuild the table (create-copy-drop-rename) to match *spec* exactly.

        Preserves data for every column common to old and new, and carries
        across columns present in the DB but absent from the spec (appended).
        Used by SQLite and PostgreSQL; MySQL overrides with in-place ALTERs.
        """
        q = self.quote_ident
        tmp = f'__ssreb_{spec.name}'
        spec_by_name = {c.name: c for c in spec.columns}
        actual_names = {c.name for c in actual_cols}
        spec_names = set(spec.column_names)
        extras = [c for c in actual_cols if c.name not in spec_names]
        # Columns that exist in BOTH old and new tables (data is copied).
        common = [c.name for c in spec.columns if c.name in actual_names]
        common += [c.name for c in extras]
        collist = ', '.join(q(c) for c in common)
        # When a column becomes NOT NULL, replace pre-existing NULLs with its
        # default so the copy does not violate the new constraint.
        select_exprs = []
        for name in common:
            col = spec_by_name.get(name)
            if col is not None and not col.nullable and col.default is not None:
                select_exprs.append(f'COALESCE({q(name)}, {col.default})')
            else:
                select_exprs.append(q(name))
        select_list = ', '.join(select_exprs)
        with self.transaction():
            self.execute(create_table_ddl(
                spec, self._type_map, q, name=tmp, extra_columns=extras))
            if common:
                self.execute(
                    f'INSERT INTO {q(tmp)} ({collist}) '
                    f'SELECT {select_list} FROM {q(spec.name)}')
            self.execute(f'DROP TABLE {q(spec.name)}')
            self.execute(f'ALTER TABLE {q(tmp)} RENAME TO {q(spec.name)}')
            self._recreate_indexes_after_rebuild(spec, actual_indexes)

    def _recreate_indexes_after_rebuild(
        self, spec: TableSpec, actual_indexes: list[IndexInfo],
    ) -> None:
        """Recreate spec indexes (authoritative) plus any pre-existing extra
        indexes, so a rebuild does not silently drop manual indexes."""
        q = self.quote_ident
        spec_names = {i.name for i in spec.indexes}
        for idx in spec.indexes:
            self.execute(create_index_ddl(
                idx.name, spec.name, idx.columns, idx.unique, q))
        for info in actual_indexes:
            if info.name in spec_names or not info.columns:
                continue
            try:
                self.execute(create_index_ddl(
                    info.name, spec.name, info.columns, info.unique, q))
            except Exception:  # pylint: disable=broad-except
                # Expression / partial indexes can't be round-tripped; skip.
                pass

    # ── Maintenance ──────────────────────────────────────────────────────────

    def vacuum(self) -> None:
        """Reclaim unused disk space.  Default: no-op (e.g. MySQL handles
        this automatically; override in connectors that support it)."""

    def checkpoint(self) -> None:
        """Flush the write-ahead log (SQLite WAL only).
        Default: no-op for backends that don't use WAL."""

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @abstractmethod
    def close(self) -> None:
        """Close the current thread's connection."""

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _adapt_sql(self, sql: str) -> str:
        """Translate canonical ``?`` placeholders to the backend's style.

        Override in subclasses that use a different placeholder token.
        """
        return sql  # default: keep as-is (SQLite uses ?)
