#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the declarative schema-reconciliation engine (lib/db/schema.py
and BaseConnector.reconcile_table).

Run against SQLite (the default engine).  The reconciliation logic shared in
``base.py`` is exercised here; MySQL/PostgreSQL reuse the same generic rebuild
and diff, differing only in introspection.
"""

import pytest

from lib.db.schema import (
    Column, Index, TableSpec, canonical_default, canonical_type, diff_table,
)
from lib.db.sqlite import SQLiteConnector


@pytest.fixture()
def db():
    conn = SQLiteConnector(':memory:')
    yield conn
    conn.close()


def _spec():
    return TableSpec(
        name='t',
        columns=(
            Column('id', 'AUTOINCREMENT', primary_key=True),
            Column('uid', 'TEXT', nullable=False, default="''", unique=True),
            Column('name', 'TEXT', nullable=False, default="''"),
            Column('age', 'INTEGER'),
        ),
        indexes=(Index('idx_t_name', ('name',)),),
    )


def _colnames(db, table='t'):
    return [c.name for c in db.describe_table(table)]


# ── Creation / idempotency ──────────────────────────────────────────────────

def test_creates_table_from_spec(db):
    db.reconcile_table(_spec())
    assert _colnames(db) == ['id', 'uid', 'name', 'age']
    assert [i.name for i in db.list_indexes('t')] == ['idx_t_name']


def test_idempotent_no_changes(db):
    spec = _spec()
    db.reconcile_table(spec)
    diff = db.reconcile_table(spec)
    assert diff.is_empty
    assert not diff.needs_rebuild


# ── Column additions ────────────────────────────────────────────────────────

def test_add_trailing_column_keeps_data(db):
    base = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('name', 'TEXT', nullable=False, default="''"),
    ))
    db.reconcile_table(base)
    db.execute("INSERT INTO t (name) VALUES ('alice')")
    db.commit()
    extended = TableSpec(name='t', columns=base.columns + (
        Column('age', 'INTEGER', nullable=False, default='0'),
    ))
    diff = db.reconcile_table(extended)
    assert not diff.needs_rebuild           # trailing add → no rebuild
    assert _colnames(db) == ['id', 'name', 'age']
    assert db.fetchone("SELECT name, age FROM t") == ('alice', 0)


def test_add_middle_column_triggers_rebuild_and_keeps_data(db):
    base = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('age', 'INTEGER'),
    ))
    db.reconcile_table(base)
    db.execute("INSERT INTO t (age) VALUES (42)")
    db.commit()
    # 'name' is inserted *before* the already-present 'age' column.
    target = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('name', 'TEXT', nullable=False, default="'x'"),
        Column('age', 'INTEGER'),
    ))
    diff = db.reconcile_table(target)
    assert diff.needs_rebuild
    assert _colnames(db) == ['id', 'name', 'age']
    assert db.fetchone("SELECT name, age FROM t") == ('x', 42)


# ── Reordering (the user's explicit case) ───────────────────────────────────

def test_reorder_columns_keeps_data(db):
    db.execute_ddl("CREATE TABLE t (col2 TEXT, col1 TEXT)")
    db.execute("INSERT INTO t (col1, col2) VALUES ('one', 'two')")
    db.commit()
    spec = TableSpec(name='t', columns=(
        Column('col1', 'TEXT'),
        Column('col2', 'TEXT'),
    ))
    diff = db.reconcile_table(spec)
    assert diff.order_wrong and diff.needs_rebuild
    assert _colnames(db) == ['col1', 'col2']
    assert db.fetchone("SELECT col1, col2 FROM t") == ('one', 'two')


# ── Type / nullable / default changes ───────────────────────────────────────

def test_type_change_rebuilds(db):
    db.execute_ddl("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    db.execute("INSERT INTO t (id, val) VALUES (1, '7')")
    db.commit()
    spec = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('val', 'INTEGER'),
    ))
    diff = db.reconcile_table(spec)
    assert diff.needs_rebuild
    assert canonical_type(db.describe_table('t')[1].type) == 'INTEGER'
    assert db.fetchone("SELECT val FROM t") == (7,)


def test_nullable_and_default_change(db):
    db.execute_ddl("CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT)")
    db.execute("INSERT INTO t (id) VALUES (1)")
    db.commit()
    spec = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('note', 'TEXT', nullable=False, default="'none'"),
    ))
    diff = db.reconcile_table(spec)
    assert diff.needs_rebuild
    col = db.describe_table('t')[1]
    assert col.nullable is False
    assert canonical_default(col.default) == 'none'


# ── Indexes ─────────────────────────────────────────────────────────────────

def test_create_missing_index_without_rebuild(db):
    base = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('name', 'TEXT'),
    ))
    db.reconcile_table(base)
    withidx = TableSpec(name='t', columns=base.columns,
                        indexes=(Index('idx_t_name', ('name',), unique=True),))
    diff = db.reconcile_table(withidx)
    assert not diff.needs_rebuild
    idx = {i.name: i for i in db.list_indexes('t')}
    assert 'idx_t_name' in idx and idx['idx_t_name'].unique


def test_changed_index_recreated(db):
    spec1 = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT'), Column('b', 'TEXT')),
        indexes=(Index('idx_t', ('a',)),))
    db.reconcile_table(spec1)
    spec2 = TableSpec(name='t', columns=spec1.columns,
                      indexes=(Index('idx_t', ('b',)),))
    db.reconcile_table(spec2)
    idx = {i.name: i for i in db.list_indexes('t')}
    assert idx['idx_t'].columns == ('b',)


# ── Extra columns are kept and reported (never dropped) ─────────────────────

def test_extra_column_kept_and_reported(db):
    db.execute_ddl("CREATE TABLE t (id INTEGER PRIMARY KEY, keep_me TEXT, name TEXT)")
    db.execute("INSERT INTO t (id, keep_me, name) VALUES (1, 'precious', 'x')")
    db.commit()
    spec = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('name', 'TEXT'),
        Column('extra_new', 'TEXT', nullable=False, default="''"),
    ))
    diff = db.reconcile_table(spec)
    assert [c.name for c in diff.extra_columns] == ['keep_me']
    cols = _colnames(db)
    assert 'keep_me' in cols          # preserved
    assert db.fetchone("SELECT keep_me FROM t") == ('precious',)


# ── Column rename via the spec's renames map ────────────────────────────────

def test_rename_column_preserves_data(db):
    db.execute_ddl("CREATE TABLE t (id INTEGER PRIMARY KEY, sid TEXT)")
    db.execute("INSERT INTO t (id, sid) VALUES (1, 'abc')")
    db.commit()
    spec = TableSpec(name='t', columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('uid', 'TEXT'),
    ), renames={'sid': 'uid'})
    db.reconcile_table(spec)
    assert 'uid' in _colnames(db) and 'sid' not in _colnames(db)
    assert db.fetchone("SELECT uid FROM t") == ('abc',)


# ── Normalisation unit tests ────────────────────────────────────────────────

@pytest.mark.parametrize('raw,expected', [
    ('INTEGER', 'INTEGER'), ('int', 'INTEGER'), ('BIGINT', 'INTEGER'),
    ('TEXT', 'TEXT'), ('VARCHAR(255)', 'TEXT'), ('character varying', 'TEXT'),
    ('REAL', 'REAL'), ('double precision', 'REAL'), ('DOUBLE', 'REAL'),
])
def test_canonical_type(raw, expected):
    assert canonical_type(raw) == expected


@pytest.mark.parametrize('raw,expected', [
    (None, None), ('', ''), ("''", ''), ('""', ''), ('NULL', None),
    ("'local'", 'local'), ('1', '1'), ("'{}'", '{}'),
    ("'local'::character varying", 'local'),
])
def test_canonical_default(raw, expected):
    assert canonical_default(raw) == expected


def test_diff_table_pure_function():
    spec = _spec()
    db = SQLiteConnector(':memory:')
    db.reconcile_table(spec)
    diff = diff_table(spec, db.describe_table('t'), db.list_indexes('t'))
    assert diff.is_empty
    db.close()
