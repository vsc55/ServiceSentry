#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for config routes: /api/config (GET, PUT) — comprehensive coverage."""

import json
from datetime import timedelta

import pytest

try:
    from lib.web_admin import WebAdmin
    from lib.web_admin.constants import SUPPORTED_LANGS
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False
    SUPPORTED_LANGS = ()

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

# Idioma válido garantizado (siempre existe al menos en_EN)
_VALID_LANG = SUPPORTED_LANGS[0] if SUPPORTED_LANGS else 'en_EN'
_INVALID_LANG = 'xx_INVALID'


# ─────────────────────────── Autenticación ─────────────────────────

class TestApiConfigAuth:
    """Autenticación / autorización para /api/config."""

    def test_get_requires_auth(self, client):
        assert client.get("/api/config").status_code == 302

    def test_put_requires_auth(self, client):
        assert client.put("/api/config", json={}).status_code == 302


# ──────────────────────────────── GET ──────────────────────────────

class TestApiConfigGet:
    """GET /api/config."""

    def test_get_returns_200(self, client):
        _login(client)
        assert client.get("/api/config").status_code == 200

    def test_get_returns_dict(self, client):
        _login(client)
        assert isinstance(client.get("/api/config").get_json(), dict)

    def test_get_includes_config_values(self, client):
        _login(client)
        data = client.get("/api/config").get_json()
        assert data["daemon"]["timer_check"] == 300
        # Sensitive fields are masked (returned as null) — never sent to the client
        assert data["telegram"]["token"] is None


# ─────────────────────────── PUT básico ────────────────────────────

class TestApiConfigPutBasic:
    """Comportamiento básico de PUT /api/config."""

    def test_put_saves_data(self, client, config_dir):
        _login(client)
        resp = client.put("/api/config", json={"daemon": {"timer_check": 600}})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["daemon"]["timer_check"] == 600

    def test_put_empty_object_saves(self, client):
        _login(client)
        resp = client.put("/api/config", json={})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_put_invalid_json(self, client):
        _login(client)
        resp = client.put("/api/config", data="{bad", content_type="application/json")
        assert resp.status_code == 400

    def test_put_null_body_rejected(self, client):
        _login(client)
        resp = client.put("/api/config", data="null", content_type="application/json")
        assert resp.status_code == 400

    def test_put_json_array_rejected(self, client):
        _login(client)
        resp = client.put("/api/config", json=[1, 2, 3])
        assert resp.status_code == 400

    def test_put_json_string_rejected(self, client):
        _login(client)
        resp = client.put("/api/config", data='"hello"', content_type="application/json")
        assert resp.status_code == 400

    def test_put_json_number_rejected(self, client):
        _login(client)
        resp = client.put("/api/config", data="42", content_type="application/json")
        assert resp.status_code == 400


# ──────────────────────────── secure_cookies ───────────────────────

class TestApiConfigPutSecureCookies:
    """PUT /api/config → web_admin.secure_cookies aplicado en tiempo de ejecución."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"secure_cookies": value}})

    def test_true_applied_to_instance(self, client, admin):
        _login(client)
        admin._secure_cookies = False
        self._put(client, True)
        assert admin._secure_cookies is True

    def test_true_propagates_to_flask_config(self, client, admin):
        _login(client)
        admin._secure_cookies = False
        self._put(client, True)
        assert admin._app.config['SESSION_COOKIE_SECURE'] is True

    def test_false_applied(self, client, admin):
        _login(client)
        admin._secure_cookies = True
        self._put(client, False)
        assert admin._secure_cookies is False
        assert admin._app.config['SESSION_COOKIE_SECURE'] is False

    def test_string_ignored(self, client, admin):
        _login(client)
        admin._secure_cookies = False
        self._put(client, "true")
        assert admin._secure_cookies is False

    def test_int_ignored(self, client, admin):
        _login(client)
        admin._secure_cookies = False
        self._put(client, 1)
        assert admin._secure_cookies is False

    def test_null_ignored(self, client, admin):
        _login(client)
        admin._secure_cookies = False
        self._put(client, None)
        assert admin._secure_cookies is False

    def test_list_ignored(self, client, admin):
        _login(client)
        admin._secure_cookies = False
        self._put(client, [True])
        assert admin._secure_cookies is False

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._secure_cookies = True
        client.put("/api/config", json={})
        assert admin._secure_cookies is True


# ────────────────────────── remember_me_days ───────────────────────

class TestApiConfigPutRememberMeDays:
    """PUT /api/config → web_admin._REMEMBER_ME_DAYS aplicado en tiempo de ejecución."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"remember_me_days": value}})

    def test_valid_applied(self, client, admin):
        _login(client)
        self._put(client, 60)
        assert admin._REMEMBER_ME_DAYS == 60

    def test_valid_propagates_to_flask_config(self, client, admin):
        _login(client)
        self._put(client, 60)
        assert admin._app.config['PERMANENT_SESSION_LIFETIME'] == timedelta(days=60)

    def test_boundary_min(self, client, admin):
        _login(client)
        self._put(client, 1)
        assert admin._REMEMBER_ME_DAYS == 1

    def test_boundary_max(self, client, admin):
        _login(client)
        self._put(client, 365)
        assert admin._REMEMBER_ME_DAYS == 365

    def test_below_min_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, 0).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_above_max_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, 366).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_negative_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, -1).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_string_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, "60").status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_float_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, 60.5).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_null_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, None).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_bool_true_rejected(self, client, admin):
        """JSON true no debe aplicarse como entero 1 (bool es subclase de int en Python)."""
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, True).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_bool_false_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, False).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_dict_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, {"value": 30}).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_list_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        assert self._put(client, [30]).status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        client.put("/api/config", json={})
        assert admin._REMEMBER_ME_DAYS == 30

    # --- disk tests: invalid value returns 400 and does not write config.json ---

    def test_string_does_not_corrupt_disk(self, client, config_dir):
        """Una cadena devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 30)
        resp = self._put(client, "60")
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["remember_me_days"] == 30

    def test_null_does_not_corrupt_disk(self, client, config_dir):
        """null devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 30)
        resp = self._put(client, None)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["remember_me_days"] == 30

    def test_below_min_does_not_corrupt_disk(self, client, config_dir):
        """Valor fuera de rango (< 1) devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 30)
        resp = self._put(client, 0)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["remember_me_days"] == 30

    def test_above_max_does_not_corrupt_disk(self, client, config_dir):
        """Valor fuera de rango (> 365) devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 30)
        resp = self._put(client, 366)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["remember_me_days"] == 30


# ─────────────────────────── audit_max_entries ─────────────────────

class TestApiConfigPutAuditMaxEntries:
    """PUT /api/config → web_admin.audit_max_entries aplicado en tiempo de ejecución."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"audit_max_entries": value}})

    def test_valid_applied(self, client, admin):
        _login(client)
        self._put(client, 1000)
        assert admin._AUDIT_MAX_ENTRIES == 1000

    def test_boundary_min(self, client, admin):
        _login(client)
        self._put(client, 10)
        assert admin._AUDIT_MAX_ENTRIES == 10

    def test_boundary_max(self, client, admin):
        _login(client)
        self._put(client, 10000)
        assert admin._AUDIT_MAX_ENTRIES == 10000

    def test_below_min_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, 9).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_above_max_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, 10001).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_zero_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, 0).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_negative_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, -100).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_string_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, "1000").status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_float_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, 500.5).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_null_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, None).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_bool_true_rejected(self, client, admin):
        """JSON true no debe aplicarse como entero 1 (bool es subclase de int en Python)."""
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, True).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_bool_false_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, False).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_dict_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        assert self._put(client, {"value": 500}).status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        client.put("/api/config", json={})
        assert admin._AUDIT_MAX_ENTRIES == 500

    # --- disk tests: invalid value returns 400 and does not write config.json ---

    def test_string_does_not_corrupt_disk(self, client, config_dir):
        """Una cadena devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 500)
        resp = self._put(client, "1000")
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["audit_max_entries"] == 500

    def test_null_does_not_corrupt_disk(self, client, config_dir):
        """null devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 500)
        resp = self._put(client, None)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["audit_max_entries"] == 500

    def test_below_min_does_not_corrupt_disk(self, client, config_dir):
        """Valor fuera de rango (< 10) devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 500)
        resp = self._put(client, 9)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["audit_max_entries"] == 500

    def test_above_max_does_not_corrupt_disk(self, client, config_dir):
        """Valor fuera de rango (> 10000) devuelve 400 y no corrompe config.json."""
        _login(client)
        self._put(client, 500)
        resp = self._put(client, 10001)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["audit_max_entries"] == 500


# ───────────────────────────────── lang ────────────────────────────

class TestApiConfigPutLang:
    """PUT /api/config → web_admin.lang aplicado en tiempo de ejecución."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"lang": value}})

    def test_valid_lang_applied(self, client, admin):
        _login(client)
        self._put(client, _VALID_LANG)
        assert admin._default_lang == _VALID_LANG

    def test_unsupported_lang_ignored(self, client, admin):
        _login(client)
        original = admin._default_lang
        self._put(client, _INVALID_LANG)
        assert admin._default_lang == original

    def test_empty_string_ignored(self, client, admin):
        _login(client)
        original = admin._default_lang
        self._put(client, "")
        assert admin._default_lang == original

    def test_non_string_type_ignored(self, client, admin):
        _login(client)
        original = admin._default_lang
        self._put(client, 42)
        assert admin._default_lang == original

    def test_null_ignored(self, client, admin):
        _login(client)
        original = admin._default_lang
        self._put(client, None)
        assert admin._default_lang == original

    def test_absent_unchanged(self, client, admin):
        _login(client)
        original = admin._default_lang
        client.put("/api/config", json={})
        assert admin._default_lang == original


# ──────────────────────────── dark_mode ────────────────────────────

class TestApiConfigPutDarkMode:
    """PUT /api/config → web_admin.dark_mode aplicado en tiempo de ejecución."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"dark_mode": value}})

    def test_true_applied(self, client, admin):
        _login(client)
        admin._default_dark_mode = False
        self._put(client, True)
        assert admin._default_dark_mode is True

    def test_false_applied(self, client, admin):
        _login(client)
        admin._default_dark_mode = True
        self._put(client, False)
        assert admin._default_dark_mode is False

    def test_string_ignored(self, client, admin):
        _login(client)
        admin._default_dark_mode = False
        self._put(client, "true")
        assert admin._default_dark_mode is False

    def test_int_ignored(self, client, admin):
        _login(client)
        admin._default_dark_mode = False
        self._put(client, 1)
        assert admin._default_dark_mode is False

    def test_null_ignored(self, client, admin):
        _login(client)
        admin._default_dark_mode = False
        self._put(client, None)
        assert admin._default_dark_mode is False

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._default_dark_mode = True
        client.put("/api/config", json={})
        assert admin._default_dark_mode is True


# ─────────────────── Clave web_admin — casos borde ─────────────────

class TestApiConfigPutWebAdminKey:
    """Casos borde para la clave web_admin en el payload."""

    def test_web_admin_null_is_graceful(self, client):
        _login(client)
        resp = client.put("/api/config", json={"web_admin": None})
        assert resp.status_code == 200

    def test_web_admin_absent_is_graceful(self, client):
        _login(client)
        resp = client.put("/api/config", json={"daemon": {"timer_check": 300}})
        assert resp.status_code == 200

    def test_web_admin_null_leaves_runtime_state_unchanged(self, client, admin):
        _login(client)
        before = {
            'lang': admin._default_lang,
            'dark_mode': admin._default_dark_mode,
            'secure_cookies': admin._secure_cookies,
            'remember_me_days': admin._REMEMBER_ME_DAYS,
            'audit_max_entries': admin._AUDIT_MAX_ENTRIES,
        }
        client.put("/api/config", json={"web_admin": None})
        assert admin._default_lang == before['lang']
        assert admin._default_dark_mode == before['dark_mode']
        assert admin._secure_cookies == before['secure_cookies']
        assert admin._REMEMBER_ME_DAYS == before['remember_me_days']
        assert admin._AUDIT_MAX_ENTRIES == before['audit_max_entries']


# ─────────────────────────── Inyección ─────────────────────────────

class TestApiConfigPutInjection:
    """Robustez frente a entradas adversariales e intentos de inyección."""

    def test_xss_payload_in_lang_not_applied(self, client, admin):
        _login(client)
        original = admin._default_lang
        client.put("/api/config", json={"web_admin": {"lang": "<script>alert(1)</script>"}})
        assert admin._default_lang == original

    def test_path_traversal_in_lang_not_applied(self, client, admin):
        _login(client)
        original = admin._default_lang
        client.put("/api/config", json={"web_admin": {"lang": "../../etc/passwd"}})
        assert admin._default_lang == original

    def test_very_long_lang_string_not_applied(self, client, admin):
        _login(client)
        original = admin._default_lang
        client.put("/api/config", json={"web_admin": {"lang": "x" * 10_000}})
        assert admin._default_lang == original

    def test_nosql_operator_in_remember_me_days_rejected(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        resp = client.put("/api/config", json={"web_admin": {"remember_me_days": {"$gt": 0}}})
        assert resp.status_code == 400
        assert admin._REMEMBER_ME_DAYS == 30

    def test_nosql_operator_in_audit_max_entries_rejected(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        resp = client.put("/api/config", json={"web_admin": {"audit_max_entries": {"$ne": 0}}})
        assert resp.status_code == 400
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_list_in_secure_cookies_ignored(self, client, admin):
        _login(client)
        admin._secure_cookies = False
        client.put("/api/config", json={"web_admin": {"secure_cookies": [True]}})
        assert admin._secure_cookies is False

    def test_arbitrary_string_values_saved_safely_as_json(self, client, config_dir):
        """Valores arbitrarios de admins se guardan en JSON (no se ejecutan)."""
        _login(client)
        payload = "<img src=x onerror=alert(1)>"
        resp = client.put("/api/config", json={"custom_key": payload})
        assert resp.status_code == 200
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f).get("custom_key") == payload


# ──────────────────────────── Schema ───────────────────────────────

class TestApiConfigSchema:
    """GET /api/config/schema."""

    def test_schema_returns_200(self, client):
        _login(client)
        assert client.get("/api/config/schema").status_code == 200

    def test_schema_returns_dict(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        assert isinstance(data, dict)

    def test_schema_requires_auth(self, client):
        assert client.get("/api/config/schema").status_code == 302

    def test_schema_bool_fields_present(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        for field in ('web_admin|public_status', 'web_admin|pw_require_upper',
                      'web_admin|pw_require_digit', 'web_admin|pw_require_symbol'):
            assert field in data, f"Missing schema field: {field}"
            assert data[field].get('type') == 'bool'
            assert isinstance(data[field].get('default'), bool)

    def test_schema_int_fields_present(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        for field in ('web_admin|remember_me_days', 'web_admin|audit_max_entries',
                      'web_admin|status_refresh_secs'):
            assert field in data, f"Missing schema field: {field}"
            assert 'min' in data[field] and 'max' in data[field]

    def test_schema_status_lang_options(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        assert 'web_admin|status_lang' in data
        opts = data['web_admin|status_lang'].get('options', [])
        assert '' in opts
        for lang in SUPPORTED_LANGS:
            assert lang in opts

    def test_schema_no_crash_on_instance_attrs(self, client):
        """Regression: getattr(type(wa), attr) crashed for instance-only attrs."""
        _login(client)
        resp = client.get("/api/config/schema")
        assert resp.status_code == 200
        assert resp.get_json() is not None

    def test_schema_default_page_size_present(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        assert "web_admin|default_page_size" in data

    def test_schema_default_page_size_has_options_int_list(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        field = data["web_admin|default_page_size"]
        assert "options_int" in field
        assert isinstance(field["options_int"], list)
        assert len(field["options_int"]) > 0

    def test_schema_default_page_size_options_include_standard_sizes(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        opts = data["web_admin|default_page_size"]["options_int"]
        for size in (25, 50, 100, 200):
            assert size in opts, f"Standard page size {size} missing from options_int"

    def test_schema_default_page_size_options_include_zero(self, client):
        """0 represents the 'All rows' option and must be present."""
        _login(client)
        data = client.get("/api/config/schema").get_json()
        assert 0 in data["web_admin|default_page_size"]["options_int"]

    def test_schema_default_page_size_has_default_matching_instance(self, client, admin):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        field = data["web_admin|default_page_size"]
        assert "default" in field
        assert field["default"] == admin._DEFAULT_PAGE_SIZE

    def test_schema_audit_sort_present_with_options(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        assert "web_admin|audit_sort" in data
        opts = data["web_admin|audit_sort"].get("options", [])
        for col in ("time", "event", "user", "ip"):
            assert col in opts, f"audit_sort option '{col}' missing"

    def test_schema_pw_int_fields_have_min_max(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        for field in ("web_admin|pw_min_len", "web_admin|pw_max_len"):
            assert field in data
            assert "min" in data[field] and "max" in data[field]

    def test_schema_proxy_count_present(self, client):
        _login(client)
        data = client.get("/api/config/schema").get_json()
        assert "web_admin|proxy_count" in data
        field = data["web_admin|proxy_count"]
        assert field["min"] == 0 and field["max"] == 10


# ─────────────────────── default_page_size ─────────────────────────

class TestApiConfigPutDefaultPageSize:
    """PUT /api/config → web_admin.default_page_size aplicado en tiempo de ejecución."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"default_page_size": value}})

    def test_valid_applied(self, client, admin):
        _login(client)
        self._put(client, 50)
        assert admin._DEFAULT_PAGE_SIZE == 50

    def test_boundary_min_zero(self, client, admin):
        """0 significa 'Todos' y es el valor mínimo válido."""
        _login(client)
        self._put(client, 0)
        assert admin._DEFAULT_PAGE_SIZE == 0

    def test_boundary_max(self, client, admin):
        _login(client)
        self._put(client, 200)
        assert admin._DEFAULT_PAGE_SIZE == 200

    def test_above_max_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, 201)
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_negative_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, -1)
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_string_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, "50")
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_float_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, 25.5)
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_null_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, None)
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_bool_true_not_treated_as_int(self, client, admin):
        """bool es subclase de int en Python — True no debe valer como 1."""
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, True)
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_bool_false_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, False)
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_dict_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, {"value": 25})
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_list_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        self._put(client, [25])
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        client.put("/api/config", json={})
        assert admin._DEFAULT_PAGE_SIZE == 25

    def test_nosql_operator_ignored(self, client, admin):
        _login(client)
        admin._DEFAULT_PAGE_SIZE = 25
        client.put("/api/config", json={"web_admin": {"default_page_size": {"$gt": 0}}})
        assert admin._DEFAULT_PAGE_SIZE == 25

    # --- disk safety: invalid values must not corrupt config.json ---

    def test_above_max_does_not_corrupt_disk(self, client, config_dir):
        _login(client)
        self._put(client, 25)
        resp = self._put(client, 201)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["default_page_size"] == 25

    def test_negative_does_not_corrupt_disk(self, client, config_dir):
        _login(client)
        self._put(client, 25)
        resp = self._put(client, -1)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["default_page_size"] == 25

    def test_string_does_not_corrupt_disk(self, client, config_dir):
        _login(client)
        self._put(client, 25)
        resp = self._put(client, "50")
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["default_page_size"] == 25

    def test_null_does_not_corrupt_disk(self, client, config_dir):
        _login(client)
        self._put(client, 25)
        resp = self._put(client, None)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["default_page_size"] == 25

    def test_bool_does_not_corrupt_disk(self, client, config_dir):
        _login(client)
        self._put(client, 25)
        resp = self._put(client, True)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["default_page_size"] == 25

    def test_valid_value_saved_to_disk(self, client, config_dir):
        _login(client)
        self._put(client, 100)
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["default_page_size"] == 100

    def test_zero_saved_to_disk(self, client, config_dir):
        _login(client)
        self._put(client, 0)
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["default_page_size"] == 0

    def test_returns_ok_on_valid(self, client):
        _login(client)
        resp = self._put(client, 50)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


# ─────────────────────────── page_sizes ────────────────────────────

class TestApiConfigPutPageSizes:
    """PUT /api/config → web_admin.page_sizes — saneamiento y seguridad."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"page_sizes": value}})

    def _saved(self, config_dir):
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            return json.load(f).get("web_admin", {}).get("page_sizes")

    _DEFAULT = [25, 50, 100, 200, 0]

    # --- happy path ---

    def test_valid_array_saved(self, client, config_dir):
        _login(client)
        self._put(client, [10, 25, 50])
        assert self._saved(config_dir) == [10, 25, 50]

    def test_standard_defaults_saved(self, client, config_dir):
        _login(client)
        self._put(client, [25, 50, 100, 200, 0])
        assert self._saved(config_dir) == [25, 50, 100, 200, 0]

    def test_zero_kept_as_all_option(self, client, config_dir):
        """0 representa 'Todos' y debe conservarse."""
        _login(client)
        self._put(client, [25, 50, 0])
        assert self._saved(config_dir) == [25, 50, 0]

    def test_only_zero_saved(self, client, config_dir):
        """Un array con solo 0 (= Todos) es válido."""
        _login(client)
        self._put(client, [0])
        assert self._saved(config_dir) == [0]

    def test_returns_ok_on_valid(self, client):
        _login(client)
        resp = self._put(client, [25, 50, 100])
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    # --- tipo incorrecto del campo completo (no-lista) → 400 ---

    def test_non_array_string_rejected(self, client):
        _login(client)
        assert self._put(client, "25,50,100").status_code == 400

    def test_non_array_int_rejected(self, client):
        _login(client)
        assert self._put(client, 25).status_code == 400

    def test_non_array_null_rejected(self, client):
        _login(client)
        assert self._put(client, None).status_code == 400

    def test_non_array_bool_rejected(self, client):
        _login(client)
        assert self._put(client, True).status_code == 400

    def test_non_array_dict_rejected(self, client):
        _login(client)
        assert self._put(client, {"25": 25}).status_code == 400

    # --- elementos inválidos dentro del array → 400 ---

    def test_string_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, "50", 100]).status_code == 400

    def test_negative_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, -1, 50]).status_code == 400

    def test_bool_elements_rejected(self, client):
        """True/False son int en Python; deben ser rechazados explícitamente."""
        _login(client)
        assert self._put(client, [25, True, False, 50]).status_code == 400

    def test_float_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, 50.5, 100]).status_code == 400

    def test_null_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, None, 50]).status_code == 400

    def test_dict_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, {"value": 50}, 100]).status_code == 400

    def test_nested_array_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, [50], 100]).status_code == 400

    # --- array vacío o completamente inválido → 400 ---

    def test_empty_array_rejected(self, client):
        """Array vacío no tiene elementos válidos: debe rechazarse con 400."""
        _login(client)
        assert self._put(client, []).status_code == 400

    def test_all_invalid_elements_rejected(self, client):
        _login(client)
        assert self._put(client, ["nope", None, True, -1, 3.14, {}]).status_code == 400

    def test_invalid_array_returns_error_json(self, client):
        """Elementos inválidos devuelven JSON con clave error."""
        _login(client)
        resp = self._put(client, ["nope", True, -5])
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    # --- campo ausente del payload ---

    def test_absent_from_payload_not_written(self, client, config_dir):
        """Si page_sizes no se envía, no debe aparecer en config.json."""
        _login(client)
        client.put("/api/config", json={"web_admin": {}})
        assert "page_sizes" not in (self._saved(config_dir) or {})

    # --- seguridad: inyección dentro del array → 400 (string/dict no son enteros) ---

    def test_xss_string_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, "<script>alert(1)</script>", 50]).status_code == 400

    def test_sql_injection_string_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, "1; DROP TABLE users;--", 50]).status_code == 400

    def test_nosql_operator_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, {"$gt": 0}, 50]).status_code == 400

    def test_path_traversal_string_elements_rejected(self, client):
        _login(client)
        assert self._put(client, [25, "../../etc/passwd", 100]).status_code == 400

    # --- límites ---

    def test_large_array_of_valid_ints_accepted(self, client):
        """Un array grande de enteros válidos no debe colapsar el servidor."""
        _login(client)
        resp = self._put(client, list(range(1, 201)))
        assert resp.status_code == 200

    def test_very_large_single_value_accepted(self, client, config_dir):
        """No hay límite por valor individual — valores grandes se conservan."""
        _login(client)
        self._put(client, [25, 999999, 50])
        assert self._saved(config_dir) == [25, 999999, 50]

    def test_duplicate_values_preserved(self, client, config_dir):
        _login(client)
        self._put(client, [25, 25, 50])
        assert self._saved(config_dir) == [25, 25, 50]

    def test_mixed_valid_and_invalid_rejected(self, client):
        """Array con mezcla de enteros válidos e inválidos → 400, nada guardado."""
        _login(client)
        assert self._put(client, [10, "bad", 25, None, True, -5, 50, 3.14]).status_code == 400

    # --- interacción con default_page_size ---

    def test_page_sizes_and_default_page_size_saved_together(self, client, config_dir):
        _login(client)
        client.put("/api/config", json={
            "web_admin": {"page_sizes": [10, 25, 50], "default_page_size": 10}
        })
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            wa = json.load(f)["web_admin"]
        assert wa["page_sizes"] == [10, 25, 50]
        assert wa["default_page_size"] == 10


# ─────────────────────────── proxy_count ───────────────────────────

class TestApiConfigPutProxyCount:
    """PUT /api/config → web_admin.proxy_count aplicado en tiempo de ejecución."""

    def _put(self, client, value):
        return client.put("/api/config", json={"web_admin": {"proxy_count": value}})

    def test_valid_applied(self, client, admin):
        _login(client)
        self._put(client, 1)
        assert admin._proxy_count == 1

    def test_boundary_min_zero(self, client, admin):
        _login(client)
        self._put(client, 0)
        assert admin._proxy_count == 0

    def test_boundary_max(self, client, admin):
        _login(client)
        self._put(client, 10)
        assert admin._proxy_count == 10

    def test_above_max_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        assert self._put(client, 11).status_code == 400
        assert admin._proxy_count == 0

    def test_negative_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        assert self._put(client, -1).status_code == 400
        assert admin._proxy_count == 0

    def test_string_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        assert self._put(client, "2").status_code == 400
        assert admin._proxy_count == 0

    def test_float_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        assert self._put(client, 1.5).status_code == 400
        assert admin._proxy_count == 0

    def test_null_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        assert self._put(client, None).status_code == 400
        assert admin._proxy_count == 0

    def test_bool_true_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        assert self._put(client, True).status_code == 400
        assert admin._proxy_count == 0

    def test_bool_false_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        assert self._put(client, False).status_code == 400
        assert admin._proxy_count == 0

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._proxy_count = 2
        client.put("/api/config", json={})
        assert admin._proxy_count == 2

    def test_above_max_does_not_corrupt_disk(self, client, config_dir):
        _login(client)
        self._put(client, 0)
        resp = self._put(client, 11)
        assert resp.status_code == 400
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["proxy_count"] == 0

    def test_nosql_operator_rejected(self, client, admin):
        _login(client)
        admin._proxy_count = 0
        resp = client.put("/api/config", json={"web_admin": {"proxy_count": {"$gt": 0}}})
        assert resp.status_code == 400
        assert admin._proxy_count == 0
