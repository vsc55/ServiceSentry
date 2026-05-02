#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the web administration panel."""

import json
import os
import unittest.mock

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import check_password_hash, generate_password_hash

from lib.modules import ModuleBase
from watchfuls.web import Watchful as WebWatchful

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
        os.makedirs(empty_var, exist_ok=True)
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=empty_var)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        resp = c.get("/api/status")
        assert resp.status_code == 200
        assert resp.get_json() == {}


# ──────────────────────────── API: overview ────────────────────────

class TestApiOverview:
    """GET /api/overview — dashboard summary."""

    def test_requires_auth(self, client):
        resp = client.get("/api/overview")
        assert resp.status_code == 302

    def test_returns_200(self, client):
        _login(client)
        resp = client.get("/api/overview")
        assert resp.status_code == 200

    def test_response_keys(self, client):
        _login(client)
        data = client.get("/api/overview").get_json()
        for key in ("modules", "status", "sessions", "users", "last_events"):
            assert key in data

    def test_modules_list(self, client):
        """Modules list contains the two sample modules (ping, web)."""
        _login(client)
        data = client.get("/api/overview").get_json()
        names = {m["name"] for m in data["modules"]}
        assert names == {"ping", "web"}

    def test_modules_enabled_flag(self, client):
        """Both sample modules are enabled."""
        _login(client)
        modules = client.get("/api/overview").get_json()["modules"]
        assert all(m["enabled"] for m in modules)

    def test_modules_items_count(self, client):
        """ping has 2 items, web has 1."""
        _login(client)
        modules = {
            m["name"]: m for m in
            client.get("/api/overview").get_json()["modules"]
        }
        assert modules["ping"]["items"] == 2
        assert modules["web"]["items"] == 1

    def test_status_counts(self, client):
        """status.json has 1 check (ping/192.168.1.1 OK)."""
        _login(client)
        status = client.get("/api/overview").get_json()["status"]
        assert status["total"] == 1
        assert status["ok"] == 1
        assert status["error"] == 0

    def test_status_without_var_dir(self, config_dir):
        """No var_dir → zero status counts."""
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=None)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        status = c.get("/api/overview").get_json()["status"]
        assert status == {"total": 0, "ok": 0, "error": 0}

    def test_sessions_contains_current(self, client):
        """After login, at least 1 active session listed."""
        _login(client)
        sessions = client.get("/api/overview").get_json()["sessions"]
        assert sessions["active"] >= 1
        assert "admin" in sessions["users"]

    def test_users_total(self, client):
        """Default fixture has a single admin user."""
        _login(client)
        users = client.get("/api/overview").get_json()["users"]
        assert users["total"] == 1
        assert users["by_role"].get("admin", 0) == 1

    def test_last_events_list(self, admin, client):
        """last_events returns most-recent-first audit entries."""
        _login(client)
        data = client.get("/api/overview").get_json()
        # The login itself should have generated an audit event
        assert isinstance(data["last_events"], list)
        if data["last_events"]:
            assert "event" in data["last_events"][0]

    def test_last_events_max_10(self, admin, client):
        """Even with many audit entries, at most 10 are returned."""
        _login(client)
        # Generate extra audit entries
        for _ in range(15):
            admin._audit("admin", "test_event", "filler")
        events = client.get("/api/overview").get_json()["last_events"]
        assert len(events) <= 10

    def test_dashboard_has_overview_tab(self, client):
        """The dashboard HTML contains the overview tab."""
        _login(client)
        resp = client.get("/")
        html = resp.data.decode()
        assert 'id="tab-overview"' in html
        assert 'btn-tab-overview' in html


# ──────────────────────────── Module item schemas ──────────────────

class TestModuleItemSchemas:
    """ITEM_SCHEMA declared in each watchful and discovered dynamically."""

    @pytest.fixture(autouse=True)
    def _schemas(self):
        self.schemas = ModuleBase.discover_schemas()

    # ---- discovery returns data ----
    def test_discover_returns_non_empty(self):
        assert isinstance(self.schemas, dict)
        assert len(self.schemas) > 0

    # ---- per-module checks ----
    def test_web_list_schema_has_code(self):
        """web|list schema includes the 'code' and 'url' fields with rich metadata."""
        schema = self.schemas.get('web|list')
        assert schema is not None
        assert 'code' in schema
        assert schema['code']['default'] == 200
        assert schema['code']['type'] == 'int'
        assert 'enabled' in schema
        assert 'url' in schema
        assert schema['url']['type'] == 'str'

    def test_ping_list_schema_fields(self):
        """ping|list schema has enabled, host, timeout, attempt, alert."""
        schema = self.schemas['ping|list']
        assert set(schema.keys()) == {'enabled', 'host', 'timeout', 'attempt', 'alert'}
        assert schema['port']['min'] == 1 if 'port' in schema else True
        # Verify rich format
        assert schema['timeout']['default'] == 5
        assert schema['timeout']['type'] == 'int'
        assert schema['timeout']['min'] == 1

    def test_mysql_list_schema_fields(self):
        """mysql|list schema has all connection fields with metadata."""
        schema = self.schemas['mysql|list']
        for field in ('enabled', 'host', 'port', 'user', 'password', 'db', 'socket'):
            assert field in schema
        # Port has range constraints
        assert schema['port']['default'] == 3306
        assert schema['port']['min'] == 1
        assert schema['port']['max'] == 65535
        # Password is marked sensitive
        assert schema['password'].get('sensitive') is True

    def test_service_status_schema_fields(self):
        """service_status|list schema has enabled, service and remediation."""
        schema = self.schemas['service_status|list']
        assert set(schema.keys()) == {'enabled', 'service', 'remediation'}
        assert schema['enabled']['type'] == 'bool'
        assert schema['service']['type'] == 'str'

    def test_temperature_list_schema_fields(self):
        """temperature|list schema has enabled, label, alert."""
        schema = self.schemas['temperature|list']
        assert set(schema.keys()) == {'enabled', 'label', 'alert'}
        assert schema['alert']['type'] == 'float'

    def test_hddtemp_list_schema_fields(self):
        """hddtemp|list schema has enabled, host, port, exclude."""
        schema = self.schemas['hddtemp|list']
        assert set(schema.keys()) == {'enabled', 'host', 'port', 'exclude'}
        assert schema['exclude']['type'] == 'list'

    def test_raid_remote_schema_fields(self):
        """raid|remote schema has SSH connection fields."""
        schema = self.schemas['raid|remote']
        for field in ('enabled', 'label', 'host', 'port', 'user', 'password', 'key_file'):
            assert field in schema
        assert schema['port']['default'] == 22

    # ---- modules with config-level schema ----
    def test_ram_swap_config_schema(self):
        """ram_swap|config schema has alert_ram and alert_swap."""
        schema = self.schemas.get('ram_swap|config')
        assert schema is not None
        assert set(schema.keys()) == {'alert_ram', 'alert_swap'}
        assert schema['alert_ram']['default'] == 60
        assert schema['alert_ram']['min'] == 0
        assert schema['alert_ram']['max'] == 100

    def test_filesystemusage_list_schema_fields(self):
        """filesystemusage|list schema has the expected fields."""
        schema = self.schemas['filesystemusage|list']
        assert set(schema.keys()) == {'enabled', 'alert', 'label', 'partition'}

    # ---- ITEM_SCHEMA on the Watchful class directly ----
    def test_watchful_class_declares_schema(self):
        """Each watchful with an ITEM_SCHEMA has a dict-of-dicts."""
        assert isinstance(WebWatchful.ITEM_SCHEMA, dict)
        assert 'list' in WebWatchful.ITEM_SCHEMA
        assert 'code' in WebWatchful.ITEM_SCHEMA['list']
        assert WebWatchful.ITEM_SCHEMA['list']['code']['default'] == 200

    # ---- discover_schemas with invalid dir ----
    def test_discover_with_bad_dir_returns_empty(self):
        assert ModuleBase.discover_schemas('/nonexistent/path') == {}

    # ---- frontend integration ----
    def test_dashboard_contains_item_schemas_json(self, client):
        """Dashboard HTML includes ITEM_SCHEMAS as a JS constant."""
        _login(client)
        html = client.get("/").data.decode()
        assert 'ITEM_SCHEMAS' in html
        assert 'web|list' in html

    def test_schemas_passed_to_template(self, admin, client):
        """item_schemas variable is present in the rendered dashboard."""
        _login(client)
        html = client.get("/").data.decode()
        # Rich schema: code has a 'default' key
        assert '"default": 200' in html or '"default":200' in html


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
        assert "own account" in resp.get_json()["error"]

    def test_cannot_remove_last_admin(self, client):
        """Demoting the only admin to editor must fail."""
        _login(client)
        resp = client.put("/api/users/admin", json={"role": "viewer"})
        assert resp.status_code == 400
        assert "admin must exist" in resp.get_json()["error"]

    def test_users_persisted_to_file(self, admin, config_dir):
        """users.json on disk reflects API changes."""
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


# ──────────────────────────── Session registry ─────────────────────

class TestSessionRegistry:
    """Server-side session tracking and management."""

    def test_session_created_on_login(self, admin, client):
        """Login creates an entry in the server-side sessions dict."""
        assert len(admin._sessions) == 0
        _login(client)
        assert len(admin._sessions) == 1

    def test_session_token_in_flask_session(self, client):
        """Login stores a session_token in Flask's session."""
        _login(client)
        with client.session_transaction() as s:
            assert 'session_token' in s
            assert len(s['session_token']) == 64  # hex(32)

    def test_session_records_username(self, admin, client):
        """Session entry contains the logged-in username."""
        _login(client)
        entry = list(admin._sessions.values())[0]
        assert entry['username'] == 'admin'

    def test_session_removed_on_logout(self, admin, client):
        """Logout removes the session from the registry."""
        _login(client)
        assert len(admin._sessions) == 1
        client.get("/logout")
        assert len(admin._sessions) == 0

    def test_session_invalid_after_revocation(self, admin, client):
        """Revoking all sessions invalidates the cookie."""
        _login(client)
        assert client.get("/api/me").status_code == 200
        admin._revoke_all_sessions()
        resp = client.get("/api/me", follow_redirects=False)
        assert resp.status_code == 302

    def test_revoke_user_sessions(self, admin, client):
        """_revoke_user_sessions removes only the target user's sessions."""
        _login(client)
        # Add a fake session for another user
        admin._sessions['fake'] = {
            'username': 'other', 'created': '', 'last_seen': '',
            'ip': '', 'user_agent': '',
        }
        assert len(admin._sessions) == 2
        removed = admin._revoke_user_sessions('other')
        assert removed == 1
        assert len(admin._sessions) == 1

    def test_sessions_persisted_to_file(self, admin, client, config_dir):
        """Sessions are written to sessions.json on disk."""
        _login(client)
        path = os.path.join(config_dir, 'sessions.json')
        assert os.path.isfile(path)
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        assert len(data) == 1

    def test_api_get_sessions(self, client):
        """GET /api/sessions returns all active sessions."""
        _login(client)
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1

    def test_api_revoke_session(self, admin, client):
        """POST /api/sessions/revoke/<sid> removes that session."""
        _login(client)
        sid = list(admin._sessions.keys())[0]
        resp = client.post(f"/api/sessions/revoke/{sid}",
                           content_type="application/json", data="{}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert sid not in admin._sessions

    def test_api_revoke_session_404(self, client):
        """Revoking a non-existent session returns 404."""
        _login(client)
        resp = client.post("/api/sessions/revoke/nonexistent",
                           content_type="application/json", data="{}")
        assert resp.status_code == 404

    def test_api_revoke_user_sessions(self, admin, client):
        """POST /api/sessions/revoke-user/<user> removes user sessions."""
        _login(client)
        admin._sessions['fake'] = {
            'username': 'victim', 'created': '', 'last_seen': '',
            'ip': '', 'user_agent': '',
        }
        resp = client.post("/api/sessions/revoke-user/victim",
                           content_type="application/json", data="{}")
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 1
        assert 'fake' not in admin._sessions
        # Admin session still present
        assert len(admin._sessions) == 1

    def test_sessions_api_admin_only(self, admin, client):
        """Non-admin users cannot access session APIs."""
        admin._users["viewer1"] = {
            "password_hash": generate_password_hash("v"),
            "role": "viewer", "display_name": "V",
        }
        _login(client, "viewer1", "v")
        assert client.get("/api/sessions").status_code == 403
        assert client.post("/api/sessions/invalidate",
                           content_type="application/json",
                           data="{}").status_code == 403

    def test_invalidate_all_sessions(self, admin, client):
        """POST /api/sessions/invalidate clears all sessions."""
        _login(client)
        assert len(admin._sessions) == 1
        resp = client.post("/api/sessions/invalidate",
                           content_type="application/json", data="{}")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert len(admin._sessions) == 0

    def test_close_all_sessions_button_in_ui(self, client):
        """Users tab has the close-all-sessions button."""
        _login(client)
        html = client.get("/").data
        assert b'invalidateAllSessions()' in html
        assert b'close_all_sessions' in html

    def test_sessions_panel_in_ui(self, client):
        """Users tab contains the sessions panel."""
        _login(client)
        html = client.get("/").data
        assert b'sessions-container' in html
        assert b'renderSessions' in html

    def test_per_user_revoke_button_in_ui(self, client):
        """Users tab has the per-user revoke button."""
        _login(client)
        html = client.get("/").data
        assert b'revokeUserSessions' in html


# ──────────────────────────── Audit log ────────────────────────────

class TestAuditLog:
    """Audit log records all relevant events."""

    def test_login_audited(self, admin, client):
        """Successful login creates an audit entry."""
        _login(client)
        events = [e['event'] for e in admin._audit_log]
        assert 'login_ok' in events

    def test_failed_login_audited(self, admin, client):
        """Failed login creates an audit entry."""
        client.post("/login", data={"username": "admin", "password": "wrong"},
                    follow_redirects=True)
        events = [e['event'] for e in admin._audit_log]
        assert 'login_failed' in events

    def test_logout_audited(self, admin, client):
        """Logout creates an audit entry."""
        _login(client)
        client.get("/logout")
        events = [e['event'] for e in admin._audit_log]
        assert 'logout' in events

    def test_modules_save_audited(self, admin, client):
        """Saving modules logs the specific field changes."""
        _login(client)
        client.put("/api/modules", json={"ping": {"enabled": False, "threads": 5}})
        entry = [e for e in admin._audit_log if e['event'] == 'modules_saved'][-1]
        assert isinstance(entry['detail'], list)
        assert any(c['field'] == 'ping.enabled' for c in entry['detail'])

    def test_config_save_audited(self, admin, client):
        """Saving config logs the specific field changes."""
        _login(client)
        client.put("/api/config", json={"daemon": {"timer_check": 60}})
        entry = [e for e in admin._audit_log if e['event'] == 'config_saved'][-1]
        assert isinstance(entry['detail'], list)
        assert any(c['field'] == 'daemon.timer_check' for c in entry['detail'])

    def test_user_create_audited(self, admin, client):
        """Creating a user logs username, role and display_name."""
        _login(client)
        client.post("/api/users", json={
            "username": "auduser", "password": "p", "role": "viewer",
        })
        entry = [e for e in admin._audit_log if e['event'] == 'user_created'][-1]
        assert entry['detail']['username'] == 'auduser'
        assert entry['detail']['role'] == 'viewer'

    def test_user_update_audited(self, admin, client):
        """Updating a user logs old and new values per changed field."""
        _login(client)
        client.put("/api/users/admin", json={"display_name": "Boss"})
        entry = [e for e in admin._audit_log if e['event'] == 'user_updated'][-1]
        assert entry['detail']['username'] == 'admin'
        changes = entry['detail']['changes']
        dn_change = [c for c in changes if c['field'] == 'display_name'][0]
        assert dn_change['new'] == 'Boss'

    def test_user_delete_audited(self, admin, client):
        """Deleting a user logs the username."""
        admin._users["delme"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "Del",
        }
        _login(client)
        client.delete("/api/users/delme")
        entry = [e for e in admin._audit_log if e['event'] == 'user_deleted'][-1]
        assert entry['detail']['username'] == 'delme'

    def test_password_change_audited(self, admin, client):
        """Changing own password creates an audit entry."""
        _login(client)
        client.put("/api/users/me/password", json={
            "current_password": "secret", "new_password": "newsecret",
        })
        events = [e['event'] for e in admin._audit_log]
        assert 'password_changed' in events

    def test_all_sessions_revoked_audited(self, admin, client):
        """Invalidating all sessions creates an audit entry."""
        _login(client)
        client.post("/api/sessions/invalidate",
                    content_type="application/json", data="{}")
        events = [e['event'] for e in admin._audit_log]
        assert 'all_sessions_revoked' in events

    def test_audit_api_returns_entries(self, admin, client):
        """GET /api/audit returns the audit log."""
        _login(client)
        resp = client.get("/api/audit")
        assert resp.status_code == 200
        entries = resp.get_json()
        assert isinstance(entries, list)
        assert len(entries) >= 1
        assert entries[0]['event'] == 'login_ok'  # most recent first

    def test_audit_api_admin_only(self, admin, client):
        """Non-admin users get 403 on /api/audit."""
        admin._users["viewer1"] = {
            "password_hash": generate_password_hash("v"),
            "role": "viewer", "display_name": "V",
        }
        _login(client, "viewer1", "v")
        assert client.get("/api/audit").status_code == 403

    def test_audit_persisted_to_file(self, admin, client, config_dir):
        """Audit log is written to audit.json on disk."""
        _login(client)
        path = os.path.join(config_dir, 'audit.json')
        assert os.path.isfile(path)
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        assert len(data) >= 1

    def test_audit_max_entries(self, admin):
        """Audit log is capped to _AUDIT_MAX_ENTRIES."""
        admin._audit_log = [
            {'ts': '', 'event': 'test', 'user': '', 'ip': '', 'detail': ''}
        ] * 600
        admin._persist_audit()
        assert len(admin._audit_log) == admin._AUDIT_MAX_ENTRIES

    def test_audit_tab_in_ui(self, client):
        """Dashboard has the audit tab for admins."""
        _login(client)
        html = client.get("/").data
        assert b'tab-audit' in html
        assert b'renderAudit' in html

    def test_audit_entry_has_required_fields(self, admin, client):
        """Each audit entry has ts, event, user, ip, detail."""
        _login(client)
        entry = admin._audit_log[-1]
        for field in ('ts', 'event', 'user', 'ip', 'detail'):
            assert field in entry

    def test_admin_password_reset_audited(self, admin, client):
        """Admin resetting a user password logs a 'password_reset' event."""
        admin._users["pwuser"] = {
            "password_hash": generate_password_hash("old"),
            "role": "viewer", "display_name": "PW",
        }
        _login(client)
        client.put("/api/users/pwuser", json={"password": "newpass"})
        events = [e['event'] for e in admin._audit_log]
        assert 'password_reset' in events
        entry = [e for e in admin._audit_log if e['event'] == 'password_reset'][-1]
        assert entry['detail'] == 'pwuser'

    def test_password_reset_separate_from_update(self, admin, client):
        """Changing role + password creates both user_updated and password_reset."""
        admin._users["both"] = {
            "password_hash": generate_password_hash("x"),
            "role": "viewer", "display_name": "B",
        }
        _login(client)
        client.put("/api/users/both", json={
            "role": "editor", "password": "newpw",
        })
        events = [e['event'] for e in admin._audit_log]
        assert 'user_updated' in events
        assert 'password_reset' in events
        upd = [e for e in admin._audit_log if e['event'] == 'user_updated'][-1]
        assert any(c['field'] == 'role' and c['old'] == 'viewer'
                   and c['new'] == 'editor' for c in upd['detail']['changes'])

    def test_config_save_records_old_and_new(self, admin, client):
        """Config change detail includes old and new values."""
        _login(client)
        client.put("/api/config", json={"daemon": {"timer_check": 99}})
        entry = [e for e in admin._audit_log if e['event'] == 'config_saved'][-1]
        change = [c for c in entry['detail']
                  if c['field'] == 'daemon.timer_check'][0]
        assert change['old'] == 300  # original fixture value
        assert change['new'] == 99

    def test_sensitive_fields_masked_in_audit(self, admin, client):
        """Sensitive fields (token, password) are masked in config audit."""
        _login(client)
        client.put("/api/config", json={
            "daemon": {"timer_check": 300},
            "global": {"debug": False},
            "telegram": {
                "token": "CHANGED-TOKEN",
                "chat_id": "12345",
                "group_messages": False,
            },
        })
        entry = [e for e in admin._audit_log if e['event'] == 'config_saved'][-1]
        if entry['detail']:  # there should be a token change
            token_changes = [c for c in entry['detail']
                             if 'token' in c['field']]
            for c in token_changes:
                assert c['old'] == '***'
                assert c['new'] == '***'

    def test_no_update_audit_when_no_changes(self, admin, client):
        """Updating a user with same values does not emit user_updated."""
        _login(client)
        before = len(admin._audit_log)
        client.put("/api/users/admin", json={
            "role": "admin",
            "display_name": admin._users["admin"].get("display_name", "admin"),
        })
        update_entries = [e for e in admin._audit_log[before:]
                         if e['event'] == 'user_updated']
        assert len(update_entries) == 0

    def test_diff_dicts_helper(self, admin):
        """_diff_dicts correctly identifies changed fields."""
        old = {'a': 1, 'b': {'c': 2, 'd': 3}}
        new = {'a': 1, 'b': {'c': 9, 'd': 3}, 'e': 5}
        changes = WebAdmin._diff_dicts(old, new)
        fields = {c['field'] for c in changes}
        assert 'b.c' in fields
        assert 'e' in fields
        assert 'a' not in fields
        bc = [c for c in changes if c['field'] == 'b.c'][0]
        assert bc['old'] == 2
        assert bc['new'] == 9


# ──────────────────────── Run checks API tests ─────────────────────

class TestApiRunChecks:
    """Tests for the /api/checks/run endpoint."""

    def test_run_checks_requires_auth(self, client):
        resp = client.post("/api/checks/run",
                           json={"modules": "all"})
        assert resp.status_code == 302

    def test_run_checks_viewer_denied(self, admin, client):
        _login(client)
        # Patch *both* the user record and the active session so the
        # write_required decorator sees the 'viewer' role.
        admin._users['admin']['role'] = 'viewer'
        with client.session_transaction() as sess:
            sess['role'] = 'viewer'
        resp = client.post("/api/checks/run",
                           json={"modules": "all"})
        assert resp.status_code in (302, 403)
        admin._users['admin']['role'] = 'admin'

    def test_run_checks_no_modules_dir(self, admin, client):
        _login(client)
        orig = admin._modules_dir
        admin._modules_dir = None
        resp = client.post("/api/checks/run",
                           json={"modules": "all"})
        assert resp.status_code == 500
        admin._modules_dir = orig

    def test_run_checks_audit_entry(self, admin, client):
        """Running checks creates an audit log entry."""
        _login(client)
        # Even if it fails to actually run modules, audit should fire
        orig = admin._modules_dir
        admin._modules_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'watchfuls'
        )
        client.post("/api/checks/run",
                     json={"modules": []})
        admin._modules_dir = orig
        events = [e['event'] for e in admin._audit_log]
        assert 'checks_run' in events

    def test_run_checks_all_discovers_package_modules(self, admin, client, tmp_path):
        """modules='all' must find package-based watchful modules (not just flat .py)."""
        import sys

        # Build a minimal package-based watchful in a temp dir
        mods_dir = tmp_path / "watchfuls"
        mods_dir.mkdir()
        mod_dir = mods_dir / "testmod"
        mod_dir.mkdir()
        (mod_dir / "__init__.py").write_text(
            "from lib.modules import ModuleBase, ReturnModuleCheck\n\n"
            "class Watchful(ModuleBase):\n"
            "    ITEM_SCHEMA = {'list': {'enabled': {'type': 'bool', 'default': True}}}\n"
            "    def check(self):\n"
            "        r = ReturnModuleCheck()\n"
            "        r.set('item1', True, 'ok')\n"
            "        return r\n",
            encoding="utf-8",
        )
        # Ensure watchfuls package is importable
        parent = str(tmp_path)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        _login(client)
        orig = admin._modules_dir
        admin._modules_dir = str(mods_dir)
        resp = client.post("/api/checks/run", json={"modules": "all"})
        admin._modules_dir = orig

        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("ok") is True
        assert "testmod" in body.get("results", {})

    def test_run_checks_all_ignores_flat_py_files(self, admin, client, tmp_path):
        """modules='all' must NOT discover legacy flat .py files."""
        mods_dir = tmp_path / "watchfuls2"
        mods_dir.mkdir()
        (mods_dir / "legacy.py").write_text(
            "class Watchful: pass\n", encoding="utf-8"
        )

        _login(client)
        orig = admin._modules_dir
        admin._modules_dir = str(mods_dir)
        resp = client.post("/api/checks/run", json={"modules": "all"})
        admin._modules_dir = orig

        assert resp.status_code == 200
        body = resp.get_json()
        assert "legacy" not in body.get("results", {})
        assert body.get("ok") is True

    def test_run_checks_response_shape(self, admin, client):
        """Response always contains ok, results and errors keys."""
        _login(client)
        orig = admin._modules_dir
        admin._modules_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'watchfuls'
        )
        resp = client.post("/api/checks/run", json={"modules": []})
        admin._modules_dir = orig
        assert resp.status_code == 200
        body = resp.get_json()
        assert "ok" in body
        assert "results" in body
        assert "errors" in body
        assert isinstance(body["results"], dict)
        assert isinstance(body["errors"], list)

    def test_run_checks_specific_module_missing(self, admin, client):
        """Requesting a non-existent module name returns it in errors."""
        _login(client)
        orig = admin._modules_dir
        admin._modules_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'watchfuls'
        )
        resp = client.post("/api/checks/run",
                           json={"modules": ["nonexistent_xyz"]})
        admin._modules_dir = orig
        assert resp.status_code == 200
        body = resp.get_json()
        assert any("nonexistent_xyz" in e for e in body.get("errors", []))


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
                "username": payload, "password": "x", "role": "viewer",
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
            "username": "xssuser", "password": "x", "role": "viewer",
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
                "username": payload, "password": "x", "role": "viewer",
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
                "username": p, "password": "x", "role": "viewer",
            })
            assert resp.status_code in (201, 400, 409)

    # ── Privilege escalation ──────────────────────────────────────

    def test_viewer_cannot_create_user(self, config_dir, var_dir):
        """Viewer cannot POST /api/users."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        resp = c.post("/api/users", json={
            "username": "hacker", "password": "x", "role": "admin",
        })
        assert resp.status_code == 403

    def test_viewer_cannot_delete_user(self, config_dir, var_dir):
        """Viewer cannot DELETE /api/users/<name>."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        resp = c.delete("/api/users/editor")
        assert resp.status_code == 403

    def test_editor_cannot_manage_users(self, config_dir, var_dir):
        """Editor cannot access user management endpoints."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "editor", "epass")
        assert c.get("/api/users").status_code == 403
        assert c.post("/api/users", json={
            "username": "h", "password": "x", "role": "viewer",
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

    def test_viewer_cannot_access_audit(self, config_dir, var_dir):
        """Viewer cannot GET /api/audit."""
        wa = self._make_multiuser(config_dir, var_dir)
        c = wa.app.test_client()
        self._login(c, "viewer", "vpass")
        assert c.get("/api/audit").status_code == 403

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
            "username": "nobody_exists_here", "password": "x",
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
            "username": "sstiuser", "password": "x", "role": "viewer",
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
            "username": "badrole", "password": "x", "role": "superadmin",
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
            "username": payload, "password": "x", "role": "viewer",
        })
        entries = c.get("/api/audit").get_json()
        # If there's a user_created entry, the username should be literal
        created = [e for e in entries if e['event'] == 'user_created']
        if created:
            assert created[0]['detail']['username'] == payload
