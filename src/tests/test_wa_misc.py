#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Telegram test endpoint, internationalisation and UI reorganisation."""

import unittest.mock

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import check_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Telegram Test ────────────────────────

class TestTelegramTest:
    """Telegram test-message endpoint tests."""

    def test_requires_auth(self, client):
        """Unauthenticated request redirects to login."""
        resp = client.post("/api/telegram/test", json={
            "token": "x", "chat_id": "y",
        })
        assert resp.status_code == 302

    def test_viewer_denied(self, client):
        """Viewer role cannot send test messages."""
        _login(client)
        client.post("/api/users", json={
            "username": "v1", "password": "v", "role": "viewer",
        })
        client.get("/logout")
        _login(client, "v1", "v")
        resp = client.post("/api/telegram/test", json={
            "token": "x", "chat_id": "y",
        })
        assert resp.status_code == 403

    def test_missing_fields(self, client):
        """Returns 400 when body is empty."""
        _login(client)
        resp = client.post("/api/telegram/test", json={})
        assert resp.status_code == 400

    def test_missing_token(self, client):
        """Returns 400 when token is empty."""
        _login(client)
        resp = client.post("/api/telegram/test", json={"chat_id": "123"})
        assert resp.status_code == 400

    def test_missing_chat_id(self, client):
        """Returns 400 when chat_id is empty."""
        _login(client)
        resp = client.post("/api/telegram/test", json={"token": "abc"})
        assert resp.status_code == 400

    def test_success(self, client):
        """Returns ok when the Telegram API returns 200."""
        _login(client)
        with unittest.mock.patch("requests.post") as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            resp = client.post("/api/telegram/test", json={
                "token": "123:ABC", "chat_id": "456",
            })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_api_error(self, client):
        """Returns 502 when the Telegram API rejects the request."""
        _login(client)
        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 401
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"description": "Unauthorized"}
        with unittest.mock.patch("requests.post", return_value=mock_resp):
            resp = client.post("/api/telegram/test", json={
                "token": "bad", "chat_id": "456",
            })
        assert resp.status_code == 502
        assert "Unauthorized" in resp.get_json()["error"]

    def test_network_error(self, client):
        """Returns 502 on network exceptions."""
        _login(client)
        with unittest.mock.patch("requests.post", side_effect=Exception("timeout")):
            resp = client.post("/api/telegram/test", json={
                "token": "123:ABC", "chat_id": "456",
            })
        assert resp.status_code == 502
        assert "timeout" in resp.get_json()["error"]

    def test_non_json_error_response(self, client):
        """Returns 502 with generic message for non-JSON error body."""
        _login(client)
        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 500
        mock_resp.headers = {"content-type": "text/html"}
        with unittest.mock.patch("requests.post", return_value=mock_resp):
            resp = client.post("/api/telegram/test", json={
                "token": "123:ABC", "chat_id": "456",
            })
        assert resp.status_code == 502
        assert "500" in resp.get_json()["error"]

    def test_dashboard_has_test_button(self, client):
        """Dashboard HTML includes the Telegram test button."""
        _login(client)
        resp = client.get("/")
        assert b"btnTestTelegram" in resp.data
        assert b"testTelegram()" in resp.data


# ──────────────────────────── Internationalisation ─────────────────

class TestI18n:
    """Multi-language support tests."""

    def test_default_language_is_english(self, client):
        _login(client)
        resp = client.get("/api/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_switch_to_spanish(self, client):
        _login(client)
        client.get("/lang/es_ES")
        resp = client.get("/api/me")
        assert resp.get_json()["lang"] == "es_ES"

    def test_switch_back_to_english(self, client):
        _login(client)
        client.get("/lang/es_ES")
        client.get("/lang/en_EN")
        resp = client.get("/api/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_invalid_language_ignored(self, client):
        _login(client)
        client.get("/lang/fr")
        resp = client.get("/api/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_spanish_error_messages(self, client):
        """Backend errors are returned in the selected language."""
        client.get("/lang/es_ES")
        resp = _login(client, password="wrong")
        assert "Credenciales incorrectas" in resp.data.decode()

    def test_login_page_renders_in_english(self, client):
        resp = client.get("/login")
        assert b"Sign In" in resp.data

    def test_login_page_renders_in_spanish(self, client):
        client.get("/lang/es_ES")
        resp = client.get("/login")
        assert "Entrar".encode() in resp.data

    def test_lang_switch_without_auth(self, client):
        """Language can be switched on the login page without auth."""
        resp = client.get("/lang/es_ES", follow_redirects=True)
        assert resp.status_code == 200
        assert "Entrar".encode() in resp.data

    def test_api_errors_in_spanish(self, client):
        """API validation errors respect the session language."""
        _login(client)
        client.get("/lang/es_ES")
        resp = client.put("/api/modules", content_type="application/json")
        assert resp.status_code == 400
        assert "JSON" in resp.get_json()["error"]

    def test_lang_persisted_to_user_record(self, admin, client):
        """Switching language saves preference to user profile."""
        _login(client)
        client.get("/lang/es_ES")
        assert admin._users["admin"].get("lang") == "es_ES"

    def test_lang_loaded_on_login(self, admin, client):
        """User's saved language is loaded on login."""
        admin._users["admin"]["lang"] = "es_ES"
        _login(client)
        resp = client.get("/api/me")
        assert resp.get_json()["lang"] == "es_ES"

    def test_global_default_lang(self, config_dir, var_dir):
        """WebAdmin respects the global default_lang parameter."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir, default_lang="es_ES")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        resp = c.get("/api/me")
        assert resp.get_json()["lang"] == "es_ES"

    def test_global_default_invalid_falls_back(self, config_dir, var_dir):
        """Invalid default_lang falls back to DEFAULT_LANG ('en_EN')."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir, default_lang="xx")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        resp = c.get("/api/me")
        assert resp.get_json()["lang"] == "en_EN"

    def test_user_lang_in_users_list(self, client):
        """Language preference appears in the users API."""
        _login(client)
        client.get("/lang/es_ES")
        users = client.get("/api/users").get_json()
        assert users["admin"]["lang"] == "es_ES"

    def test_admin_can_set_user_lang(self, client):
        """Admin can update another user's language via PUT."""
        _login(client)
        client.post("/api/users", json={
            "username": "languser", "password": "x", "role": "viewer",
        })
        resp = client.put("/api/users/languser", json={"lang": "es_ES"})
        assert resp.status_code == 200
        users = client.get("/api/users").get_json()
        assert users["languser"]["lang"] == "es_ES"

    def test_create_user_with_lang(self, client):
        """Creating a user with a specific language saves it."""
        _login(client)
        resp = client.post("/api/users", json={
            "username": "langcreate", "password": "x",
            "role": "viewer", "lang": "es_ES",
        })
        assert resp.status_code == 201
        users = client.get("/api/users").get_json()
        assert users["langcreate"]["lang"] == "es_ES"

    def test_create_user_without_lang(self, client):
        """Creating a user without lang defaults to empty (system default)."""
        _login(client)
        resp = client.post("/api/users", json={
            "username": "nolang", "password": "x", "role": "viewer",
        })
        assert resp.status_code == 201
        users = client.get("/api/users").get_json()
        assert users["nolang"]["lang"] == ""

    def test_update_own_lang_updates_session(self, client):
        """Editing own user's language updates the active session."""
        _login(client)
        resp = client.put("/api/users/admin", json={"lang": "es_ES"})
        assert resp.status_code == 200
        me = client.get("/api/me").get_json()
        assert me["lang"] == "es_ES"

    def test_save_config_updates_default_lang(self, admin, client):
        """Saving config.json with web_admin.lang updates runtime default."""
        _login(client)
        resp = client.put("/api/config", json={
            "web_admin": {"lang": "es_ES"},
        })
        assert resp.status_code == 200
        assert admin._default_lang == "es_ES"

    def test_save_config_invalid_lang_ignored(self, admin, client):
        """Saving config.json with invalid lang keeps current default."""
        _login(client)
        client.put("/api/config", json={
            "web_admin": {"lang": "xx"},
        })
        assert admin._default_lang == "en_EN"

    def test_dashboard_exposes_default_lang(self, client):
        """Dashboard HTML includes the system default language."""
        _login(client)
        resp = client.get("/")
        assert b"SYSTEM_DEFAULT_LANG" in resp.data

    def test_dashboard_exposes_supported_langs(self, client):
        """Dashboard JS has the list of supported languages."""
        _login(client)
        resp = client.get("/")
        assert b"SUPPORTED_LANGS" in resp.data


# ──────────────────────────── UI reorganisation ────────────────────

class TestUIReorganisation:
    """Verify the user-menu dropdown, password modals and users tab."""

    def test_navbar_has_user_dropdown(self, client):
        """Navbar contains a user dropdown menu."""
        _login(client)
        html = client.get("/").data
        assert b"openChangePasswordModal()" in html
        assert b"bi-person-circle" in html

    def test_change_password_modal_exists(self, client):
        """Dashboard contains the change-own-password modal."""
        _login(client)
        html = client.get("/").data
        assert b'id="changePasswordModal"' in html
        assert b'id="btnChangePasswordOk"' in html
        assert b'id="pwCurrent"' in html

    def test_reset_password_modal_exists(self, client):
        """Dashboard contains the admin reset-password modal."""
        _login(client)
        html = client.get("/").data
        assert b'id="resetPasswordModal"' in html
        assert b'id="btnResetPasswordOk"' in html
        assert b'id="rpNewPassword"' in html

    def test_no_inline_password_form_in_users_tab(self, client):
        """The old inline change-password card is no longer in the users tab."""
        _login(client)
        html = client.get("/").data
        assert b'onclick="changeOwnPassword()"' not in html

    def test_users_table_has_reset_icon(self, client):
        """The renderUsers JS produces a reset-password button per row."""
        _login(client)
        html = client.get("/").data
        assert b"openResetPasswordModal(" in html

    def test_reset_password_via_admin_api(self, admin, client):
        """Admin can reset another user's password via PUT /api/users/<u>."""
        _login(client)
        client.post("/api/users", json={
            "username": "resetme", "password": "old", "role": "viewer",
        })
        resp = client.put("/api/users/resetme", json={"password": "brandnew"})
        assert resp.status_code == 200
        assert check_password_hash(
            admin._users["resetme"]["password_hash"], "brandnew"
        )

    def test_language_selector_in_user_menu(self, client):
        """Language options are inside the user dropdown as a submenu."""
        _login(client)
        html = client.get("/").data
        assert b'bi-translate' in html
        assert b'bi-chevron-down' in html
        assert b'/lang/' in html

    def test_dark_mode_toggle_in_user_menu(self, client):
        """Dark mode toggle is present in the user dropdown menu."""
        _login(client)
        html = client.get("/").data
        assert b'id="darkModeSwitch"' in html
        assert b'toggleDarkMode()' in html
