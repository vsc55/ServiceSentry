#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the central config registry (lib.config.spec) and the small
schema-aware helpers added around it: cfg_default, cfg_get, cfg_validate,
normalize_url, frontend_schema, the derived rule dicts, coerce_lang and
track_change.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_config_spec.py`` lives in ``tests/meta/test_config_spec.py``."""

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
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        app = io.open(os.path.join(src, 'lib', 'web_admin', 'app.py'), encoding='utf-8').read()
        from lib.config.spec import CONFIG_FIELDS
        for f in CONFIG_FIELDS:
            if not f.attr:
                continue
            twin = '_' + f.path.split('|', 1)[1]        # the lower-case spelling
            if twin == f.attr:
                continue
            assert f'\n    {twin} = ' not in app, f'{f.path}: {twin} shadows {f.attr}'




class TestNoDefaultIsWrittenTwice:
    """A second copy of a default is a copy that gets to disagree: the panel offering one
    number as the default while the server binds to another, with nothing on either side
    saying which is the real one.

    `DEFAULT_PORT = 8080` and `DEFAULT_HOST = '0.0.0.0'` sat on `WebAdmin` beside the registry
    entries that already said exactly that.
    """

    def test_the_start_up_fallbacks_come_from_the_registry(self):
        from lib.config.spec import cfg_default
        # importorskip: el panel arrastra Flask, que puede no estar en una instalación slim.
        WebAdmin = pytest.importorskip('lib.web_admin.app').WebAdmin
        assert WebAdmin.DEFAULT_PORT == cfg_default('web_admin|port')
        assert WebAdmin.DEFAULT_HOST == cfg_default('web_admin|host')

    def test_they_are_not_literals(self):
        import io as _io
        import os as _os
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        app = _io.open(_os.path.join(src, 'lib', 'web_admin', 'app.py'), encoding='utf-8').read()
        for literal in ('DEFAULT_PORT = 8080', "DEFAULT_HOST = '0.0.0.0'"):
            assert literal not in app, literal


class TestLaRetencionDelHistoricoEsUnAjuste:
    """Eran 30 días escritos dentro del bucle de poda del monitor, que es el peor sitio posible
    para un número que depende enteramente de la flota: en una instalación real SNMP es el 83 %
    de las filas —noventa mil en diecisiete días— y quien tiene que meter eso en un disco no
    tenía forma de decirlo sin editar el código.

    Es el paso 2 del plan de `docs/explica-snmp.md`."""

    def test_esta_en_el_registro(self):
        assert cfg_default('history|retention_days') == 30

    def test_cero_significa_para_siempre_y_se_puede_escribir(self):
        """El podador ya entiende el cero; sin un mínimo de cero, la pantalla no dejaría
        pedirlo."""
        ok, _ = cfg_validate('history|retention_days', 0)
        assert ok

    def test_y_no_lo_puede_cambiar_cualquiera(self):
        """Bajarlo borra datos que no vuelven."""
        assert 'history|retention_days' in admin_only_fields()

    def test_el_monitor_no_lleva_el_numero_escrito(self):
        """Los dos lados de la misma frase: el registro es el único sitio donde se cambia un
        valor por defecto, así que un 30 suelto en el podador sería un segundo sitio — y el que
        gana no es el que la pantalla enseña."""
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        man = _io.open(_os.path.join(src, 'lib', 'services', 'monitoring', 'manager.py'),
                       encoding='utf-8').read()
        poda = man.split('self._history.prune')[0][-900:]
        assert "retention_days', 30)" not in poda, 'el 30 sigue escrito en el podador'
        assert "cfg_default('history|retention_days')" in poda, poda[-300:]


class TestUnDesplegableNoEnseñaIdentificadores:
    """`_opt_labels` busca la palabra de cada opción en el catálogo de idiomas **por su clave de
    primer nivel**, y si no la encuentra devuelve la opción tal cual. No falla, no avisa: el
    desplegable sale con «osm», «carto_light», «google» escritos, que es lo que se vio en la
    pantalla del mapa — las claves se habían metido dentro de `labels`, donde nadie las busca.

    Y es un fallo que se repite solo: cada select nuevo tiene que acordarse de dónde van sus
    palabras, y el sitio equivocado tiene toda la pinta de ser el bueno.
    """

    def _selects(self):
        from lib.core.config.service import build_config_schema      # noqa: PLC0415
        return {p: m for p, m in build_config_schema().items()
                if (m or {}).get('options_i18n')}

    def test_cada_opcion_tiene_su_palabra_en_todos_los_idiomas(self):
        crudas = []
        for path, meta in self._selects().items():
            for opcion, porlang in (meta['options_i18n'] or {}).items():
                for lang, texto in (porlang or {}).items():
                    if texto == opcion:
                        crudas.append(f'{path} · {opcion!r} · {lang}')
        assert not crudas, ('opciones que salen con su identificador escrito:' + chr(10) + '  '
                            + (chr(10) + '  ').join(crudas))

    def test_y_ninguna_se_queda_sin_etiquetar(self):
        """Declarar `options_i18n` a medias deja unas opciones con nombre y otras con su
        identificador, en la misma lista."""
        faltan = []
        for path, meta in self._selects().items():
            etiquetadas = set((meta['options_i18n'] or {}))
            for opcion in (meta.get('options') or []):
                if opcion not in etiquetadas:
                    faltan.append(f'{path} · {opcion!r}')
        assert not faltan, faltan

    def test_y_hay_desplegables_que_mirar(self):
        """Sin esto, las dos de arriba pasarían el día que `build_config_schema` dejara de
        declarar ninguno — verdes y sin mirar nada."""
        assert len(self._selects()) >= 5
