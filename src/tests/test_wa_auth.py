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

    def test_login_account_disabled(self, admin, client):
        """Disabled account shows the SAME generic error as wrong credentials (anti-enumeration).
        The real reason is recorded only in the audit log."""
        from werkzeug.security import generate_password_hash
        admin._users["disabled_user"] = {
            "password_hash": generate_password_hash("secret", method="pbkdf2:sha256"),
            "role": "viewer",
            "display_name": "Disabled",
            "enabled": False,
        }
        resp = _login(client, username="disabled_user", password="secret")
        assert resp.status_code == 200
        body = resp.data.decode()
        # Anti-enumeration: must NOT reveal the account is disabled
        assert "disabled" not in body.lower()
        # Must show the same generic error as an invalid password
        assert "invalid" in body.lower() or "credentials" in body.lower() or "incorrect" in body.lower()

    def test_login_uses_post_redirect_get(self, client):
        """Failed login returns 302 redirect (PRG pattern), not a direct 200 render."""
        resp = client.post(
            "/login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

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

    def test_dashboard_seeds_config_defaults_from_registry(self, client):
        """The config UI's section defaults come from the registry (spec), not
        hardcoded literals: the rendered page injects CONFIG_REGISTRY_DEFAULTS
        carrying the spec's values (e.g. syslog|udp_port=514)."""
        from lib.config.spec import registry_defaults
        _login(client)
        html = client.get("/").get_data(as_text=True)
        assert "CONFIG_REGISTRY_DEFAULTS" in html
        defs = registry_defaults()
        assert defs["syslog|udp_port"] == 514
        # the registry is the single source — spec, not the template, owns these
        assert "syslog|udp_port" in defs and "notifications|telegram_on_down" in defs

    def test_session_stores_user_info(self, client):
        """Login populates session with username, role and display_name."""
        _login(client)
        resp = client.get("/api/v1/me")
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


# ──────────────────────────── Account lockout ──────────────────────

class TestAccountLockout:
    """Account lockout after N failed login attempts."""

    def _set_lockout(self, admin, max_attempts=3, duration_secs=900):
        admin._LOCKOUT_MAX_ATTEMPTS = max_attempts
        admin._LOCKOUT_DURATION_SECS = duration_secs

    def test_lockout_triggers_after_n_attempts(self, admin, client):
        """After N wrong passwords the account is locked and shows a generic error (anti-enumeration).
        The real reason (account_locked) is recorded only in the audit log."""
        self._set_lockout(admin, max_attempts=3)
        for _ in range(3):
            resp = _login(client, password="wrong")
            assert resp.status_code == 200
        # Next attempt: account is now locked — must NOT reveal lockout status
        resp = _login(client, password="wrong")
        body = resp.data.decode()
        assert "locked" not in body.lower() and "bloqueada" not in body.lower()
        # Must show the generic invalid-credentials error
        assert "invalid" in body.lower() or "credentials" in body.lower() or "incorrect" in body.lower()

    def test_locked_account_rejects_correct_password(self, admin, client):
        """A locked account rejects even the correct password with a generic error."""
        self._set_lockout(admin, max_attempts=2)
        for _ in range(2):
            _login(client, password="wrong")
        resp = _login(client, password="secret")
        body = resp.data.decode()
        # Anti-enumeration: must NOT reveal the account is locked
        assert "locked" not in body.lower() and "bloqueada" not in body.lower()
        # Must not reach the dashboard either (login failed)
        assert "dashboard" not in body.lower()

    def test_lockout_audit_records_reason(self, admin, client):
        """Locked-account login is recorded in the audit log with reason 'account_locked',
        even though the UI only shows a generic message."""
        self._set_lockout(admin, max_attempts=2)
        for _ in range(2):
            _login(client, password="wrong")
        _login(client, password="wrong")  # triggers lockout
        # Audit log must record the real reason for security monitoring
        reasons = [e.get('detail', {}).get('reason', '') for e in admin._audit_log]
        assert 'account_locked' in reasons

    def test_successful_login_resets_failed_attempts(self, admin, client):
        """A successful login clears the failed-attempts counter."""
        self._set_lockout(admin, max_attempts=5)
        for _ in range(3):
            _login(client, password="wrong")
        _login(client, password="secret")
        assert admin._users["admin"].get("_failed_attempts") is None
        assert admin._users["admin"].get("_locked_until") is None

    def test_lockout_disabled_when_max_attempts_zero(self, admin, client):
        """With max_attempts=0 the account is never locked."""
        self._set_lockout(admin, max_attempts=0)
        for _ in range(20):
            _login(client, password="wrong")
        resp = _login(client, password="secret")
        assert b"modules-container" in resp.data

    def test_account_unlocks_after_duration(self, admin, client):
        """After the lockout duration expires the user can log in again."""
        from datetime import datetime, timedelta, timezone
        self._set_lockout(admin, max_attempts=2)
        for _ in range(2):
            _login(client, password="wrong")
        # Backdate the locked_until to simulate expiry
        admin._users["admin"]["_locked_until"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        resp = _login(client, password="secret")
        assert b"modules-container" in resp.data
        assert admin._users["admin"].get("_locked_until") is None

    def test_authenticate_returns_tuple(self, admin):
        """_authenticate() always returns a 2-tuple."""
        with admin.app.test_request_context():
            result = admin._authenticate("admin", "secret")
            assert isinstance(result, tuple) and len(result) == 2
            user, reason = result
            assert user is not None
            assert reason is None

    def test_authenticate_wrong_password_reason(self, admin):
        """Wrong password returns (None, 'invalid_credentials') when lockout not reached."""
        admin._LOCKOUT_MAX_ATTEMPTS = 0
        with admin.app.test_request_context():
            user, reason = admin._authenticate("admin", "wrong")
            assert user is None
            assert reason == "invalid_credentials"

    def test_authenticate_unknown_user_reason(self, admin):
        """Unknown username returns (None, 'user_not_found')."""
        with admin.app.test_request_context():
            user, reason = admin._authenticate("nobody", "x")
            assert user is None
            assert reason == "user_not_found"
