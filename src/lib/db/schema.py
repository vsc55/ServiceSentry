#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Declarative table-schema specification and reconciliation diff engine.

A :class:`TableSpec` describes the *desired* shape of a table (columns, order,
types, nullability, defaults, primary key and indexes).  Connectors introspect
the *actual* table into :class:`ColumnInfo` / :class:`IndexInfo` lists and feed
both to :func:`diff_table`, which reports every difference and whether a full
table rebuild is required to reconcile them.

This module is backend-agnostic: it contains no SQL execution, only the data
model, normalisation rules and the diff algorithm.  DDL string construction is
also here (parameterised by the connector's type tokens and identifier quoting)
so all three connectors share one builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Desired-schema specification ────────────────────────────────────────────

@dataclass(frozen=True)
class Column:
    """A desired column.

    ``type`` is a symbolic token — ``'TEXT'``, ``'INTEGER'``, ``'REAL'`` or
    ``'AUTOINCREMENT'`` — mapped to the backend's native type by the connector.
    ``default`` is the raw SQL literal exactly as it would appear after
    ``DEFAULT`` (e.g. ``"''"``, ``"1"``, ``"'local'"``); ``None`` means no
    default.
    """
    name: str
    type: str
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False
    unique: bool = False


@dataclass(frozen=True)
class Index:
    """A desired index.  ``columns`` may carry a direction, e.g. ``('id DESC',)``."""
    name: str
    columns: tuple[str, ...]
    unique: bool = False


@dataclass(frozen=True)
class TableSpec:
    """The desired shape of a table."""
    name: str
    columns: tuple[Column, ...]
    indexes: tuple[Index, ...] = ()
    composite_pk: tuple[str, ...] = ()
    # Table-level multi-column UNIQUE constraints, e.g. (('group_uid','role_uid'),).
    # Emitted in CREATE TABLE; not diffed (created on fresh tables, never retro-added).
    unique_constraints: tuple[tuple[str, ...], ...] = ()
    renames: dict = field(default_factory=dict)  # {old_name: new_name}, applied first

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @property
    def pk_columns(self) -> tuple[str, ...]:
        if self.composite_pk:
            return tuple(self.composite_pk)
        return tuple(c.name for c in self.columns if c.primary_key)


# ── Introspection results ───────────────────────────────────────────────────

@dataclass(frozen=True)
class ColumnInfo:
    """An existing column as reported by the backend (in physical order)."""
    name: str
    type: str
    nullable: bool
    default: str | None
    pk: int = 0  # 0 = not part of PK; >0 = 1-based position within the PK


@dataclass(frozen=True)
class IndexInfo:
    """An existing index as reported by the backend."""
    name: str
    columns: tuple[str, ...]
    unique: bool = False


# ── Normalisation (best-effort, cross-engine) ───────────────────────────────

def canonical_type(raw: str) -> str:
    """Reduce a backend type name to one of TEXT / INTEGER / REAL."""
    t = (raw or '').strip().upper().split('(')[0].strip()
    if t in ('AUTOINCREMENT',):
        return 'INTEGER'
    if t in ('INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT', 'MEDIUMINT',
             'SERIAL', 'BIGSERIAL', 'INT2', 'INT4', 'INT8'):
        return 'INTEGER'
    if t in ('REAL', 'DOUBLE', 'DOUBLE PRECISION', 'FLOAT', 'NUMERIC',
             'DECIMAL', 'FLOAT8', 'FLOAT4'):
        return 'REAL'
    if t in ('TEXT', 'VARCHAR', 'CHARACTER VARYING', 'CHARACTER', 'CHAR',
             'CLOB', 'NVARCHAR', 'NCHAR', 'LONGTEXT', 'MEDIUMTEXT', 'TINYTEXT',
             'BPCHAR'):
        return 'TEXT'
    return t or 'TEXT'


def canonical_default(raw) -> str | None:
    """Normalise a DEFAULT literal to a bare value for cross-engine comparison.

    Strips one layer of surrounding single quotes and any PostgreSQL ``::type``
    cast.  ``None`` (and the SQL keyword ``NULL``) mean "no default"; an empty
    string default (``DEFAULT ''``) normalises to ``''`` (distinct from None).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    s = s.split('::', 1)[0].strip()  # drop PG cast suffix
    if s == '':
        # A driver reporting '' (e.g. MySQL) means DEFAULT '' — an empty string.
        return ''
    if s.upper() == 'NULL':
        return None
    # Strip one layer of surrounding quotes. SQLite stores ALTER-added string
    # defaults double-quoted ("") — semantically the same empty string as ''.
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        s = s[1:-1]
    return s


def _index_key_cols(cols) -> tuple[str, ...]:
    """Bare column names for index comparison (drops ASC/DESC direction)."""
    out = []
    for c in cols:
        name = str(c).strip()
        upper = name.upper()
        for suffix in (' DESC', ' ASC'):
            if upper.endswith(suffix):
                name = name[: -len(suffix)].strip()
                break
        out.append(name)
    return tuple(out)


# ── Diff ─────────────────────────────────────────────────────────────────────

@dataclass
class SchemaDiff:
    """The set of differences between a TableSpec and an existing table."""
    table: str
    missing_columns: list = field(default_factory=list)     # list[Column]
    extra_columns: list = field(default_factory=list)        # list[ColumnInfo] (report only)
    type_mismatches: list = field(default_factory=list)      # list[(name, want, got)]
    nullable_mismatches: list = field(default_factory=list)  # list[(name, want, got)]
    default_mismatches: list = field(default_factory=list)   # list[(name, want, got)]
    pk_mismatch: bool = False
    order_wrong: bool = False
    missing_indexes: list = field(default_factory=list)      # list[Index]
    changed_indexes: list = field(default_factory=list)      # list[Index]
    extra_indexes: list = field(default_factory=list)        # list[IndexInfo] (report only)
    # Set by diff_table(): True when missing columns must be inserted mid-order.
    missing_not_trailing: bool = False

    @property
    def needs_rebuild(self) -> bool:
        return bool(
            self.type_mismatches or self.nullable_mismatches
            or self.default_mismatches or self.pk_mismatch or self.order_wrong
            or self.missing_not_trailing
        )

    @property
    def is_empty(self) -> bool:
        return not (
            self.missing_columns or self.type_mismatches
            or self.nullable_mismatches or self.default_mismatches
            or self.pk_mismatch or self.order_wrong
            or self.missing_indexes or self.changed_indexes
        )


def diff_table(
    spec: TableSpec,
    actual_cols: list[ColumnInfo],
    actual_indexes: list[IndexInfo],
) -> SchemaDiff:
    """Compute the differences needed to turn the actual table into *spec*."""
    diff = SchemaDiff(table=spec.name)

    spec_by_name = {c.name: c for c in spec.columns}
    actual_by_name = {c.name: c for c in actual_cols}
    spec_names = spec.column_names

    # Missing / extra columns
    diff.missing_columns = [c for c in spec.columns if c.name not in actual_by_name]
    diff.extra_columns = [c for c in actual_cols if c.name not in spec_by_name]

    # Per-column attribute comparison (only for columns present in both)
    for col in spec.columns:
        act = actual_by_name.get(col.name)
        if act is None:
            continue
        is_autoinc = col.type.upper() == 'AUTOINCREMENT'
        is_pk = col.primary_key or col.name in spec.composite_pk

        want_type = canonical_type(col.type)
        got_type = canonical_type(act.type)
        if want_type != got_type:
            diff.type_mismatches.append((col.name, want_type, got_type))

        # PK / autoincrement columns: nullability and default are implicit.
        if not is_autoinc and not is_pk:
            if col.nullable != act.nullable:
                diff.nullable_mismatches.append(
                    (col.name, col.nullable, act.nullable))
            want_def = canonical_default(col.default)
            got_def = canonical_default(act.default)
            if want_def != got_def:
                diff.default_mismatches.append((col.name, want_def, got_def))

    # Primary key
    want_pk = set(spec.pk_columns)
    got_pk = {c.name for c in actual_cols if c.pk}
    diff.pk_mismatch = want_pk != got_pk

    # Column order: the defined columns present in the table must appear in the
    # same relative order the spec defines them.  Extra columns are ignored.
    present_defined = [c.name for c in actual_cols if c.name in spec_by_name]
    spec_present = [n for n in spec_names if n in actual_by_name]
    diff.order_wrong = present_defined != spec_present

    # Missing columns can be appended with ADD COLUMN only if they are all at
    # the trailing end of the spec (after every already-present defined column).
    present_idx = [i for i, n in enumerate(spec_names) if n in actual_by_name]
    missing_idx = [i for i, n in enumerate(spec_names) if n not in actual_by_name]
    if missing_idx and present_idx:
        diff.missing_not_trailing = min(missing_idx) < max(present_idx)
    else:
        diff.missing_not_trailing = False

    # Indexes (compared by name; columns compared without ASC/DESC direction)
    actual_idx = {i.name: i for i in actual_indexes}
    spec_idx_names = set()
    for idx in spec.indexes:
        spec_idx_names.add(idx.name)
        existing = actual_idx.get(idx.name)
        want_cols = _index_key_cols(idx.columns)
        if existing is None:
            diff.missing_indexes.append(idx)
        elif (_index_key_cols(existing.columns) != want_cols
              or bool(existing.unique) != bool(idx.unique)):
            diff.changed_indexes.append(idx)
    diff.extra_indexes = [i for i in actual_indexes if i.name not in spec_idx_names]

    return diff


# ── DDL construction (parameterised by the connector) ───────────────────────

def _column_ddl(col: Column, type_map: dict, quote, keyed: bool = False) -> str:
    """Build a single column definition for CREATE TABLE.

    *keyed* marks a column that participates in a key/index: a TEXT column then
    uses the backend's ``TEXT_KEY`` type (a bounded VARCHAR on MySQL, which can't
    index plain TEXT; plain TEXT elsewhere)."""
    if col.type.upper() == 'AUTOINCREMENT':
        return f'{quote(col.name)} {type_map["AUTOINCREMENT"]}'
    token = col.type.upper()
    if keyed and token == 'TEXT' and 'TEXT_KEY' in type_map:
        native = type_map['TEXT_KEY']
    else:
        native = type_map.get(token, col.type)
    parts = [f'{quote(col.name)} {native}']
    if col.primary_key:
        parts.append('PRIMARY KEY')
    if not col.nullable:
        parts.append('NOT NULL')
    if col.default is not None:
        parts.append(f'DEFAULT {col.default}')
    if col.unique:
        parts.append('UNIQUE')
    return ' '.join(parts)


def _colinfo_ddl(info: ColumnInfo, quote) -> str:
    """Build a column definition from an introspected (extra) column, preserved
    verbatim during a rebuild so its data is never lost."""
    parts = [f'{quote(info.name)} {info.type or "TEXT"}']
    if not info.nullable:
        parts.append('NOT NULL')
    if info.default is not None:
        parts.append(f'DEFAULT {info.default}')
    return ' '.join(parts)


def create_table_ddl(
    spec: TableSpec, type_map: dict, quote,
    *, name: str | None = None, extra_columns: list[ColumnInfo] | None = None,
) -> str:
    """Build a full CREATE TABLE statement from *spec*.

    ``name`` overrides the table name (used for the temp table during rebuild).
    ``extra_columns`` are appended after the spec columns (preserved on rebuild).
    """
    table = name or spec.name
    # Columns that take part in a key/index — their TEXT type must be indexable
    # (VARCHAR on MySQL). Covers the PK, composite PK, UNIQUE columns/constraints
    # and every index.
    keyed: set = set(spec.pk_columns)
    keyed.update(c.name for c in spec.columns if c.primary_key or c.unique)
    for uc in spec.unique_constraints:
        keyed.update(uc)
    for idx in spec.indexes:
        keyed.update(_index_key_cols(idx.columns))
    defs = [_column_ddl(c, type_map, quote, keyed=(c.name in keyed)) for c in spec.columns]
    for info in (extra_columns or []):
        defs.append(_colinfo_ddl(info, quote))
    if spec.composite_pk:
        cols = ', '.join(quote(c) for c in spec.composite_pk)
        defs.append(f'PRIMARY KEY ({cols})')
    for uniq in spec.unique_constraints:
        cols = ', '.join(quote(c) for c in uniq)
        defs.append(f'UNIQUE ({cols})')
    body = ',\n    '.join(defs)
    return f'CREATE TABLE {quote(table)} (\n    {body}\n)'


def _index_col_ddl(col: str, quote) -> str:
    """Quote an index column, keeping a trailing ASC/DESC direction intact."""
    text = str(col).strip()
    if text.upper().endswith((' ASC', ' DESC')):
        name, direction = text.rsplit(' ', 1)
        return f'{quote(name.strip())} {direction.upper()}'
    return quote(text)


def create_index_ddl(name: str, table: str, columns, unique: bool, quote) -> str:
    """Build a CREATE INDEX statement (column directions preserved as written)."""
    cols = ', '.join(_index_col_ddl(c, quote) for c in columns)
    uniq = 'UNIQUE ' if unique else ''
    return f'CREATE {uniq}INDEX {quote(name)} ON {quote(table)} ({cols})'
