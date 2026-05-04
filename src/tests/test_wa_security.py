#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security, injection and abuse-resistance tests for the web API."""

import json
import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ────────────────────── Security & injection tests ─────────────────

class TestSecurityInjection:
    """Security, injection, and abuse-resistance tests for the web API."""

    # ── XSS payloads ──────────────────────────────────────────────

    _XSS_PAYLOADS = [
        '<script>alert("xss")</script>',
        '"><img src=x onerror=alert(1)>',
        "'; DROP TABLE users;--",
        '{{7*7}}',                           # SSTI
        '${7*7}',                            # Template injection
        '<svg onload=alert(1)>',
        'javascript:alert(1)',
    ]

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _make_admin(config_dir, var_dir):
        """Create a basic WebAdmin for security tests."""
        wa = WebAdmin(config_dir, "secadmin", "secpass", var_dir)
        wa.app.config["TESTING"] = True
        return wa

    @staticmethod
    def _login(client, user="secadmin", pw="secpass"):
        return client.post(
            "/login", data={"username": user, "password": pw},
            follow_redirects=True,
        )

    @staticmethod
    def _make_multiuser(config_dir, var_dir):
        """Admin + viewer for privilege-escalation tests."""
        users = {
            "secadmin": {
                "password_hash": generate_password_hash("secpass"),
                "role": "admin", "display_name": "Admin",
            },
            "viewer": {
                "password_hash": generate_password_hash("vpass"),
                "role": "viewer", "display_name": "V",
            },
            "editor": {
                "password_hash": generate_password_hash("epass"),
                "role": "editor", "display_name": "E",
            },
        }
        users_path = os.path.join(config_dir, "users.json")
        with open(users_path, "w", encoding="utf-8") as f:
            json.dump(users, f)
        wa = WebAdmin(config_dir, var_dir=var_dir)
        wa.app.config["TESTING"] = True
        return wa

    # ── XSS in user fields ───────────────────────────────────────

    def test_xss_in_username_create(self, config_dir, var_dir):
        """XSS payload in username is stored literally, never executed."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        for payload in self._XSS_PAYLOADS:
            resp = c.post("/api/users", json={
                "username": payload, "password": "testpass", "role": "viewer",
            })
            # Server must not crash; response is 201 or 400/409
            assert resp.status_code in (201, 400, 409)

    def test_xss_in_display_name(self, config_dir, var_dir):
        """XSS payload in display_name does not leak to dashboard HTML."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        payload = '<script>alert("xss")</script>'
        c.post("/api/users", json={
            "username": "xssuser", "password": "testpass", "role": "viewer",
            "display_name": payload,
        })
        html = c.get("/").data.decode()
        # Jinja2 auto-escapes; the raw <script> tag must NOT appear
        assert '<script>alert("xss")</script>' not in html

    def test_xss_in_login_form_username(self, config_dir, var_dir):
        """XSS payload in login username field doesn't reflect unescaped."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        resp = c.post("/login", data={
            "username": '<script>alert(1)</script>',
            "password": "wrong",
        })
        body = resp.data.decode()
        assert '<script>alert(1)</script>' not in body

    # ── SQL-like injection in user endpoints ──────────────────────

    def test_sql_injection_in_username(self, config_dir, var_dir):
        """SQL injection attempts in username don't cause errors."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        payloads = [
            "admin' OR '1'='1",
            "admin'; DROP TABLE users;--",
            "admin\" OR \"1\"=\"1",
            "' UNION SELECT * FROM users--",
        ]
        for payload in payloads:
            resp = c.post("/api/users", json={
                "username": payload, "password": "testpass", "role": "viewer",
            })
            assert resp.status_code in (201, 400, 409)

    def test_sql_injection_in_user_lookup(self, config_dir, var_dir):
        """SQL injection in URL path parameter for user operations."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        payloads = [
            "admin' OR '1'='1",
            "admin'; DROP TABLE users;--",
            "../../../etc/passwd",
        ]
        for payload in payloads:
            resp = c.put(f"/api/users/{payload}", json={"role": "viewer"})
            assert resp.status_code in (404, 400)
            resp = c.delete(f"/api/users/{payload}")
            assert resp.status_code in (404, 400)

    # ── Path traversal ────────────────────────────────────────────

    def test_path_traversal_lang_endpoint(self, config_dir, var_dir):
        """Path traversal via /lang/<code> doesn't break the app."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//etc/passwd",
            "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ]
        for payload in payloads:
            resp = c.get(f"/lang/{payload}", follow_redirects=True)
            # Must not crash; language stays unchanged
            assert resp.status_code in (200, 302, 404)

    def test_path_traversal_theme_endpoint(self, config_dir, var_dir):
        """Path traversal via /theme/<mode> doesn't break the app."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        for payload in ["../../etc/shadow", "light/../../../etc/passwd"]:
            resp = c.get(f"/theme/{payload}", follow_redirects=True)
            assert resp.status_code in (200, 302, 404)

    def test_path_traversal_session_revoke(self, config_dir, var_dir):
        """Path traversal in session revoke endpoint."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        payloads = [
            "../../../etc/passwd",
            "..%2F..%2F..%2Fetc%2Fpasswd",
            "....//....//secret",
        ]
        for payload in payloads:
            resp = c.post(
                f"/api/sessions/revoke/{payload}",
                content_type="application/json", data="{}",
            )
            assert resp.status_code in (404, 400)

    # ── JSON injection / malformed payloads ───────────────────────

    def test_non_json_content_type(self, config_dir, var_dir):
        """Sending non-JSON content to JSON endpoints returns 400."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        endpoints = [
            ("/api/modules", "PUT"),
            ("/api/config", "PUT"),
            ("/api/users", "POST"),
            ("/api/users/secadmin", "PUT"),
            ("/api/users/me/password", "PUT"),
        ]
        for path, method in endpoints:
            resp = getattr(c, method.lower())(
                path, data="not json",
                content_type="text/plain",
            )
            assert resp.status_code == 400, f"{method} {path} accepted non-JSON"

    def test_empty_body_json_endpoints(self, config_dir, var_dir):
        """Empty body on JSON endpoints returns 400, not a 500."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        endpoints = [
            ("/api/modules", "PUT"),
            ("/api/config", "PUT"),
            ("/api/users", "POST"),
            ("/api/users/me/password", "PUT"),
        ]
        for path, method in endpoints:
            resp = getattr(c, method.lower())(
                path, data="",
                content_type="application/json",
            )
            assert resp.status_code == 400, f"{method} {path} didn't reject empty body"

    def test_deeply_nested_json(self, config_dir, var_dir):
        """Deeply nested JSON doesn't crash the server."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        # Build a 50-level nested dict
        nested = {"end": True}
        for i in range(50):
            nested = {f"level_{i}": nested}
        resp = c.put("/api/modules", json=nested)
        # Must not crash — 200 (saved) is fine
        assert resp.status_code in (200, 400)

    def test_very_large_json_payload(self, config_dir, var_dir):
        """An oversized JSON payload doesn't crash the server."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        big = {"key_" + str(i): "x" * 1000 for i in range(500)}
        resp = c.put("/api/modules", json=big)
        # Accept or reject — just don't crash
        assert resp.status_code in (200, 400, 413)

    def test_null_bytes_in_json_fields(self, config_dir, var_dir):
        """Null bytes in JSON values don't crash the server."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        resp = c.post("/api/users", json={
            "username": "null\x00user", "password": "p\x00wd",
            "role": "viewer",
        })
        assert resp.status_code in (201, 400)

    def test_unicode_abuse_in_fields(self, config_dir, var_dir):
        """Exotic Unicode in user fields doesn't crash anything."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        payloads = [
            "\u202eadmin",       # RTL override
            "admin\u0000",       # null char
            "\uffff",            # noncharacter
            "🔥" * 100,          # lots of emoji
            "Ā" * 5000,          # long multibyte string
        ]
        for p in payloads:
            resp = c.post("/api/users", json={
                "username": p, "password": "testpass", "role": "viewer",
            })
            assert resp.status_code in (201, 400, 409)

    # ── Privilege escalation ──────────────────────────────────────

    def test_viewer_cannot_create_user(self, config_dir, var_dir):
        """Viewer cannot POST /api/users."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        resp = c.post("/api/users", json={
            "username": "hacker", "password": "testpass", "role": "admin",
        })
        assert resp.status_code == 403

    def test_viewer_cannot_delete_user(self, config_dir, var_dir):
        """Viewer cannot DELETE /api/users/<name>."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        resp = c.delete("/api/users/editor")
        assert resp.status_code == 403

    def test_editor_cannot_create_or_delete_users(self, config_dir, var_dir):
        """Editor can view users but cannot create or delete them."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "editor", "epass")
        assert c.get("/api/users").status_code == 200
        assert c.post("/api/users", json={
            "username": "h", "password": "testpass", "role": "viewer",
        }).status_code == 403
        assert c.delete("/api/users/viewer").status_code == 403

    def test_editor_cannot_access_sessions(self, config_dir, var_dir):
        """Editor cannot access session management."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "editor", "epass")
        assert c.get("/api/sessions").status_code == 403

    def test_viewer_cannot_write_modules(self, config_dir, var_dir):
        """Viewer cannot PUT modules."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        resp = c.put("/api/modules", json={"evil": True})
        assert resp.status_code == 403

    def test_viewer_cannot_write_config(self, config_dir, var_dir):
        """Viewer cannot PUT config."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        resp = c.put("/api/config", json={"evil": True})
        assert resp.status_code == 403

    def test_viewer_can_access_audit(self, config_dir, var_dir):
        """Viewer can GET /api/audit (audit_view included in viewer role)."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        assert c.get("/api/audit").status_code == 200

    def test_self_promotion_via_update(self, config_dir, var_dir):
        """A non-admin cannot promote themselves by calling PUT /api/users."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        resp = c.put("/api/users/viewer", json={"role": "admin"})
        assert resp.status_code == 403

    # ── Authentication bypass attempts ────────────────────────────

    def test_unauthenticated_api_access(self, config_dir, var_dir):
        """All API endpoints redirect or reject unauthenticated requests."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        protected_endpoints = [
            ("GET", "/api/modules"),
            ("PUT", "/api/modules"),
            ("GET", "/api/config"),
            ("PUT", "/api/config"),
            ("GET", "/api/status"),
            ("GET", "/api/overview"),
            ("GET", "/api/users"),
            ("POST", "/api/users"),
            ("PUT", "/api/users/x"),
            ("DELETE", "/api/users/x"),
            ("PUT", "/api/users/me/password"),
            ("GET", "/api/sessions"),
            ("POST", "/api/sessions/invalidate"),
            ("POST", "/api/sessions/revoke/x"),
            ("GET", "/api/audit"),
            ("GET", "/api/me"),
        ]
        for method, path in protected_endpoints:
            resp = getattr(c, method.lower())(path)
            assert resp.status_code in (302, 401, 403), \
                f"Unauthenticated {method} {path} returned {resp.status_code}"

    def test_login_wrong_password(self, config_dir, var_dir):
        """Wrong password returns the login page, not a crash."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        resp = c.post("/login", data={
            "username": "secadmin", "password": "WRONG",
        })
        assert resp.status_code == 200  # stays on login page
        assert b'logged_in' not in resp.data

    def test_login_nonexistent_user(self, config_dir, var_dir):
        """Login with a non-existent user is cleanly rejected."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        resp = c.post("/login", data={
            "username": "nobody_exists_here", "password": "testpass",
        })
        assert resp.status_code == 200
        with c.session_transaction() as s:
            assert 'logged_in' not in s

    def test_login_empty_credentials(self, config_dir, var_dir):
        """Empty username/password does not grant access."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        resp = c.post("/login", data={"username": "", "password": ""},
                       follow_redirects=True)
        with c.session_transaction() as s:
            assert 'logged_in' not in s

    # ── Session manipulation ──────────────────────────────────────

    def test_forged_session_token_rejected(self, config_dir, var_dir):
        """A hand-crafted session token is rejected."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        # Replace the real token with a forged one
        with c.session_transaction() as s:
            s['session_token'] = 'a' * 64
        resp = c.get("/api/me", follow_redirects=False)
        assert resp.status_code == 302  # kicked back to login

    def test_reused_session_token_after_logout(self, config_dir, var_dir):
        """After logout the token is no longer valid."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        with c.session_transaction() as s:
            token = s.get('session_token')
        c.get("/logout")
        # Re-inject the old token
        with c.session_transaction() as s:
            s['session_token'] = token
            s['logged_in'] = True
            s['username'] = 'secadmin'
            s['role'] = 'admin'
        resp = c.get("/api/me", follow_redirects=False)
        assert resp.status_code == 302  # session invalidated

    # ── HTTP method abuse ─────────────────────────────────────────

    def test_wrong_http_methods_rejected(self, config_dir, var_dir):
        """Endpoints reject unsupported HTTP methods."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        tests = [
            ("DELETE", "/api/modules"),
            ("POST", "/api/modules"),
            ("PATCH", "/api/modules"),
            ("DELETE", "/api/config"),
            ("POST", "/api/config"),
            ("PUT", "/api/users"),          # should be POST for create
            ("PATCH", "/api/users/admin"),
            ("GET", "/api/sessions/invalidate"),
        ]
        for method, path in tests:
            resp = getattr(c, method.lower())(path)
            assert resp.status_code == 405, \
                f"{method} {path} returned {resp.status_code} instead of 405"

    # ── SSTI (server-side template injection) ─────────────────────

    def test_ssti_in_display_name(self, config_dir, var_dir):
        """Template syntax in display_name is escaped, not evaluated."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        c.post("/api/users", json={
            "username": "sstiuser", "password": "testpass", "role": "viewer",
            "display_name": "{{ config.items() }}",
        })
        html = c.get("/").data.decode()
        # Must not leak Flask config; Jinja auto-escape means literal text
        assert "config.items()" not in html or "{{ config.items() }}" in html

    # ── Role enumeration safety ───────────────────────────────────

    def test_invalid_role_rejected(self, config_dir, var_dir):
        """Creating a user with an invalid role is rejected."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        resp = c.post("/api/users", json={
            "username": "badrole", "password": "testpass", "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_update_to_invalid_role_rejected(self, config_dir, var_dir):
        """Updating user to an invalid role is rejected."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "secadmin", "secpass")
        resp = c.put("/api/users/viewer", json={"role": "superadmin"})
        assert resp.status_code == 400

    # ── Special characters in config/module keys ──────────────────

    def test_special_chars_in_module_keys(self, config_dir, var_dir):
        """Special characters in module keys don't break save/load."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        tricky = {
            "mod/../evil": {"enabled": True},
            "mod<script>": {"enabled": False},
            "mod\x00null": {"enabled": True},
        }
        resp = c.put("/api/modules", json=tricky)
        assert resp.status_code == 200
        # Re-read and verify keys are stored literally
        data = c.get("/api/modules").get_json()
        for key in tricky:
            assert key in data

    # ── Audit-log injection ───────────────────────────────────────

    def test_audit_log_not_injectable(self, config_dir, var_dir):
        """XSS payloads in user actions are recorded literally in audit."""
        wa = self._make_admin(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c)
        payload = '<script>alert("audit")</script>'
        c.post("/api/users", json={
            "username": payload, "password": "testpass", "role": "viewer",
        })
        entries = c.get("/api/audit").get_json()
        # If there's a user_created entry, the username should be literal
        created = [e for e in entries if e['event'] == 'user_created']
        if created:
            assert created[0]['detail']['username'] == payload
