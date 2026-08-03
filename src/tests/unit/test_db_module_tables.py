#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the module-declared tables mechanism (lib/db/module_tables.py).

Modules may create their own namespaced tables in the general database; these
tests cover the namespacing helper, the per-module discovery/validation, and
end-to-end reconciliation on a real (in-memory) SQLite connector.
"""

import types

from lib.db import get_connector, module_table, reconcile_module_tables, collect_module_tables
from lib.db.module_tables import _tables_from_module
from lib.db.schema import Column, Index, TableSpec


_COLS = (Column('oid', 'TEXT', nullable=False), Column('name', 'TEXT'))


class TestModuleTableHelper:

    def test_prefixes_table_and_indexes(self):
        spec = module_table('snmp', 'mib_symbols', _COLS,
                            indexes=(Index('by_oid', ('oid',)),))
        assert spec.name == 'mod_snmp_mib_symbols'
        assert spec.indexes[0].name == 'mod_snmp_by_oid'
        assert spec.indexes[0].columns == ('oid',)

    def test_prefix_is_idempotent(self):
        # An already-prefixed name (or index) is left untouched.
        spec = module_table('snmp', 'mod_snmp_cache', (Column('x', 'TEXT'),),
                            indexes=(Index('mod_snmp_ix', ('x',)),))
        assert spec.name == 'mod_snmp_cache'
        assert spec.indexes[0].name == 'mod_snmp_ix'

    def test_carries_pk_and_unique(self):
        spec = module_table('m', 't', (Column('a', 'TEXT'), Column('b', 'TEXT')),
                            composite_pk=('a', 'b'),
                            unique_constraints=(('a', 'b'),))
        assert spec.composite_pk == ('a', 'b')
        assert spec.unique_constraints == (('a', 'b'),)
        assert spec.pk_columns == ('a', 'b')


class TestTablesFromModule:

    def _mod(self, fn):
        return types.SimpleNamespace(discover_db_tables=fn)

    def test_valid_namespaced_table(self):
        m = self._mod(lambda: [module_table('foo', 'cache', (Column('k', 'TEXT'),))])
        out = _tables_from_module('foo', m)
        assert [t.name for t in out] == ['mod_foo_cache']

    def test_wrong_prefix_skipped(self):
        # A spec namespaced for another module must not be accepted.
        m = self._mod(lambda: [module_table('snmp', 'x', (Column('k', 'TEXT'),))])
        assert _tables_from_module('foo', m) == []

    def test_raw_unprefixed_tablespec_skipped(self):
        m = self._mod(lambda: [TableSpec(name='users', columns=(Column('k', 'TEXT'),))])
        assert _tables_from_module('foo', m) == []

    def test_non_tablespec_skipped(self):
        m = self._mod(lambda: ['not a spec', 123])
        assert _tables_from_module('foo', m) == []

    def test_missing_function(self):
        assert _tables_from_module('foo', types.SimpleNamespace()) == []

    def test_non_callable_attribute(self):
        assert _tables_from_module('foo', types.SimpleNamespace(discover_db_tables=42)) == []

    def test_raising_function_is_contained(self):
        def boom():
            raise RuntimeError('nope')
        assert _tables_from_module('foo', self._mod(boom)) == []

    def test_empty_return(self):
        assert _tables_from_module('foo', self._mod(lambda: None)) == []


class TestReconcile:

    def test_reconcile_creates_usable_table(self):
        con = get_connector(None, default_sqlite_path=':memory:')
        spec = module_table('snmp', 'mib_symbols', _COLS,
                            indexes=(Index('by_oid', ('oid',)),))
        con.reconcile_table(spec)
        con.execute("INSERT INTO mod_snmp_mib_symbols (oid, name) VALUES (?, ?)",
                    ('1.3.6.1', 'sysDescr'))
        con.commit()
        assert con.fetchall("SELECT oid, name FROM mod_snmp_mib_symbols") == [('1.3.6.1', 'sysDescr')]

    def test_reconcile_module_tables_real_dir_is_safe(self):
        # No shipped module declares tables yet → empty result, never raises.
        con = get_connector(None, default_sqlite_path=':memory:')
        assert reconcile_module_tables(con) == []

    def test_collect_module_tables_real_dir(self):
        # The walk over the real watchfuls package must return a list (no crash).
        assert isinstance(collect_module_tables(), list)

    def test_reconcile_failure_is_isolated(self, monkeypatch):
        # A spec that fails to reconcile is logged and skipped, not propagated.
        con = get_connector(None, default_sqlite_path=':memory:')
        good = module_table('foo', 'ok', (Column('a', 'TEXT'),))
        bad = TableSpec(name='mod_foo_bad', columns=())  # no columns → invalid DDL
        monkeypatch.setattr('lib.db.module_tables.collect_module_tables',
                            lambda *a, **k: [bad, good])
        done = reconcile_module_tables(con)
        assert 'mod_foo_ok' in done   # the good one still got created
