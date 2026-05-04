#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for authentication routes: /login, /logout."""

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
