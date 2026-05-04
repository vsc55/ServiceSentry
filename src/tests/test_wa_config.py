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
        assert data["telegram"]["token"] == "test-token-123"


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

    def test_below_min_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, 0)
        assert admin._REMEMBER_ME_DAYS == 30

    def test_above_max_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, 366)
        assert admin._REMEMBER_ME_DAYS == 30

    def test_negative_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, -1)
        assert admin._REMEMBER_ME_DAYS == 30

    def test_string_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, "60")
        assert admin._REMEMBER_ME_DAYS == 30

    def test_float_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, 60.5)
        assert admin._REMEMBER_ME_DAYS == 30

    def test_null_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, None)
        assert admin._REMEMBER_ME_DAYS == 30

    def test_bool_true_not_treated_as_int(self, client, admin):
        """JSON true no debe aplicarse como entero 1 (bool es subclase de int en Python)."""
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, True)
        assert admin._REMEMBER_ME_DAYS == 30

    def test_bool_false_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, False)
        assert admin._REMEMBER_ME_DAYS == 30

    def test_dict_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, {"value": 30})
        assert admin._REMEMBER_ME_DAYS == 30

    def test_list_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, [30])
        assert admin._REMEMBER_ME_DAYS == 30

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        client.put("/api/config", json={})
        assert admin._REMEMBER_ME_DAYS == 30

    # --- file-content tests: invalid values must not corrupt config.json ---

    def test_string_saves_current_to_disk(self, client, admin, config_dir):
        """Enviar una cadena para remember_me_days no corrompe el fichero."""
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, "60")
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["remember_me_days"] == 30

    def test_null_saves_current_to_disk(self, client, admin, config_dir):
        """Enviar null para remember_me_days no corrompe el fichero."""
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, None)
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["remember_me_days"] == 30

    def test_below_min_saves_current_to_disk(self, client, admin, config_dir):
        """Valor fuera de rango (< 1) no se guarda: se sustituye por el valor actual."""
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, 0)
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["remember_me_days"] == 30

    def test_above_max_saves_current_to_disk(self, client, admin, config_dir):
        """Valor fuera de rango (> 365) no se guarda: se sustituye por el valor actual."""
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        self._put(client, 366)
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

    def test_below_min_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, 9)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_above_max_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, 10001)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_zero_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, 0)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_negative_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, -100)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_string_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, "1000")
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_float_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, 500.5)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_null_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, None)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_bool_true_not_treated_as_int(self, client, admin):
        """JSON true no debe aplicarse como entero 1 (bool es subclase de int en Python)."""
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, True)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_bool_false_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, False)
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_dict_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, {"value": 500})
        assert admin._AUDIT_MAX_ENTRIES == 500

    def test_absent_unchanged(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        client.put("/api/config", json={})
        assert admin._AUDIT_MAX_ENTRIES == 500

    # --- file-content tests: invalid values must not corrupt config.json ---

    def test_string_saves_current_to_disk(self, client, admin, config_dir):
        """Enviar una cadena para audit_max_entries no corrompe el fichero."""
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, "1000")
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["audit_max_entries"] == 500

    def test_null_saves_current_to_disk(self, client, admin, config_dir):
        """Enviar null para audit_max_entries no corrompe el fichero."""
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, None)
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["audit_max_entries"] == 500

    def test_below_min_saves_current_to_disk(self, client, admin, config_dir):
        """Valor fuera de rango (< 10) no se guarda: se sustituye por el valor actual."""
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, 9)
        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            assert json.load(f)["web_admin"]["audit_max_entries"] == 500

    def test_above_max_saves_current_to_disk(self, client, admin, config_dir):
        """Valor fuera de rango (> 10000) no se guarda: se sustituye por el valor actual."""
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        self._put(client, 10001)
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

    def test_nosql_operator_in_remember_me_days_ignored(self, client, admin):
        _login(client)
        admin._REMEMBER_ME_DAYS = 30
        client.put("/api/config", json={"web_admin": {"remember_me_days": {"$gt": 0}}})
        assert admin._REMEMBER_ME_DAYS == 30

    def test_nosql_operator_in_audit_max_entries_ignored(self, client, admin):
        _login(client)
        admin._AUDIT_MAX_ENTRIES = 500
        client.put("/api/config", json={"web_admin": {"audit_max_entries": {"$ne": 0}}})
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
