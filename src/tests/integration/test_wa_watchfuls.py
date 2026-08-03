#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the generic watchful action endpoint: GET|POST /api/v1/modules/watchfuls/<module>/<action>.

Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_wa_watchfuls.py`` lives in ``tests/unit/test_wa_watchfuls.py``."""

import os
import pathlib
from unittest.mock import patch

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_SRC_DIR = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_WATCHFULS_DIR = os.path.join(_SRC_DIR, "watchfuls")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client_with_modules(tmp_path):
    """Flask test client with modules_dir pointing to the real watchfuls directory."""
    config_dir = str(tmp_path / "config")
    var_dir = str(tmp_path / "var")
    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(var_dir, exist_ok=True)

    (pathlib.Path(config_dir) / "config.json").write_text("{}", encoding="utf-8")

    wa = WebAdmin(
        config_dir, "admin", "secret", var_dir,
        modules_dir=_WATCHFULS_DIR,
        pw_require_upper=False, pw_require_digit=False,
    )
    wa.app.config["TESTING"] = True
    return wa.app.test_client()


# ── Auth ──────────────────────────────────────────────────────────────────────






class TestApiWatchfulActionAuth:
    """Unauthenticated requests are redirected to /login."""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/v1/modules/watchfuls/filesystemusage/discover")
        assert resp.status_code == 401

    def test_post_requires_auth(self, client):
        resp = client.post("/api/v1/modules/watchfuls/datastore/test_connection", json={})
        assert resp.status_code == 401


# ── Input validation ──────────────────────────────────────────────────────────


class TestApiWatchfulActionValidation:
    """Module name and action name are validated before any import."""

    def test_invalid_module_name_uppercase(self, client):
        _login(client)
        resp = client.get("/api/v1/modules/watchfuls/FILESYSTEMUSAGE/discover")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_invalid_module_name_with_dash(self, client):
        _login(client)
        resp = client.get("/api/v1/modules/watchfuls/file-system/discover")
        assert resp.status_code == 400

    def test_invalid_action_name_uppercase(self, client):
        _login(client)
        resp = client.get("/api/v1/modules/watchfuls/filesystemusage/DISCOVER")
        assert resp.status_code == 400

    def test_invalid_action_name_with_dash(self, client):
        _login(client)
        resp = client.get("/api/v1/modules/watchfuls/filesystemusage/get-list")
        assert resp.status_code == 400

    def test_no_modules_dir_returns_404(self, client):
        """Default admin fixture has no modules_dir → 404 before any import."""
        _login(client)
        resp = client.get("/api/v1/modules/watchfuls/filesystemusage/discover")
        assert resp.status_code == 404


# ── Dispatch ──────────────────────────────────────────────────────────────────


class TestApiWatchfulActionDispatch:
    """Module loading, WATCHFUL_ACTIONS whitelist and response plumbing."""

    def test_unknown_module_returns_404(self, client_with_modules):
        _login(client_with_modules)
        resp = client_with_modules.get("/api/v1/modules/watchfuls/nonexistent_xyz/discover")
        assert resp.status_code == 404

    def test_action_not_in_watchful_actions_returns_404(self, client_with_modules):
        """'check' is a real method but NOT in datastore's WATCHFUL_ACTIONS."""
        _login(client_with_modules)
        resp = client_with_modules.post("/api/v1/modules/watchfuls/datastore/check", json={})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "Action not supported"

    def test_get_discover_filesystemusage(self, client_with_modules):
        """GET discover calls cls.discover() and returns the list."""
        _login(client_with_modules)
        fake_items = [{"key": "sda1", "label": "/dev/sda1", "mount": "/"}]
        with patch("watchfuls.filesystemusage.Watchful.discover", return_value=fake_items):
            resp = client_with_modules.get("/api/v1/modules/watchfuls/filesystemusage/discover")
        assert resp.status_code == 200
        assert resp.get_json() == fake_items

    def test_post_test_connection_datastore(self, client_with_modules):
        """POST test_connection calls cls.test_connection(config) and returns result."""
        _login(client_with_modules)
        fake_result = {"ok": True, "message": "MySQL / MariaDB: connection successful"}
        with patch("watchfuls.datastore.Watchful.test_connection", return_value=fake_result):
            resp = client_with_modules.post(
                "/api/v1/modules/watchfuls/datastore/test_connection",
                json={"db_type": "mysql", "conn_type": "tcp", "host": "localhost"},
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_post_list_databases_datastore(self, client_with_modules):
        """POST list_databases returns items list (not databases)."""
        _login(client_with_modules)
        fake_result = {"ok": True, "message": "", "items": ["db1", "db2"]}
        with patch("watchfuls.datastore.Watchful.list_databases", return_value=fake_result):
            resp = client_with_modules.post(
                "/api/v1/modules/watchfuls/datastore/list_databases",
                json={"db_type": "mysql", "conn_type": "tcp"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["items"] == ["db1", "db2"]
        assert "databases" not in data

    def test_action_exception_returns_500(self, client_with_modules):
        """If the action raises, the endpoint returns 500 with error details."""
        _login(client_with_modules)
        with patch(
            "watchfuls.filesystemusage.Watchful.discover",
            side_effect=RuntimeError("boom"),
        ):
            resp = client_with_modules.get("/api/v1/modules/watchfuls/filesystemusage/discover")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["ok"] is False
        assert "boom" in data["message"]

    def test_post_empty_body_passes_empty_dict(self, client_with_modules):
        """POST with no JSON body must call the action with a dict that contains
        only server-injected control keys (no user-supplied data)."""
        _login(client_with_modules)
        captured = {}

        def fake_test_connection(config):
            captured["config"] = config
            return {"ok": True, "message": "ok"}

        with patch(
            "watchfuls.datastore.Watchful.test_connection",
            side_effect=fake_test_connection,
        ):
            client_with_modules.post("/api/v1/modules/watchfuls/datastore/test_connection")

        cfg = captured.get("config", {})
        # The route injects only server-side control keys (the shared DB
        # connector and the var dir); no user-supplied keys should be present.
        assert "__var_dir__" in cfg
        assert "__connector__" in cfg
        assert {k for k in cfg if not (k.startswith("__") and k.endswith("__"))} == set()

    def test_get_discover_service_status(self, client_with_modules):
        """GET discover works on service_status module."""
        _login(client_with_modules)
        fake_items = [{"key": "nginx", "label": "nginx"}]
        with patch("watchfuls.service_status.Watchful.discover", return_value=fake_items):
            resp = client_with_modules.get("/api/v1/modules/watchfuls/service_status/discover")
        assert resp.status_code == 200
        assert resp.get_json() == fake_items


# ── Security ───────────────────────────────────────────────────────────────────


class TestApiWatchfulActionSecurity:
    """Security-specific tests: module import confinement, whitelist enforcement,
    and safe handling of attacker-controlled input."""

    def test_stdlib_module_names_return_404(self, client_with_modules):
        """Built-in names (os, sys, re…) resolve to watchfuls.<name> which doesn't
        exist — the endpoint returns 404, not an import of the stdlib module."""
        _login(client_with_modules)
        for name in ("os", "sys", "re", "subprocess", "pathlib", "importlib"):
            resp = client_with_modules.get(f"/api/v1/modules/watchfuls/{name}/discover")
            assert resp.status_code == 404, f"stdlib module '{name}' should be blocked"

    def test_third_party_package_names_return_404(self, client_with_modules):
        """Third-party packages not under watchfuls/ resolve to watchfuls.<name>
        which doesn't exist — they must not be imported."""
        _login(client_with_modules)
        for name in ("flask", "paramiko", "requests", "psutil", "pytest"):
            resp = client_with_modules.get(f"/api/v1/modules/watchfuls/{name}/discover")
            assert resp.status_code == 404, f"package '{name}' should be blocked"

    def test_private_and_base_methods_blocked_by_whitelist(self, client_with_modules):
        """Methods that exist on the Watchful class but are NOT in WATCHFUL_ACTIONS
        must return 404 — the whitelist is the only gate."""
        _login(client_with_modules)
        for method in ("check", "get_conf", "send_message", "discover_schemas",
                       "is_enabled", "check_status"):
            resp = client_with_modules.post(
                f"/api/v1/modules/watchfuls/datastore/{method}", json={}
            )
            assert resp.status_code == 404, f"method '{method}' should be blocked"

    def test_dunder_method_names_blocked_by_validation(self, client_with_modules):
        """Action names starting with _ or containing __ are rejected by input
        validation (regex ^[a-z][a-z0-9_]*$ requires lowercase start)."""
        _login(client_with_modules)
        for action in ("__init__", "_private", "__class__"):
            resp = client_with_modules.post(
                f"/api/v1/modules/watchfuls/datastore/{action}", json={}
            )
            assert resp.status_code == 400

    def test_numeric_leading_module_name_rejected(self, client_with_modules):
        """Module names starting with a digit fail the ^[a-z] regex."""
        _login(client_with_modules)
        resp = client_with_modules.get("/api/v1/modules/watchfuls/1ping/discover")
        assert resp.status_code == 400

    def test_long_action_name_not_in_whitelist_returns_404(self, client_with_modules):
        """A valid-regex but very long action name not in WATCHFUL_ACTIONS → 404."""
        _login(client_with_modules)
        long_action = "a" * 200
        resp = client_with_modules.get(f"/api/v1/modules/watchfuls/filesystemusage/{long_action}")
        assert resp.status_code == 404

    def test_enc_prefix_in_post_body_does_not_crash(self, client_with_modules):
        """Attacker-supplied enc:-prefixed values in POST body must be passed
        through to the classmethod as-is without crashing the endpoint.
        The watchful action endpoint does not decrypt config values — that is
        the Monitor's responsibility."""
        _login(client_with_modules)
        captured = {}

        def fake_test(config):
            captured["config"] = config
            return {"ok": True, "message": "ok"}

        with patch("watchfuls.datastore.Watchful.test_connection", side_effect=fake_test):
            resp = client_with_modules.post(
                "/api/v1/modules/watchfuls/datastore/test_connection",
                json={"password": "enc:attacker-payload", "host": "localhost"},
            )
        assert resp.status_code == 200
        assert captured["config"]["password"] == "enc:attacker-payload"

    def test_unauthenticated_user_cannot_call_any_action(self, client_with_modules):
        """No action is reachable without a valid session — always redirects."""
        for method, url in (
            ("GET",  "/api/v1/modules/watchfuls/filesystemusage/discover"),
            ("POST", "/api/v1/modules/watchfuls/datastore/test_connection"),
            ("GET",  "/api/v1/modules/watchfuls/os/discover"),
        ):
            resp = getattr(client_with_modules, method.lower())(url, json={})
            assert resp.status_code == 401, f"{method} {url} must return 401 unauthenticated"


class TestApiWatchfulActionAuthorization:
    """Write actions require modules_edit; read-only actions need only modules_view."""

    @staticmethod
    def _login_viewer(client):
        """Create a viewer user (modules_view, no modules_edit) and log in as them."""
        _login(client)  # as admin
        client.post("/api/v1/users", json={
            "username": "viewer1", "password": "viewerpw", "role": "viewer",
        })
        client.post("/logout")
        client.post("/login", data={"username": "viewer1", "password": "viewerpw"})

    def test_viewer_cannot_run_write_action(self, client_with_modules):
        """A modules_view-only user must NOT be able to delete a MIB (write action)."""
        self._login_viewer(client_with_modules)
        resp = client_with_modules.post(
            "/api/v1/modules/watchfuls/snmp/delete_mib", json={"name": "x.mib", "kind": "raw"}
        )
        assert resp.status_code == 403

    def test_viewer_can_run_read_only_action(self, client_with_modules):
        """A modules_view-only user CAN run a read-only action (list_mibs)."""
        self._login_viewer(client_with_modules)
        resp = client_with_modules.get("/api/v1/modules/watchfuls/snmp/list_mibs")
        assert resp.status_code == 200

    def test_admin_can_run_write_action(self, client_with_modules):
        """Admin (has modules_edit) is not blocked by the authorization gate."""
        _login(client_with_modules)
        resp = client_with_modules.post(
            "/api/v1/modules/watchfuls/snmp/delete_mib", json={"name": "nonexistent.mib", "kind": "raw"}
        )
        assert resp.status_code != 403






# ── Host-aware discovery (Servers modal: run discover on the bound host) ──────


class TestHostAwareDiscovery:
    """POST discover with a host context runs the listing on that host (here a
    remote host, with the SSH command runner mocked)."""

    def test_process_discover_remote_draft(self, client_with_modules):
        c = client_with_modules
        _login(c)
        with patch('lib.core.hosts.runner.run', return_value=('nginx\nnginx\nsshd\n', '', 0)) as run:
            r = c.post('/api/v1/modules/watchfuls/process/discover', json={
                '_host': {'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
                          'profiles': {'ssh': {'ssh_user': 'root'}}},
            })
        assert r.status_code == 200
        names = {s['name'] for s in r.get_json()}
        assert 'nginx' in names and 'sshd' in names
        # The command ran against the remote host context.
        assert run.call_args.args[1] == 'ps -A -o comm='

    def test_service_discover_remote_draft(self, client_with_modules):
        c = client_with_modules
        _login(c)
        out = "  nginx.service   loaded active running  Web server\n"
        with patch('lib.core.hosts.runner.run', return_value=(out, '', 0)):
            r = c.post('/api/v1/modules/watchfuls/service_status/discover', json={
                '_host': {'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
                          'profiles': {'ssh': {'ssh_user': 'root'}}},
            })
        assert r.status_code == 200
        assert any(s['name'] == 'nginx' for s in r.get_json())
