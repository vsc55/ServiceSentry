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
