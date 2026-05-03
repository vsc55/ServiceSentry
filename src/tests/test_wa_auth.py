#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for authentication, remember-me, dark mode and config dark-mode."""

import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Authentication ───────────────────────

class TestAuthentication:
    """Login / logout flow."""

    def test_root_redirects_to_login(self, client):
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b"ServiceSentry" in resp.data

    def test_login_success(self, client):
        resp = _login(client)
        assert resp.status_code == 200
        # After following redirect we should see the dashboard
        assert b"modules-container" in resp.data

    def test_login_wrong_password(self, client):
        resp = _login(client, password="wrong")
        assert resp.status_code == 200
        assert "Invalid credentials" in resp.data.decode()

    def test_login_wrong_username(self, client):
        resp = _login(client, username="hacker")
        assert resp.status_code == 200
        assert "Invalid credentials" in resp.data.decode()

    def test_login_empty_fields(self, client):
        resp = _login(client, username="", password="")
        assert resp.status_code == 200
        assert "Invalid credentials" in resp.data.decode()

    def test_logout(self, client):
        _login(client)
        resp = client.get("/logout")
        assert resp.status_code == 302
        # After logout, dashboard must redirect to login
        resp2 = client.get("/")
        assert resp2.status_code == 302
        assert "/login" in resp2.headers["Location"]

    def test_already_logged_in_skips_login_page(self, client):
        _login(client)
        resp = client.get("/login")
        assert resp.status_code == 302  # redirects to dashboard

    def test_dashboard_accessible_after_login(self, client):
        _login(client)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_session_stores_user_info(self, client):
        """Login populates session with username, role and display_name."""
        _login(client)
        resp = client.get("/api/me")
        data = resp.get_json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"


# ──────────────────────────── Remember me ──────────────────────────

class TestRememberMe:
    """Persistent session via 'remember me' checkbox."""

    def test_login_page_has_remember_me(self, client):
        """Login form contains a 'remember me' checkbox."""
        html = client.get("/login").data
        assert b'name="remember_me"' in html

    def test_login_without_remember_me(self, client):
        """Without remember me the session is not permanent."""
        _login(client)
        with client.session_transaction() as s:
            assert s.permanent is False

    def test_login_with_remember_me(self, client):
        """Checking remember me makes the session permanent."""
        client.post(
            "/login",
            data={"username": "admin", "password": "secret",
                  "remember_me": "on"},
            follow_redirects=True,
        )
        with client.session_transaction() as s:
            assert s.permanent is True

    def test_secret_key_persisted(self, admin):
        """Secret key is saved to a file in the config dir."""
        path = admin._secret_key_path
        assert os.path.isfile(path)
        with open(path, encoding='utf-8') as fh:
            key = fh.read().strip()
        assert key == admin.app.secret_key

    def test_secret_key_reused(self, config_dir, var_dir):
        """Creating a second WebAdmin instance reuses the same key."""
        wa1 = WebAdmin(config_dir, "admin", "secret", var_dir)
        wa2 = WebAdmin(config_dir, "admin", "secret", var_dir)
        assert wa1.app.secret_key == wa2.app.secret_key


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
            "username": "dmuser", "password": "x", "role": "viewer",
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
