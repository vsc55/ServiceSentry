#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for module routes: /api/modules, /api/status, /api/overview."""

import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.modules import ModuleBase
from watchfuls.web import Watchful as WebWatchful

from tests.conftest import _login, _SAMPLE_MODULES

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── API: modules ─────────────────────────

class TestApiModules:
    """GET / PUT /api/modules."""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/v1/modules")
        assert resp.status_code == 401

    def test_put_requires_auth(self, client):
        resp = client.put("/api/v1/modules", json={"x": 1})
        assert resp.status_code == 401

    def test_get_returns_data(self, client):
        _login(client)
        resp = client.get("/api/v1/modules")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ping" in data
        assert data["ping"]["enabled"] is True
        assert data["ping"]["threads"] == 5

    def test_put_saves_data(self, client):
        _login(client)
        new = {"ping": {"enabled": False, "timeout": 10}}
        resp = client.put("/api/v1/modules", json=new)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        # Verify it persisted (DB-backed module store)
        saved = client.get("/api/v1/modules").get_json()
        assert saved["ping"]["enabled"] is False
        assert saved["ping"]["timeout"] == 10

    def test_put_roundtrip(self, client):
        _login(client)
        original = client.get("/api/v1/modules").get_json()
        original["web"]["enabled"] = False
        client.put("/api/v1/modules", json=original)
        reloaded = client.get("/api/v1/modules").get_json()
        assert reloaded["web"]["enabled"] is False
        assert reloaded["ping"]["enabled"] is True  # unchanged

    def test_put_invalid_json(self, client):
        _login(client)
        resp = client.put(
            "/api/v1/modules", data="not-json", content_type="application/json"
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_put_no_body(self, client):
        _login(client)
        resp = client.put("/api/v1/modules", content_type="application/json")
        assert resp.status_code == 400


# ──────────────────────────── API: status ──────────────────────────

class TestApiStatus:
    """GET /api/status (read-only)."""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/v1/modules/status")
        assert resp.status_code == 401

    def test_get_returns_data(self, client):
        _login(client)
        resp = client.get("/api/v1/modules/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ping"]["192.168.1.1"]["status"] is True

    def test_get_empty_when_no_var_dir(self, config_dir):
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=None)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        resp = c.get("/api/v1/modules/status")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_get_empty_when_status_missing(self, config_dir, tmp_path):
        """var_dir exists but no check state present."""
        empty_var = str(tmp_path / "empty_var")
        os.makedirs(empty_var, exist_ok=True)
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=empty_var)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        resp = c.get("/api/v1/modules/status")
        assert resp.status_code == 200
        assert resp.get_json() == {}


# ──────────────────────────── API: overview ────────────────────────

class TestApiOverview:
    """GET /api/overview — dashboard summary."""

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/modules/overview")
        assert resp.status_code == 401

    def test_returns_200(self, client):
        _login(client)
        resp = client.get("/api/v1/modules/overview")
        assert resp.status_code == 200

    def test_response_keys(self, client):
        """The slim aggregate carries only the shared data (module widgets + role
        metadata); every card/table fetches its own from /overview/widget/<id>."""
        _login(client)
        data = client.get("/api/v1/modules/overview").get_json()
        for key in ("module_widgets", "role_names", "role_keys"):
            assert key in data

    def test_syslog_widget_data(self, admin, client):
        """The syslog widgets expose the total (stat) + recent messages (table) over AJAX."""
        _login(client)
        admin._syslog_store.add({
            'ts': 1000.0, 'received_at': '2026-06-23T10:00:00Z', 'source': '10.0.0.1',
            'hostname': 'h1', 'app': 'sshd', 'procid': '1', 'severity': 3, 'facility': 4,
            'msgid': '', 'message': 'boom', 'raw': ''})
        assert client.get("/api/v1/overview/widget/syslog_stats").get_json()["content"]["value"] == 1
        rows = client.get("/api/v1/overview/widget/syslog").get_json()["rows"]
        assert rows[0]["message"] == "boom"
        assert rows[0]["severity_name"] == "err"

    def test_modules_list(self, client):
        """The modules_list table lists the two sample modules (ping, web)."""
        _login(client)
        rows = client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]
        assert {m["name"] for m in rows} == {"ping", "web"}

    def test_modules_enabled_flag(self, client):
        """Both sample modules are enabled."""
        _login(client)
        rows = client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]
        assert all(m["enabled"] for m in rows)

    def test_modules_items_count(self, client):
        """ping has 2 items, web has 1."""
        _login(client)
        rows = {m["name"]: m for m in
                client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]}
        assert rows["ping"]["items"] == 2
        assert rows["web"]["items"] == 1

    def test_status_counts(self, client):
        """The checks stat value is the total check count (1 = ping/192.168.1.1 OK)."""
        _login(client)
        assert client.get("/api/v1/overview/widget/checks").get_json()["content"]["value"] == 1
        ping = {m["name"]: m["checks"] for m in
                client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]}["ping"]
        assert ping["ok"] == 1 and ping["error"] == 0

    def test_overview_module_widget_section(self, client, admin):
        """The overview payload carries generic module-widget data: each module
        declaring __overview_widget__ contributes its own {entries, aggregate}
        via its overview_widget() hook (here: proxmox aggregates cluster/ceph/node
        status). The core stays module-agnostic."""
        _login(client)
        admin._save_modules({'watchfuls.proxmox': {'enabled': True, 'list': {
            'cl1': {'label': 'Lab', 'enabled': True}}}})
        admin._check_state_store.persist_status({'watchfuls.proxmox': {
            'cl1/cluster':     {'status': True, 'other_data': {'quorate': True, 'nodes_online': 2}},
            'cl1/ceph':        {'status': True, 'other_data': {'health': 'HEALTH_OK'}},
            'cl1/node/pve01':  {'status': True, 'other_data': {'host_name': 'srv-1'}},
            'cl1/node/pve02':  {'status': False, 'other_data': {}},
        }})
        mw = client.get('/api/v1/modules/overview').get_json()['module_widgets']
        prox = mw['proxmox']
        assert len(prox['entries']) == 1
        e = prox['entries'][0]
        assert e['id'] == 'cl1' and e['name'] == 'Lab'
        assert e['ok'] is False                       # one node in error
        assert len(e['rows']) == 2                    # one row per node
        n1 = next(r for r in e['rows'] if r['name'].startswith('pve01'))
        assert n1['state'] == 'ok' and 'srv-1' in n1['name']
        assert any(r['state'] == 'error' for r in e['rows'])
        assert prox['aggregate']['count'] == 1
        # stats carry module-authored labels + values (e.g. nodes 1/2)
        assert any(s['value'] == '1/2' for s in e['stats'])

    def test_status_without_var_dir(self, config_dir):
        """No var_dir → the checks stat value is zero."""
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=None)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        assert c.get("/api/v1/overview/widget/checks").get_json()["content"]["value"] == 0

    def test_sessions_contains_current(self, client):
        """After login the sessions stat counts ≥1 and the sessions_list has the user."""
        _login(client)
        assert client.get("/api/v1/overview/widget/sessions").get_json()["content"]["value"] >= 1
        rows = client.get("/api/v1/overview/widget/sessions_list").get_json()["rows"]
        assert any(r["user"] == "admin" for r in rows)

    def test_users_total(self, client):
        """The users stat value is the user count (1); the by-role split is in its badges."""
        _login(client)
        content = client.get("/api/v1/overview/widget/users").get_json()["content"]
        assert content["value"] == 1
        assert any(b.get("fn") == "role" for b in content["badges"])

    def test_last_events_list(self, admin, client):
        """The activity table returns most-recent-first audit entries."""
        _login(client)
        rows = client.get("/api/v1/overview/widget/activity").get_json()["rows"]
        assert isinstance(rows, list)
        if rows:
            assert "event" in rows[0]

    def test_last_events_max_10(self, admin, client):
        """Even with many audit entries, the activity table returns at most 10."""
        _login(client)
        for _ in range(15):
            admin._audit("admin", "test_event", "filler")
        rows = client.get("/api/v1/overview/widget/activity").get_json()["rows"]
        assert len(rows) <= 10

    def test_dashboard_has_overview_tab(self, client):
        """The dashboard HTML contains the overview tab."""
        _login(client)
        resp = client.get("/admin")
        html = resp.data.decode()
        assert 'id="tab-overview"' in html
        assert 'btn-tab-overview' in html

    # ---- groups summary ----

    def test_groups_summary_keys(self, client):
        """The groups stat exposes a value + badges."""
        _login(client)
        content = client.get("/api/v1/overview/widget/groups").get_json()["content"]
        assert "value" in content and "badges" in content

    def test_groups_default_administrators(self, client):
        """No groups.json → WebAdmin auto-creates 'administrators' group (stat value 1)."""
        _login(client)
        assert client.get("/api/v1/overview/widget/groups").get_json()["content"]["value"] == 1

    # ---- roles summary ----

    def test_roles_summary_keys(self, client):
        """The roles stat exposes a value + badges."""
        _login(client)
        content = client.get("/api/v1/overview/widget/roles").get_json()["content"]
        assert "value" in content and "badges" in content

    def test_roles_builtin_count(self, client):
        """With no custom roles the roles stat value equals the builtin count."""
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        _login(client)
        val = client.get("/api/v1/overview/widget/roles").get_json()["content"]["value"]
        assert val == len(BUILTIN_ROLE_PERMISSIONS)

    def test_roles_custom_count(self, admin, client):
        """Adding a custom role increments the roles stat value."""
        from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS
        _login(client)
        admin._custom_roles["superuser"] = {"permissions": ["modules_view"]}
        val = client.get("/api/v1/overview/widget/roles").get_json()["content"]["value"]
        assert val == len(BUILTIN_ROLE_PERMISSIONS) + 1

    def test_credentials_summary_keys(self, client):
        """The credentials stat exposes a value + badges."""
        _login(client)
        content = client.get("/api/v1/overview/widget/credentials").get_json()["content"]
        assert "value" in content and "badges" in content

    # ---- per-module checks (modules_list table rows) ----

    def test_modules_have_checks_key(self, client):
        """Every modules_list row has a checks dict."""
        _login(client)
        rows = client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]
        for m in rows:
            assert isinstance(m.get("checks"), dict)

    def test_module_checks_structure(self, client):
        """checks dict has total, ok and error keys."""
        _login(client)
        rows = client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]
        for m in rows:
            for key in ("total", "ok", "error"):
                assert key in m["checks"], f"{m['name']}.checks missing '{key}'"

    def test_module_checks_counts(self, client):
        """ping: 1 check OK; web: no checks in status fixture."""
        _login(client)
        rows = {m["name"]: m["checks"] for m in
                client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]}
        assert rows["ping"] == {"total": 1, "ok": 1, "error": 0, "warning": 0}
        assert rows["web"] == {"total": 0, "ok": 0, "error": 0, "warning": 0}

    def test_module_checks_with_error(self, config_dir, tmp_path):
        """A failing check increments the error counter."""
        var = tmp_path / "var2"
        var.mkdir()
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=str(var))
        wa._save_modules(_SAMPLE_MODULES)
        wa._check_state_store.persist_status({
            "ping": {
                "192.168.1.1": {"status": False},
                "192.168.1.2": {"status": True},
            }
        })
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        ping = {m["name"]: m["checks"] for m in
                c.get("/api/v1/overview/widget/modules_list").get_json()["rows"]}["ping"]
        assert ping["total"] == 2 and ping["ok"] == 1 and ping["error"] == 1

    def test_module_checks_with_warning(self, config_dir, tmp_path):
        """A non-OK check marked severity='warning' counts as warning, not error."""
        var = tmp_path / "var3"
        var.mkdir()
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=str(var))
        wa._save_modules(_SAMPLE_MODULES)
        wa._check_state_store.persist_status({
            "ping": {
                "192.168.1.1": {"status": False, "severity": "warning"},
                "192.168.1.2": {"status": True},
            }
        })
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        ping = {m["name"]: m["checks"] for m in
                c.get("/api/v1/overview/widget/modules_list").get_json()["rows"]}["ping"]
        assert ping == {"total": 2, "ok": 1, "error": 0, "warning": 1}

    def test_module_checks_without_var_dir(self, config_dir):
        """No var_dir → all module checks are zero."""
        wa = WebAdmin(config_dir, "admin", "pass", var_dir=None)
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "admin", "password": "pass"})
        rows = c.get("/api/v1/overview/widget/modules_list").get_json()["rows"]
        for m in rows:
            assert m["checks"] == {"total": 0, "ok": 0, "error": 0, "warning": 0}

    def test_status_aggregated_from_module_checks(self, client):
        """The checks stat total equals the sum of per-module check totals."""
        _login(client)
        rows = client.get("/api/v1/overview/widget/modules_list").get_json()["rows"]
        total = sum(m["checks"]["total"] for m in rows)
        assert client.get("/api/v1/overview/widget/checks").get_json()["content"]["value"] == total


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
        """web|list schema includes the 'code', 'server' and 'port' fields."""
        schema = self.schemas.get('web|list')
        assert schema is not None
        assert 'code' in schema
        assert schema['code']['default'] == 0
        assert schema['code']['type'] == 'int'
        assert 'enabled' in schema
        assert 'url' not in schema
        assert schema['server']['type'] == 'str'
        assert schema['port']['type'] == 'int'

    def test_ping_list_schema_fields(self):
        """ping|list schema has enabled, label, host, timeout, attempt, alert."""
        schema = self.schemas['ping|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'label', 'host', 'timeout', 'attempt', 'alert'}
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
        """service_status|list: enabled, label, service, expected, remediation.

        The key is an opaque UID; 'label' carries the editable display name."""
        schema = self.schemas['service_status|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'label', 'service', 'expected', 'remediation'}
        assert schema['enabled']['type'] == 'bool'
        assert schema['service']['type'] == 'str'
        assert schema['label']['type'] == 'str'
        assert schema['__check_title_field__'] == 'label'
        assert schema['__discovery_uid_key__'] is True

    def test_temperature_list_schema_fields(self):
        """temperature is host-centric: a sensor + alert per check, bound to a host."""
        schema = self.schemas['temperature|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'sensor', 'label', 'alert'}
        assert schema['alert']['type'] == 'float'
        import watchfuls.temperature as _t
        assert _t.Watchful.ITEM_SCHEMA['__host_profile__']['key'] == 'ssh'

    def test_hddtemp_list_schema_fields(self):
        """hddtemp is host-centric: the daemon address comes from the bound host."""
        schema = self.schemas['hddtemp|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'label', 'port', 'exclude', 'alert'}
        assert schema['exclude']['type'] == 'list'
        # Per-item threshold inherits the module-level default (50) when blank/0.
        assert schema['alert']['default'] == 0
        assert schema['alert']['placeholder_module'] == 'alert'
        import watchfuls.hddtemp as _h
        assert _h.Watchful.ITEM_SCHEMA['__host_profile__']['address_field'] == 'host'

    def test_raid_list_schema_fields(self):
        """raid is host-centric: the check holds only enabled/label; the SSH
        connection now comes from the bound host (__host_profile__)."""
        schema = self.schemas['raid|list']
        assert 'enabled' in schema and 'label' in schema
        for gone in ('host', 'port', 'user', 'password', 'key_file'):
            assert gone not in schema
        import watchfuls.raid as _raid
        assert _raid.Watchful.ITEM_SCHEMA['__host_profile__']['key'] == 'ssh'

    # ---- modules with __module__-level scalar fields ----
    def test_ram_swap_module_schema(self):
        """ram_swap is host-centric: thresholds live per-check in |list, and the
        check binds to a host (__host_profile__ ssh)."""
        schema = self.schemas.get('ram_swap|list')
        assert schema is not None
        assert 'alert_ram' in schema and 'alert_swap' in schema
        # Per-item default is 0 → inherits the module-level threshold (60).
        assert schema['alert_ram']['default'] == 0
        assert schema['alert_ram']['placeholder_module'] == 'alert_ram'
        assert schema['alert_ram']['min'] == 0 and schema['alert_ram']['max'] == 100
        mod_schema = self.schemas.get('ram_swap|__module__')
        assert mod_schema['alert_ram']['default'] == 60
        assert mod_schema['alert_swap']['default'] == 60
        import watchfuls.ram_swap as _rs
        assert _rs.Watchful.ITEM_SCHEMA['__host_profile__']['key'] == 'ssh'

    def test_filesystemusage_list_schema_fields(self):
        """filesystemusage|list: key is an opaque UID; 'label' is the editable
        display name (host - partition)."""
        schema = self.schemas['filesystemusage|list']
        user_keys = {k for k in schema.keys() if not k.startswith('__')}
        assert user_keys == {'enabled', 'alert', 'partition', 'label'}
        assert schema['__check_title_field__'] == 'label'
        assert schema['__discovery_uid_key__'] is True

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
        html = client.get("/admin").data.decode()
        assert 'ITEM_SCHEMAS' in html
        assert 'web|list' in html

    def test_schemas_passed_to_template(self, admin, client):  # noqa: ARG002
        """item_schemas variable is present in the rendered dashboard."""
        _login(client)
        html = client.get("/admin").data.decode()
        # Rich schema: code has a 'default' key
        assert '"default": 200' in html or '"default":200' in html


# ──────────────────────────── Config-file edge cases ───────────────

class TestConfigEdgeCases:
    """Edge cases around missing or empty config files."""

    def test_get_modules_empty_dir(self, tmp_path):
        """Config dir exists but the module store is empty."""
        wa = WebAdmin(str(tmp_path), "a", "b")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "a", "password": "b"})
        resp = c.get("/api/v1/modules")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_save_persists(self, tmp_path):
        """Saving persists to the DB-backed store."""
        wa = WebAdmin(str(tmp_path), "a", "b")
        wa.app.config["TESTING"] = True
        c = wa.app.test_client()
        c.post("/login", data={"username": "a", "password": "b"})
        resp = c.put("/api/v1/modules", json={"test": {"enabled": True}})
        assert resp.status_code == 200
        assert c.get("/api/v1/modules").get_json() == {"test": {"enabled": True}}


class TestRekeyItemsByUid:
    """_rekey_items_by_uid makes every item's dict key equal its uid, across
    flat ``list`` collections and snmp's nested ``servers``/``checks``."""

    def test_rekey_flat_and_nested(self):
        from lib.core.modules.routes import _rekey_items_by_uid
        data = {
            "ping": {"list": {
                "host1": {"uid": "U1", "label": "A"},
                "host2": {"label": "B"},            # missing uid → generated
            }},
            "snmp": {"enabled": True, "threads": 5, "servers": {
                "srvA": {"uid": "SV", "checks": {
                    "chk1": {"uid": "C1"},
                    "chk2": {},                      # missing uid → generated
                }},
            }},
        }
        _rekey_items_by_uid(data)

        # Flat: existing uid kept as key; generated uid used as key for host2.
        lst = data["ping"]["list"]
        assert "U1" in lst and lst["U1"]["label"] == "A"
        assert all(k == v["uid"] for k, v in lst.items())

        # Nested: server keyed by uid; checks keyed by uid; scalars untouched.
        assert data["snmp"]["enabled"] is True and data["snmp"]["threads"] == 5
        assert "SV" in data["snmp"]["servers"]
        checks = data["snmp"]["servers"]["SV"]["checks"]
        assert "C1" in checks
        assert all(k == v["uid"] for k, v in checks.items())
