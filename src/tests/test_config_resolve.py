#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the config resolution layer (env > config.json > DB > default)."""

from lib.config.resolve import resolve_config, file_leaves
from lib.config.spec import cfg_default


class TestFileLeaves:
    def test_flattens_two_levels(self):
        assert file_leaves({'modules': {'timeout': 15, 'threads': 5}}) == {
            'modules|timeout': 15, 'modules|threads': 5,
        }

    def test_ignores_non_dict_sections(self):
        assert file_leaves({'x': 1, 'y': {'z': 2}}) == {'y|z': 2}


class TestPrecedence:

    def test_db_value_is_editable(self):
        eff, locked = resolve_config({'modules|threads': 9}, {}, {}, include_defaults=False)
        assert eff['modules']['threads'] == 9
        assert 'modules|threads' not in locked          # DB value → editable

    def test_file_overrides_db_and_locks(self):
        # The user's exact example: file has modules.timeout (locked), DB has threads (editable).
        eff, locked = resolve_config(
            {'modules|timeout': 99, 'modules|threads': 5},
            {'modules': {'timeout': 15}},
            {}, include_defaults=False)
        assert eff['modules']['timeout'] == 15           # file wins over DB
        assert eff['modules']['threads'] == 5            # DB value
        assert 'modules|timeout' in locked               # file → read-only
        assert 'modules|threads' not in locked           # DB → editable

    def test_env_overrides_file_and_db(self):
        eff, locked = resolve_config(
            {'web_admin|lang': 'es_ES'},
            {'web_admin': {'lang': 'en_EN'}},
            {'web_admin|lang': 'fr_FR'}, include_defaults=False)
        assert eff['web_admin']['lang'] == 'fr_FR'       # env wins
        assert 'web_admin|lang' in locked

    def test_default_when_unset(self):
        eff, locked = resolve_config({}, {}, {})         # include_defaults=True
        assert eff['web_admin']['lang'] == cfg_default('web_admin|lang')
        assert 'web_admin|lang' not in locked            # default → editable

    def test_database_section_never_from_db(self):
        # database is bootstrap: a DB-stored value must be ignored; file wins.
        eff, locked = resolve_config(
            {'database|driver': 'mysql'},                # should be ignored
            {'database': {'driver': 'postgresql'}},
            {}, include_defaults=False)
        assert eff['database']['driver'] == 'postgresql'
        assert 'database|driver' in locked

    def test_database_default_when_only_db(self):
        # Only a DB value for database → ignored → falls back to spec default.
        eff, _ = resolve_config({'database|driver': 'mysql'}, {}, {})
        assert eff['database']['driver'] == cfg_default('database|driver')

    def test_locked_set_is_union_of_env_and_file(self):
        _, locked = resolve_config(
            {},
            {'modules': {'timeout': 15}},
            {'web_admin|lang': 'es_ES'}, include_defaults=False)
        assert locked == {'modules|timeout', 'web_admin|lang'}

    def test_opaque_leaf_values_preserved(self):
        # dict/list leaf values (group_role_map, page_sizes) are single values.
        eff, _ = resolve_config(
            {'web_admin|page_sizes': [10, 25], 'oidc|group_role_map': {'admins': 'admin'}},
            {}, {}, include_defaults=False)
        assert eff['web_admin']['page_sizes'] == [10, 25]
        assert eff['oidc']['group_role_map'] == {'admins': 'admin'}


class TestBootstrapDatabaseCfg:
    """SS_DB_* env overlay used to point the connector at MySQL/PostgreSQL."""

    def test_env_overlays_file_section(self, monkeypatch):
        from lib.config.manager import bootstrap_database_cfg
        monkeypatch.setenv('SS_DB_DRIVER', 'mysql')
        monkeypatch.setenv('SS_DB_HOST', 'db')
        monkeypatch.setenv('SS_DB_PORT', '3306')
        monkeypatch.setenv('SS_DB_NAME', 'ss')
        monkeypatch.setenv('SS_DB_USER', 'svc')
        monkeypatch.setenv('SS_DB_PASSWORD', 'secret')
        db = bootstrap_database_cfg({'database': {'driver': 'sqlite'}})
        assert db['driver'] == 'mysql' and db['host'] == 'db'
        assert db['port'] == 3306 and isinstance(db['port'], int)
        assert db['name'] == 'ss' and db['user'] == 'svc' and db['password'] == 'secret'

    def test_no_env_returns_file_section(self, monkeypatch):
        from lib.config.manager import bootstrap_database_cfg
        for k in ('SS_DB_DRIVER', 'SS_DB_HOST', 'SS_DB_PORT', 'SS_DB_NAME',
                  'SS_DB_USER', 'SS_DB_PASSWORD', 'SS_DB_PATH'):
            monkeypatch.delenv(k, raising=False)
        assert bootstrap_database_cfg({'database': {'driver': 'sqlite'}}) == {'driver': 'sqlite'}
        assert bootstrap_database_cfg({}) is None      # nothing to bootstrap

    def test_bad_port_is_ignored(self, monkeypatch):
        from lib.config.manager import bootstrap_database_cfg
        monkeypatch.setenv('SS_DB_PORT', 'notaport')
        db = bootstrap_database_cfg({'database': {'driver': 'mysql', 'port': 3306}})
        assert db['port'] == 3306                       # invalid env left the file value
