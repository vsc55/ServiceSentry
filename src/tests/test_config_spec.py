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
        assert 'web_admin|default_lang' not in a


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


class TestOverlayAllEnv:
    """`overlay_all_env` applies SS_* env to a FULL config on the consumption side.

    The stored config never carries env (the UI needs saved-vs-locked separate), so
    notification dispatch and the standalone workers apply it here. Regression: telegram
    was ignored everywhere and events|autostart in the embedded boot."""

    def _overlay(self, monkeypatch, cfg, env):
        # Start from an environment with NO SS_* set (conftest fixes SS_SYSLOG_AUTOSTART
        # etc. process-wide) and apply only this case's vars, so the result is deterministic.
        from lib.config.manager import overlay_all_env
        for k in env_field_specs():
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return overlay_all_env(cfg)

    def test_creates_absent_section_from_env(self, monkeypatch):
        # blank saved telegram + SS_TELEGRAM_* → the section is materialised
        out = self._overlay(monkeypatch, {'global': {'log_level': 'off'}},
                            {'SS_TELEGRAM_TOKEN': 'T', 'SS_TELEGRAM_CHAT_ID': 'C'})
        assert out['telegram'] == {'token': 'T', 'chat_id': 'C'}

    def test_env_wins_over_saved(self, monkeypatch):
        out = self._overlay(monkeypatch, {'telegram': {'token': 'saved'}},
                            {'SS_TELEGRAM_TOKEN': 'env'})
        assert out['telegram']['token'] == 'env'

    def test_bool_and_int_casting(self, monkeypatch):
        out = self._overlay(monkeypatch, {},
                            {'SS_EVENTS_AUTOSTART': '0', 'SS_CHECK_INTERVAL': '45'})
        assert out['events']['autostart'] is False
        assert out['monitoring']['timer_check'] == 45 and isinstance(
            out['monitoring']['timer_check'], int)

    def test_database_section_is_left_to_bootstrap(self, monkeypatch):
        # SS_DB_* is owned by bootstrap_database_cfg; overlay_all_env must not touch it.
        out = self._overlay(monkeypatch, {'database': {'driver': 'sqlite'}},
                            {'SS_DB_PASSWORD': 'x'})
        assert out['database'] == {'driver': 'sqlite'}

    def test_sections_without_env_untouched_and_no_mutation(self, monkeypatch):
        src = {'global': {'log_level': 'off'}}
        out = self._overlay(monkeypatch, src, {})
        assert out == {'global': {'log_level': 'off'}}
        out['global']['log_level'] = 'debug'      # out is a copy
        assert src['global']['log_level'] == 'off'


class TestAMirroredAttributeIsDerivableFromItsOption:
    """`attr` is the WebAdmin attribute a config option is mirrored on at runtime, and it was
    written out by hand next to each option: thirty-seven `_UPPER_SNAKE`, eleven `_lower_snake`,
    and ten that did not match their option at all (`_WEB_PORT` for `port`, `_LOGIN_RL_MAX` for
    `login_ratelimit_max`).

    Nothing said which to expect, so `_DEFAULT_PAGE_SIZE` outlived the rename of the option it
    mirrors without anyone noticing — which is what was reported. One rule, and it is checkable:
    the attribute is the option name upper-cased with a leading underscore.
    """

    def test_every_attribute_matches_its_option(self):
        from lib.config.spec import CONFIG_FIELDS
        wrong = [(f.path, f.attr) for f in CONFIG_FIELDS
                 if f.attr and f.attr != '_' + f.path.split('|', 1)[1].upper()]
        assert not wrong, 'attributes that do not follow from their option: ' + repr(wrong)

    def test_no_option_is_mirrored_on_two_attributes(self):
        """Four options had an UPPER class default AND a lower-case attribute the config
        actually wrote to. Only one of the two was ever updated; the other sat there looking
        authoritative and answering with the value the product shipped with."""
        import io
        import os
        src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        app = io.open(os.path.join(src, 'lib', 'web_admin', 'app.py'), encoding='utf-8').read()
        from lib.config.spec import CONFIG_FIELDS
        for f in CONFIG_FIELDS:
            if not f.attr:
                continue
            twin = '_' + f.path.split('|', 1)[1]        # the lower-case spelling
            if twin == f.attr:
                continue
            assert f'\n    {twin} = ' not in app, f'{f.path}: {twin} shadows {f.attr}'


class TestTheKeyFileHasOneName:
    """`.flask_secret` signs Flask's session cookies AND derives the Fernet key every stored
    secret is encrypted with — losing it is not "sign in again", it is every secret in the
    database becoming unreadable.

    Its name was spelled out in six places: the panel, the CLI and the four standalone
    services. One spelling away from a process that derives a different key, decrypts nothing,
    and reports the config as empty rather than as broken.
    """

    def test_only_the_registry_names_it(self):
        import io
        import os
        src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spelled = []
        for base, dirs, files in os.walk(os.path.join(src, 'lib')):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for name in files:
                if not name.endswith('.py'):
                    continue
                path = os.path.join(base, name)
                if "'.flask_secret'" in io.open(path, encoding='utf-8').read():
                    spelled.append(os.path.relpath(path, src))
        assert spelled == [os.path.join('lib', 'config', '__init__.py')], spelled

    def test_the_helper_and_the_panel_agree(self):
        from lib.config import SECRET_KEY_FILENAME, secret_key_path
        from lib.web_admin.app import WebAdmin
        assert WebAdmin._SECRET_KEY_FILE == SECRET_KEY_FILENAME
        assert secret_key_path('/x').endswith(SECRET_KEY_FILENAME)


class TestNoDefaultIsWrittenTwice:
    """A second copy of a default is a copy that gets to disagree: the panel offering one
    number as the default while the server binds to another, with nothing on either side
    saying which is the real one.

    `DEFAULT_PORT = 8080` and `DEFAULT_HOST = '0.0.0.0'` sat on `WebAdmin` beside the registry
    entries that already said exactly that.
    """

    def test_the_start_up_fallbacks_come_from_the_registry(self):
        from lib.config.spec import cfg_default
        from lib.web_admin.app import WebAdmin
        assert WebAdmin.DEFAULT_PORT == cfg_default('web_admin|port')
        assert WebAdmin.DEFAULT_HOST == cfg_default('web_admin|host')

    def test_they_are_not_literals(self):
        import io as _io
        import os as _os
        src = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        app = _io.open(_os.path.join(src, 'lib', 'web_admin', 'app.py'), encoding='utf-8').read()
        for literal in ('DEFAULT_PORT = 8080', "DEFAULT_HOST = '0.0.0.0'"):
            assert literal not in app, literal
