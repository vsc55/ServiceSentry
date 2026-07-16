#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the central config registry (lib.config.spec) and the small
schema-aware helpers added around it: cfg_default, cfg_get, cfg_validate,
normalize_url, frontend_schema, the derived rule dicts, coerce_lang and
track_change."""

import pytest

from lib.config.spec import (
    CONFIG_FIELDS, CFG_BY_PATH,
    cfg_default, cfg_get, cfg_validate, normalize_url, frontend_schema,
    int_rules, bool_rules, json_dict_fields, env_field_specs, admin_only_fields,
)


class TestRegistryIntegrity:

    def test_no_duplicate_paths(self):
        paths = [f.path for f in CONFIG_FIELDS]
        assert len(paths) == len(set(paths))

    def test_cfg_by_path_complete(self):
        assert set(CFG_BY_PATH) == {f.path for f in CONFIG_FIELDS}

    def test_every_path_has_section_and_field(self):
        for f in CONFIG_FIELDS:
            assert '|' in f.path, f.path


class TestCfgDefault:

    def test_known_defaults(self):
        assert cfg_default('ldap|port') == 389
        assert cfg_default('ldap|timeout') == 5
        assert cfg_default('email|smtp_port') == 587
        assert cfg_default('email|smtp_use_tls') is True
        assert cfg_default('oidc|auto_create_users') is True
        assert cfg_default('web_admin|remember_me_days') == 30
        assert cfg_default('global|log_level') == 'off'

    def test_notifications_matrix_is_dynamic_not_static(self):
        # The routing matrix (notifications|{channel}_on_{kind}) is NOT declared in the
        # registry — it's derived at runtime from the notify-event × channel registries and
        # stored per-cell in the DB. So spec.py must hold no such static keys (no duplication).
        from lib.config.spec import CFG_BY_PATH
        assert not [p for p in CFG_BY_PATH
                    if p.startswith('notifications|') and '_on_' in p]


class TestCfgGet:

    def test_missing_uses_default_coerced(self):
        v = cfg_get({}, 'ldap|port')
        assert v == 389 and isinstance(v, int)

    def test_present_value(self):
        assert cfg_get({'port': 636}, 'ldap|port') == 636

    def test_bool_coercion(self):
        assert cfg_get({'use_ssl': 1}, 'ldap|use_ssl') is True
        assert cfg_get({'use_ssl': 0}, 'ldap|use_ssl') is False

    def test_falsy_false_keeps_empty(self):
        # falsy=False → only missing key falls back; empty string is kept.
        assert cfg_get({'user_filter': ''}, 'ldap|user_filter') == ''

    def test_falsy_true_replaces_empty(self):
        assert cfg_get({'email_attr': ''}, 'ldap|email_attr', falsy=True) == 'mail'
        assert cfg_get({'smtp_port': 0}, 'email|smtp_port', falsy=True) == 587


class TestCfgValidate:

    def test_int_ok(self):
        assert cfg_validate('ldap|port', 389) == (True, None)

    def test_int_out_of_range(self):
        ok, err = cfg_validate('ldap|port', 70000)
        assert ok is False and err == 'range'

    def test_int_wrong_type(self):
        assert cfg_validate('ldap|port', 'x')[1] == 'type'

    def test_int_rejects_bool(self):
        # bool is a subclass of int but must not pass an int field.
        assert cfg_validate('web_admin|remember_me_days', True)[1] == 'type'

    def test_json_dict_ok_string(self):
        assert cfg_validate('ldap|group_role_map', '{"a": "b"}') == (True, None)

    def test_json_dict_ok_dict(self):
        assert cfg_validate('ldap|group_role_map', {'a': 'b'}) == (True, None)

    def test_json_dict_bad(self):
        assert cfg_validate('ldap|group_role_map', '{bad')[1] == 'json'

    def test_json_dict_empty_ok(self):
        assert cfg_validate('ldap|group_role_map', '') == (True, None)

    def test_unconstrained_passes(self):
        assert cfg_validate('ldap|server', 'anything') == (True, None)
        assert cfg_validate('unknown|field', 123) == (True, None)


class TestNormalizeUrl:

    @pytest.mark.parametrize('raw,expected', [
        ('https://Host.com/path/', 'Host.com/path'),
        ('  http://host/  ', 'host'),
        ('host/', 'host'),
        ('host', 'host'),
        ('', ''),
        (None, ''),
        ('https://host:8080', 'host:8080'),
    ])
    def test_store_form(self, raw, expected):
        assert normalize_url(raw) == expected


class TestFrontendSchema:

    def test_bool_field(self):
        s = frontend_schema()
        assert s['web_admin|public_status'] == {'type': 'bool', 'default': False}

    def test_int_field_has_range(self):
        s = frontend_schema()['web_admin|remember_me_days']
        assert s['min'] == 1 and s['max'] == 365 and s['default'] == 30

    def test_excludes_non_attr_fields(self):
        s = frontend_schema()
        assert 'ldap|server' not in s        # str, attr=None
        assert 'ldap|port' not in s          # attr=None
        assert 'webhooks|method' not in s


class TestDerivedRuleDicts:

    def test_int_rules(self):
        r = int_rules()
        assert r['web_admin|remember_me_days']['min'] == 1
        assert r['web_admin|remember_me_days']['attr'] == '_REMEMBER_ME_DAYS'
        assert 'database|port' not in r      # no_rule

    def test_bool_rules(self):
        b = bool_rules()
        assert 'web_admin|public_status' in b
        assert 'web_admin|secure_cookies' not in b   # no_rule (special-cased)
        assert 'telegram|group_messages' not in b    # no_rule

    def test_json_dict_fields(self):
        j = json_dict_fields()
        assert 'ldap|group_role_map' in j and 'oidc|group_display_names' in j

    def test_env_field_specs(self):
        e = env_field_specs()
        assert e['SS_PORT'] == ('web_admin|port', int)
        assert e['SS_CHECK_INTERVAL'] == ('monitoring|timer_check', int)

    def test_admin_only_fields(self):
        a = admin_only_fields()
        assert 'web_admin|secure_cookies' in a
        assert 'web_admin|public_status' in a
        assert 'web_admin|lang' not in a


class TestCoerceLang:

    def test_valid_kept(self):
        from lib.i18n import coerce_lang, SUPPORTED_LANGS
        lang = SUPPORTED_LANGS[0]
        assert coerce_lang(lang, 'en_EN') == lang

    def test_invalid_falls_back(self):
        from lib.i18n import coerce_lang
        assert coerce_lang('zz_ZZ', 'en_EN') == 'en_EN'
        assert coerce_lang('', '') == ''
        assert coerce_lang('zz', 'keep') == 'keep'   # keep-if-valid semantics


class TestTrackChange:

    def test_records_and_applies_change(self):
        from lib.util.entity_audit import track_change
        changes, entity = [], {'name': 'old'}
        track_change(changes, entity, 'name', 'new')
        assert entity['name'] == 'new'
        assert changes == [{'field': 'name', 'old': 'old', 'new': 'new'}]

    def test_no_change_no_record(self):
        from lib.util.entity_audit import track_change
        changes, entity = [], {'name': 'same'}
        track_change(changes, entity, 'name', 'same')
        assert changes == [] and entity['name'] == 'same'

    def test_old_default(self):
        from lib.util.entity_audit import track_change
        changes, entity = [], {}
        track_change(changes, entity, 'name', 'new', old_default='uid-x')
        assert changes == [{'field': 'name', 'old': 'uid-x', 'new': 'new'}]
        assert entity['name'] == 'new'
