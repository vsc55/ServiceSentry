#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the web administration panel."""

import json

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Fixtures ─────────────────────────────

@pytest.fixture()
def config_dir(tmp_path):
    """Temporary config directory with sample modules.json and config.json."""
    modules = {
        "ping": {
            "enabled": True,
            "threads": 5,
            "timeout": 5,
            "attempt": 3,
            "list": {
                "192.168.1.1": {
                    "enabled": True,
                    "label": "Router",
                    "timeout": 5,
                },
                "192.168.1.2": False,
            },
        },
        "web": {
            "enabled": True,
            "threads": 5,
            "list": {
                "www.example.com": True,
            },
        },
    }
    config = {
        "daemon": {"timer_check": 300},
        "global": {"debug": False},
        "telegram": {
            "token": "test-token-123",
            "chat_id": "12345",
            "group_messages": False,
        },
    }
    (tmp_path / "modules.json").write_text(
        json.dumps(modules, indent=4), encoding="utf-8"
    )
    (tmp_path / "config.json").write_text(
        json.dumps(config, indent=4), encoding="utf-8"
    )
    return str(tmp_path)


@pytest.fixture()
def var_dir(tmp_path):
    """Temporary var directory with a sample status.json."""
    status = {
        "ping": {
            "192.168.1.1": {"status": True, "other_data": {}},
        },
    }
    d = tmp_path / "var"
    d.mkdir()
    (d / "status.json").write_text(
        json.dumps(status, indent=4), encoding="utf-8"
    )
    return str(d)


@pytest.fixture()
def admin(config_dir, var_dir):
    """WebAdmin instance with testing config."""
    return WebAdmin(config_dir, "admin", "secret", var_dir)


@pytest.fixture()
def client(admin):
    """Flask test client (not logged in)."""
    admin.app.config["TESTING"] = True
    return admin.app.test_client()


def _login(client, username="admin", password="secret"):
    """Helper — POST to /login and follow redirects."""
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


# ──────────────────────────── Initialisation ───────────────────────

class TestWebAdminInit:
    """WebAdmin construction tests."""

    def test_instance_creation(self, config_dir):
        wa = WebAdmin(config_dir, "u", "p")
        assert wa.app is not None

    def test_default_port(self):
        assert WebAdmin.DEFAULT_PORT == 8080

    def test_default_host(self):
        assert WebAdmin.DEFAULT_HOST == "0.0.0.0"

    def test_instance_without_var_dir(self, config_dir):
        wa = WebAdmin(config_dir, "u", "p", var_dir=None)
        assert wa.app is not None

    def test_creates_users_json_on_first_run(self, config_dir):
        """users.json is created automatically with the default admin."""
        import os
        wa = WebAdmin(config_dir, "myadmin", "mypass")
        path = os.path.join(config_dir, "users.json")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            users = json.load(f)
        assert "myadmin" in users
        assert users["myadmin"]["role"] == "admin"
        assert "password_hash" in users["myadmin"]

    def test_loads_existing_users_json(self, config_dir):
        """If users.json already exists, it is loaded instead of recreated."""
        import os

        from werkzeug.security import generate_password_hash
        users = {
            "existinguser": {
                "password_hash": generate_password_hash("existingpass"),
                "role": "editor",
                "display_name": "Existing",
            }
        }
        path = os.path.join(config_dir, "users.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(users, f)
        wa = WebAdmin(config_dir, "ignored", "ignored")
        # The constructor should NOT overwrite with the default user
        assert "existinguser" in wa._users
        assert "ignored" not in wa._users


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
        assert "incorrectas" in resp.data.decode()

    def test_login_wrong_username(self, client):
        resp = _login(client, username="hacker")
        assert resp.status_code == 200
        assert "incorrectas" in resp.data.decode()

    def test_login_empty_fields(self, client):
        resp = _login(client, username="", password="")
        assert resp.status_code == 200
        assert "incorrectas" in resp.data.decode()

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


# ──────────────────────────── API: modules ─────────────────────────

class TestApiModules:
    """GET / PUT /api/modules."""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/modules")
        assert resp.status_code == 302

    def test_put_requires_auth(self, client):
        resp = client.put("/api/modules", json={"x": 1})
        assert resp.status_code == 302

    def test_get_returns_data(self, client):
        _login(client)
        resp = client.get("/api/modules")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ping" in data
        assert data["ping"]["enabled"] is True
        assert data["ping"]["threads"] == 5

    def test_put_saves_data(self, client, config_dir):
        _login(client)
        new = {"ping": {"enabled": False, "timeout": 10}}
        resp = client.put("/api/modules", json=new)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        # Verify the saved file
        with open(f"{config_dir}/modules.json", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["ping"]["enabled"] is False
        assert saved["ping"]["timeout"] == 10

    def test_put_roundtrip(self, client):
        _login(client)
        original = client.get("/api/modules").get_json()
        original["web"]["enabled"] = False
        client.put("/api/modules", json=original)
        reloaded = client.get("/api/modules").get_json()
        assert reloaded["web"]["enabled"] is False
        assert reloaded["ping"]["enabled"] is True  # unchanged

    def test_put_invalid_json(self, client):
        _login(client)
        resp = client.put(
            "/api/modules", data="not-json", content_type="application/json"
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_put_no_body(self, client):
        _login(client)
        resp = client.put("/api/modules", content_type="application/json")
        assert resp.status_code == 400


# ──────────────────────────── API: config ──────────────────────────

class TestApiConfig:
    """GET / PUT /api/config."""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 302

    def test_put_requires_auth(self, client):
        resp = client.put("/api/config", json={})
        assert resp.status_code == 302

    def test_get_returns_data(self, client):
        _login(client)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["daemon"]["timer_check"] == 300
        assert data["telegram"]["token"] == "test-token-123"

    def test_put_saves_data(self, client, config_dir):
        _login(client)
        new = {"daemon": {"timer_check": 600}, "global": {"debug": True}}
        resp = client.put("/api/config", json=new)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["daemon"]["timer_check"] == 600

    def test_put_invalid_json(self, client):
        _login(client)
        resp = client.put(
            "/api/config", data="{bad", content_type="application/json"
        )
        assert resp.status_code == 400


# ──────────────────────────── API: status ──────────────────────────

class TestApiStatus:
    """GET /api/status (read-only)."""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 302

    def test_get_returns_data(self, client):
        _login(client)
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ping"]["192.168.1.1"]["status"] is True

    def test_get_empty_when_no_var_dir(self, config_dir):
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=None)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        resp = c.get("/api/status")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_get_empty_when_status_missing(self, config_dir, tmp_path):
        """var_dir exists but status.json does not."""
        empty_var = str(tmp_path / "empty_var")
        import os
        os.makedirs(empty_var, exist_ok=True)
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=empty_var)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        resp = c.get("/api/status")
        assert resp.status_code == 200
        assert resp.get_json() == {}


# ──────────────────────────── API: user management ─────────────────

class TestApiUsers:
    """User CRUD — admin only."""

    def test_get_users_requires_auth(self, client):
        resp = client.get("/api/users")
        assert resp.status_code == 302

    def test_get_users_as_admin(self, client):
        _login(client)
        resp = client.get("/api/users")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "admin" in data
        # Must NOT expose password_hash
        assert "password_hash" not in data["admin"]
        assert data["admin"]["role"] == "admin"

    def test_create_user(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "newuser",
            "password": "pass123",
            "role": "editor",
            "display_name": "New User",
        })
        assert resp.status_code == 201
        # Verify it appears in the list
        users = client.get("/api/users").get_json()
        assert "newuser" in users
        assert users["newuser"]["role"] == "editor"
        assert users["newuser"]["display_name"] == "New User"

    def test_create_user_missing_username(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "",
            "password": "x",
        })
        assert resp.status_code == 400

    def test_create_user_missing_password(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "nopass",
            "password": "",
        })
        assert resp.status_code == 400

    def test_create_duplicate_user(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "admin",
            "password": "x",
        })
        assert resp.status_code == 409

    def test_create_user_invalid_role(self, client):
        _login(client)
        resp = client.post("/api/users", json={
            "username": "badrole",
            "password": "x",
            "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_update_user(self, client):
        _login(client)
        # Create a user first
        client.post("/api/users", json={
            "username": "testuser",
            "password": "pass",
            "role": "viewer",
        })
        # Update role and display_name
        resp = client.put("/api/users/testuser", json={
            "role": "editor",
            "display_name": "Test Edited",
        })
        assert resp.status_code == 200
        users = client.get("/api/users").get_json()
        assert users["testuser"]["role"] == "editor"
        assert users["testuser"]["display_name"] == "Test Edited"

    def test_update_user_password(self, admin, client):
        """Changing a user's password via admin API works."""
        _login(client)
        client.post("/api/users", json={
            "username": "pwuser", "password": "oldpass", "role": "viewer",
        })
        # Change the password
        resp = client.put("/api/users/pwuser", json={"password": "newpass"})
        assert resp.status_code == 200
        # Verify new password works
        from werkzeug.security import check_password_hash
        assert check_password_hash(admin._users["pwuser"]["password_hash"], "newpass")

    def test_update_nonexistent_user(self, client):
        _login(client)
        resp = client.put("/api/users/ghost", json={"role": "viewer"})
        assert resp.status_code == 404

    def test_delete_user(self, client):
        _login(client)
        client.post("/api/users", json={
            "username": "todelete", "password": "x", "role": "viewer",
        })
        resp = client.delete("/api/users/todelete")
        assert resp.status_code == 200
        users = client.get("/api/users").get_json()
        assert "todelete" not in users

    def test_delete_nonexistent_user(self, client):
        _login(client)
        resp = client.delete("/api/users/ghost")
        assert resp.status_code == 404

    def test_cannot_delete_self(self, client):
        _login(client)
        resp = client.delete("/api/users/admin")
        assert resp.status_code == 400
        assert "propia" in resp.get_json()["error"]

    def test_cannot_remove_last_admin(self, client):
        """Demoting the only admin to editor must fail."""
        _login(client)
        resp = client.put("/api/users/admin", json={"role": "viewer"})
        assert resp.status_code == 400
        assert "administrador" in resp.get_json()["error"]

    def test_users_persisted_to_file(self, admin, config_dir):
        """users.json on disk reflects API changes."""
        import os
        admin.app.config["TESTING"] = True
        c = admin.app.test_client()
        c.post("/login", data={"username": "admin", "password": "secret"})
        c.post("/api/users", json={
            "username": "persisted", "password": "x", "role": "viewer",
        })
        path = os.path.join(config_dir, "users.json")
        with open(path, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert "persisted" in on_disk


# ──────────────────────────── Roles & permissions ──────────────────

class TestRolePermissions:
    """Verify role-based access control."""

    @staticmethod
    def _make_multiuser_admin(config_dir, var_dir):
        """Create a WebAdmin with admin + editor + viewer users."""
        import os

        from werkzeug.security import generate_password_hash
        users = {
            "boss": {
                "password_hash": generate_password_hash("bosspass"),
                "role": "admin",
                "display_name": "Boss",
            },
            "dev": {
                "password_hash": generate_password_hash("devpass"),
                "role": "editor",
                "display_name": "Developer",
            },
            "guest": {
                "password_hash": generate_password_hash("guestpass"),
                "role": "viewer",
                "display_name": "Guest",
            },
        }
        with open(os.path.join(config_dir, "users.json"), "w", encoding="utf-8") as f:
            json.dump(users, f)
        wa = WebAdmin(config_dir, var_dir=var_dir)
        wa.app.config["TESTING"] = True
        return wa

    def test_viewer_can_read_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.get("/api/modules")
        assert resp.status_code == 200

    def test_viewer_cannot_write_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.put("/api/modules", json={"x": 1})
        assert resp.status_code == 403

    def test_viewer_cannot_write_config(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.put("/api/config", json={"x": 1})
        assert resp.status_code == 403

    def test_editor_can_write_modules(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200

    def test_editor_can_write_config(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.put("/api/config", json={"daemon": {"timer_check": 60}})
        assert resp.status_code == 200

    def test_editor_cannot_manage_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "dev", "password": "devpass"})
        resp = c.get("/api/users")
        assert resp.status_code == 403

    def test_viewer_cannot_manage_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "guest", "password": "guestpass"})
        resp = c.post("/api/users", json={"username": "x", "password": "x"})
        assert resp.status_code == 403

    def test_admin_can_manage_users(self, config_dir, var_dir):
        wa = self._make_multiuser_admin(config_dir, var_dir)
        c = wa.app.test_client()
        c.post("/login", data={"username": "boss", "password": "bosspass"})
        resp = c.get("/api/users")
        assert resp.status_code == 200
        assert "boss" in resp.get_json()


# ──────────────────────────── Change own password ──────────────────

class TestChangeOwnPassword:
    """Any user can change their own password."""

    def test_change_own_password(self, admin, client):
        _login(client)
        resp = client.put("/api/users/me/password", json={
            "current_password": "secret",
            "new_password": "newsecret",
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # Verify new password works
        from werkzeug.security import check_password_hash
        assert check_password_hash(admin._users["admin"]["password_hash"], "newsecret")

    def test_change_own_password_wrong_current(self, client):
        _login(client)
        resp = client.put("/api/users/me/password", json={
            "current_password": "wrong",
            "new_password": "x",
        })
        assert resp.status_code == 403

    def test_change_own_password_empty_new(self, client):
        _login(client)
        resp = client.put("/api/users/me/password", json={
            "current_password": "secret",
            "new_password": "",
        })
        assert resp.status_code == 400

    def test_change_password_requires_auth(self, client):
        resp = client.put("/api/users/me/password", json={
            "current_password": "x",
            "new_password": "y",
        })
        assert resp.status_code == 302


# ──────────────────────────── Config-file edge cases ───────────────

class TestConfigEdgeCases:
    """Edge cases around missing or empty config files."""

    def test_get_modules_empty_dir(self, tmp_path):
        """Config dir exists but modules.json does not."""
        wa = WebAdmin(str(tmp_path), "a", "b")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "a", "password": "b"})
        resp = c.get("/api/modules")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_save_creates_file(self, tmp_path):
        """Saving to a non-existent file creates it."""
        wa = WebAdmin(str(tmp_path), "a", "b")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "a", "password": "b"})
        resp = c.put("/api/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200
        assert (tmp_path / "modules.json").exists()
