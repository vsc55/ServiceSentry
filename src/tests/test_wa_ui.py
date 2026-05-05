#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UI routes: /, /api/me, /lang/<code>, /theme/<mode>."""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import check_password_hash

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Dark mode ────────────────────────────

class TestDarkMode:
    """Dark mode toggle, persistence and default handling."""

    def test_default_theme_is_light(self, client):
        """Without any config, theme defaults to light."""
        _login(client)
        html = client.get("/").data
        assert b'data-bs-theme="light"' in html

    def test_toggle_to_dark(self, client):
        """Hitting /theme/dark switches the session to dark mode."""
        _login(client)
        client.get("/theme/dark")
        html = client.get("/").data
        assert b'data-bs-theme="dark"' in html

    def test_toggle_back_to_light(self, client):
        """Hitting /theme/light switches back to light mode."""
        _login(client)
        client.get("/theme/dark")
        client.get("/theme/light")
        html = client.get("/").data
        assert b'data-bs-theme="light"' in html

    def test_theme_persisted_to_user(self, admin, client):
        """Theme preference is saved in the user record."""
        _login(client)
        client.get("/theme/dark")
        assert admin._users["admin"]["dark_mode"] is True
        client.get("/theme/light")
        assert admin._users["admin"]["dark_mode"] is False

    def test_theme_loaded_on_login(self, admin, client):
        """User's saved dark_mode preference is restored on login."""
        admin._users["admin"]["dark_mode"] = True
        _login(client)
        html = client.get("/").data
        assert b'data-bs-theme="dark"' in html

    def test_api_me_includes_dark_mode(self, client):
        """GET /api/me includes the dark_mode field."""
        _login(client)
        data = client.get("/api/me").get_json()
        assert "dark_mode" in data
        assert data["dark_mode"] is False

    def test_invalid_theme_ignored(self, client):
        """Invalid theme mode is silently ignored."""
        _login(client)
        client.get("/theme/purple")
        html = client.get("/").data
        assert b'data-bs-theme="light"' in html

    def test_global_default_dark_mode(self, config_dir, var_dir):
        """WebAdmin can be initialised with dark mode as default."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      default_dark_mode=True)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        html = c.get("/").data
        assert b'data-bs-theme="dark"' in html

    def test_save_config_updates_default_dark_mode(self, admin, client):
        """Saving config.json web_admin.dark_mode updates the runtime default."""
        _login(client)
        assert admin._default_dark_mode is False
        client.put("/api/config", json={
            "web_admin": {"dark_mode": True},
        })
        assert admin._default_dark_mode is True

    def test_user_dark_mode_in_users_list(self, admin, client):
        """GET /api/users includes dark_mode for each user."""
        _login(client)
        client.get("/theme/dark")
        users = client.get("/api/users").get_json()
        assert users["admin"]["dark_mode"] is True

    def test_admin_can_set_user_dark_mode(self, admin, client):
        """Admin can set dark_mode for another user via PUT."""
        _login(client)
        client.post("/api/users", json={
            "username": "dmuser", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/dmuser", json={"dark_mode": True})
        assert resp.status_code == 200
        assert admin._users["dmuser"]["dark_mode"] is True


# ──────────────────────────── Config dark mode ─────────────────────

class TestConfigDarkMode:
    """Dark mode field appears in the Configuration tab."""

    def test_config_tab_renders_dark_mode_field(self, client):
        """The config tab JS ensures web_admin.dark_mode is rendered."""
        _login(client)
        html = client.get("/").data
        assert b"configData.web_admin.dark_mode" in html


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
            "username": "languser", "password": "testpass", "role": "viewer",
        })
        resp = client.put("/api/users/languser", json={"lang": "es_ES"})
        assert resp.status_code == 200
        users = client.get("/api/users").get_json()
        assert users["languser"]["lang"] == "es_ES"

    def test_create_user_with_lang(self, client):
        """Creating a user with a specific language saves it."""
        _login(client)
        resp = client.post("/api/users", json={
            "username": "langcreate", "password": "testpass",
            "role": "viewer", "lang": "es_ES",
        })
        assert resp.status_code == 201
        users = client.get("/api/users").get_json()
        assert users["langcreate"]["lang"] == "es_ES"

    def test_create_user_without_lang(self, client):
        """Creating a user without lang defaults to empty (system default)."""
        _login(client)
        resp = client.post("/api/users", json={
            "username": "nolang", "password": "testpass", "role": "viewer",
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
            "username": "resetme", "password": "testpass", "role": "viewer",
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


# ──────────────────────────── Public status page ───────────────────

class TestPublicStatusPage:
    """Tests for the /status public page."""

    def test_status_hidden_by_default(self, client):
        """/status returns 404 when public_status is not enabled."""
        resp = client.get("/status")
        assert resp.status_code == 404

    def test_status_accessible_when_enabled(self, config_dir, var_dir):
        """When public_status=True, /status returns 200."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        resp = c.get("/status")
        assert resp.status_code == 200

    def test_status_no_login_required(self, config_dir, var_dir):
        """The status page is accessible without authentication."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        # No _login() call — should still work
        resp = c.get("/status")
        assert resp.status_code == 200

    def test_status_shows_module_name(self, config_dir, var_dir):
        """The status page renders the module name from status.json."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"Ping" in html or b"ping" in html

    def test_status_shows_check_name(self, config_dir, var_dir):
        """The status page renders individual check names."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"192.168.1.1" in html

    def test_status_overall_pct_100_when_all_ok(self, config_dir, var_dir):
        """Overall percentage is 100% when all checks pass."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data.decode()
        assert "100" in html

    def test_status_shows_all_systems_ok_banner(self, config_dir, var_dir):
        """Banner says 'operational' when all checks pass."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"operational" in html

    def test_status_shows_degraded_banner_on_failure(self, config_dir, tmp_path):
        """Banner shows degraded message when a check fails."""
        import json as _json
        import os
        d = tmp_path / "var"
        d.mkdir()
        status = {"api": {"endpoint": {"status": False, "other_data": {}}}}
        (d / "status.json").write_text(_json.dumps(status), encoding="utf-8")
        wa = WebAdmin(config_dir, "admin", "secret", str(d),
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"Degraded" in html or b"degraded" in html

    def test_status_has_auto_refresh_meta(self, config_dir, var_dir):
        """Page includes JS auto-refresh countdown."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"REFRESH_SECS" in html or b"location.reload" in html

    def test_status_has_login_link(self, config_dir, var_dir):
        """Page contains a link to /login for admins."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"/login" in html

    def test_status_empty_when_no_status_file(self, config_dir, tmp_path):
        """Page renders without error when no status.json exists."""
        d = tmp_path / "emptyvar"
        d.mkdir()
        wa = WebAdmin(config_dir, "admin", "secret", str(d),
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        resp = c.get("/status")
        assert resp.status_code == 200

    def test_status_custom_refresh_secs(self, config_dir, var_dir):
        """Custom refresh interval is embedded in the page."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True, status_refresh_secs=120,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        html = c.get("/status").data
        assert b"120" in html

    def test_status_config_updates_refresh_secs(self, config_dir, var_dir):
        """Saving config.json updates status_refresh_secs at runtime."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        c.put("/api/config", json={"web_admin": {"status_refresh_secs": 300}})
        assert wa._STATUS_REFRESH_SECS == 300

    def test_status_hidden_from_anonymous_when_disabled(self, config_dir, var_dir):
        """When public_status=False, anonymous requests get 404."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=False,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        resp = c.get("/status")
        assert resp.status_code == 404

    def test_status_visible_to_logged_in_when_disabled(self, config_dir, var_dir):
        """When public_status=False, logged-in users can still access /status."""
        wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                      public_status=False,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        _login(c)
        resp = c.get("/status")
        assert resp.status_code == 200
