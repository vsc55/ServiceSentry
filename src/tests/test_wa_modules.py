#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for module routes: /api/modules, /api/status, /api/overview."""

import json
import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.modules import ModuleBase
from watchfuls.web import Watchful as WebWatchful

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


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
        for key in ("modules", "status", "sessions", "users", "groups", "roles", "last_events"):
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

    # ---- groups summary ----

    def test_groups_summary_keys(self, client):
        """groups key has total and members sub-keys."""
        _login(client)
        groups = client.get("/api/overview").get_json()["groups"]
        assert "total" in groups
        assert "members" in groups

    def test_groups_default_administrators(self, client):
        """No groups.json → WebAdmin auto-creates 'administrators' group with no members."""
        _login(client)
        groups = client.get("/api/overview").get_json()["groups"]
        assert groups["total"] == 1
        assert groups["members"] == 0

    # ---- roles summary ----

    def test_roles_summary_keys(self, client):
        """roles key has total, builtin and custom sub-keys."""
        _login(client)
        roles = client.get("/api/overview").get_json()["roles"]
        assert "total" in roles
        assert "builtin" in roles
        assert "custom" in roles

    def test_roles_builtin_count(self, client):
        """Builtin roles match BUILTIN_ROLE_PERMISSIONS length (admin, editor, viewer = 3)."""
        from lib.web_admin.constants import BUILTIN_ROLE_PERMISSIONS
        _login(client)
        roles = client.get("/api/overview").get_json()["roles"]
        assert roles["builtin"] == len(BUILTIN_ROLE_PERMISSIONS)
        assert roles["custom"] == 0
        assert roles["total"] == roles["builtin"] + roles["custom"]

    def test_roles_custom_count(self, admin, client):
        """Adding a custom role increments the custom and total counts."""
        from lib.web_admin.constants import BUILTIN_ROLE_PERMISSIONS
        _login(client)
        admin._custom_roles["superuser"] = {"permissions": ["modules_view"]}
        roles = client.get("/api/overview").get_json()["roles"]
        assert roles["custom"] == 1
        assert roles["total"] == len(BUILTIN_ROLE_PERMISSIONS) + 1

    # ---- per-module checks ----

    def test_modules_have_checks_key(self, client):
        """Every module entry in overview has a checks dict."""
        _login(client)
        modules = client.get("/api/overview").get_json()["modules"]
        for m in modules:
            assert "checks" in m
            assert isinstance(m["checks"], dict)

    def test_module_checks_structure(self, client):
        """checks dict has total, ok and error keys."""
        _login(client)
        modules = client.get("/api/overview").get_json()["modules"]
        for m in modules:
            for key in ("total", "ok", "error"):
                assert key in m["checks"], f"{m['name']}.checks missing '{key}'"

    def test_module_checks_counts(self, client):
        """ping: 1 check OK; web: no checks in status fixture."""
        _login(client)
        modules = {
            m["name"]: m["checks"]
            for m in client.get("/api/overview").get_json()["modules"]
        }
        assert modules["ping"] == {"total": 1, "ok": 1, "error": 0}
        assert modules["web"] == {"total": 0, "ok": 0, "error": 0}

    def test_module_checks_with_error(self, config_dir, tmp_path):
        """A failing check increments the error counter."""
        status = {
            "ping": {
                "192.168.1.1": {"status": False},
                "192.168.1.2": {"status": True},
            }
        }
        var = tmp_path / "var2"
        var.mkdir()
        (var / "status.json").write_text(json.dumps(status), encoding="utf-8")
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=str(var))
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        modules = {
            m["name"]: m["checks"]
            for m in c.get("/api/overview").get_json()["modules"]
        }
        assert modules["ping"]["total"] == 2
        assert modules["ping"]["ok"] == 1
        assert modules["ping"]["error"] == 1

    def test_module_checks_without_var_dir(self, config_dir):
        """No var_dir → all module checks are zero."""
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=None)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        modules = c.get("/api/overview").get_json()["modules"]
        for m in modules:
            assert m["checks"] == {"total": 0, "ok": 0, "error": 0}

    def test_status_aggregated_from_module_checks(self, client):
        """Top-level status counts equal the sum of per-module check counts."""
        _login(client)
        data = client.get("/api/overview").get_json()
        total = sum(m["checks"]["total"] for m in data["modules"])
        ok    = sum(m["checks"]["ok"]    for m in data["modules"])
        error = sum(m["checks"]["error"] for m in data["modules"])
        assert data["status"]["total"] == total
        assert data["status"]["ok"]    == ok
        assert data["status"]["error"] == error


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
        assert schema['code']['default'] == 0
        assert schema['code']['type'] == 'int'
        assert 'enabled' in schema
        assert 'url' in schema
        assert schema['url']['type'] == 'str'

    def test_ping_list_schema_fields(self):
        """ping|list schema has enabled, label, host, timeout, attempt, alert."""
        schema = self.schemas['ping|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'host', 'timeout', 'attempt', 'alert'}
        assert schema['port']['min'] == 1 if 'port' in schema else True
        # Verify rich format — 0 means "inherit from module-level setting"
        assert schema['timeout']['default'] == 0
        assert schema['timeout']['type'] == 'int'
        assert schema['timeout']['min'] == 0

    def test_datastore_list_schema_fields(self):
        """datastore|list schema has all connection fields across all engines."""
        schema = self.schemas['datastore|list']
        for field in ('enabled', 'db_type', 'conn_type', 'host', 'port',
                      'user', 'password', 'db', 'socket'):
            assert field in schema
        # db_type covers all supported engines (merged: mariadb→mysql, valkey→redis, opensearch→elasticsearch)
        engines = schema['db_type']['options']
        for eng in ('mysql', 'postgres', 'mssql', 'mongodb',
                    'redis', 'elasticsearch', 'influxdb', 'memcached'):
            assert eng in engines
        for removed in ('mariadb', 'valkey', 'opensearch'):
            assert removed not in engines
        # Password is marked sensitive
        assert schema['password'].get('sensitive') is True
        # SSH fields exist
        for f in ('ssh_host', 'ssh_port', 'ssh_user', 'ssh_password', 'ssh_key'):
            assert f in schema

    def test_service_status_schema_fields(self):
        """service_status|list schema has enabled, service, expected and remediation."""
        schema = self.schemas['service_status|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'service', 'expected', 'remediation'}
        assert schema['enabled']['type'] == 'bool'
        assert schema['service']['type'] == 'str'

    def test_temperature_list_schema_fields(self):
        """temperature|list schema has enabled, alert."""
        schema = self.schemas['temperature|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'alert'}
        assert schema['alert']['type'] == 'float'

    def test_hddtemp_list_schema_fields(self):
        """hddtemp|list schema has enabled, host, port, exclude."""
        schema = self.schemas['hddtemp|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'host', 'port', 'exclude'}
        assert schema['exclude']['type'] == 'list'

    def test_raid_list_schema_fields(self):
        """raid|list schema has SSH connection fields."""
        schema = self.schemas['raid|list']
        for field in ('enabled', 'host', 'port', 'user', 'password', 'key_file'):
            assert field in schema
        # 0 means "use default SSH port"; placeholder shows 22 in the UI
        assert schema['port']['default'] == 0
        assert schema['port']['placeholder'] == 22

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
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'alert', 'partition'}

    # ---- ITEM_SCHEMA on the Watchful class directly ----
    def test_watchful_class_declares_schema(self):
        """Each watchful with an ITEM_SCHEMA has a dict-of-dicts."""
        assert isinstance(WebWatchful.ITEM_SCHEMA, dict)
        assert 'list' in WebWatchful.ITEM_SCHEMA
        assert 'code' in WebWatchful.ITEM_SCHEMA['list']
        assert WebWatchful.ITEM_SCHEMA['list']['code']['default'] == 0

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

    def test_schemas_passed_to_template(self, admin, client):  # noqa: ARG002
        """item_schemas variable is present in the rendered dashboard."""
        _login(client)
        html = client.get("/").data.decode()
        # Rich schema: code has a 'default' key
        assert '"default": 200' in html or '"default":200' in html


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
