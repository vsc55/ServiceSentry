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
        # The severity filter must reach the backend under its declared param name
        # (severity_max, not the default 'f'): err(3) is kept at max=3, dropped at max=2.
        assert len(client.get("/api/v1/overview/widget/syslog?severity_max=3").get_json()["rows"]) == 1
        assert client.get("/api/v1/overview/widget/syslog?severity_max=2").get_json()["rows"] == []

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
        """The dashboard HTML contains the overview pane and its sidebar trigger.

        Overview is a top-level SECTION, so the sidebar builds its button as
        `btn-nav-overview` (the `btn-tab-*` ids belong to the admin panel's own tabs) —
        see test_wa_ui.py, which asserts the old id is gone."""
        _login(client)
        resp = client.get("/admin")
        html = resp.data.decode()
        assert 'id="tab-overview"' in html
        assert 'btn-nav-overview' in html

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


class TestDisablingAnItemKeepsIt:
    """Reported: two items in a module, one disabled with the item checkbox, saved, and on
    reload it was gone — from the database, not just from the view.

    The store deletes every uid absent from the payload, so an item lost anywhere upstream
    becomes a real DELETE. This walks the actual endpoint to place the blame: if the item
    survives here, whatever dropped it was not the server.
    """

    @staticmethod
    def _put(client, data):
        r = client.put('/api/v1/modules', json=data)
        assert r.status_code == 200, r.get_json()
        return client.get('/api/v1/modules').get_json()

    def test_disabling_one_of_two_items_keeps_both(self, client):
        from tests.conftest import _login                        # noqa: PLC0415
        _login(client)
        first = self._put(client, {'ping': {'enabled': True, 'list': {
            'a': {'label': 'one', 'enabled': True},
            'b': {'label': 'two', 'enabled': True}}}})
        items = first['ping']['list']
        assert len(items) == 2, items
        uid_off = next(k for k, v in items.items() if v['label'] == 'two')

        items[uid_off]['enabled'] = False          # exactly what the item checkbox does
        after = self._put(client, first)
        got = after['ping']['list']
        assert len(got) == 2, f'an item was lost on save: {got}'
        assert {v['label'] for v in got.values()} == {'one', 'two'}
        assert got[uid_off]['enabled'] is False, 'the toggle did not stick'

    def test_a_reload_still_returns_the_disabled_item(self, client):
        """The other half: a load-side filter on `enabled` would be just as fatal, because
        the next save builds its payload from what the GET returned — and the store deletes
        every uid the payload omits."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(client)
        self._put(client, {'ping': {'enabled': True, 'list': {
            'a': {'label': 'on', 'enabled': True},
            'b': {'label': 'off', 'enabled': False}}}})
        got = client.get('/api/v1/modules').get_json()['ping']['list']
        assert len(got) == 2, f'the disabled item did not come back: {got}'
        assert any(v['enabled'] is False for v in got.values())


