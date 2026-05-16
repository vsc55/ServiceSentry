#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the generic watchful action endpoint: GET|POST /api/watchfuls/<module>/<action>."""

import json
import os
import pathlib
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WATCHFULS_DIR = os.path.join(_SRC_DIR, "watchfuls")
_ADMIN_HASH = generate_password_hash("secret", method="pbkdf2:sha256")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client_with_modules(tmp_path):
    """Flask test client with modules_dir pointing to the real watchfuls directory."""
    config_dir = str(tmp_path / "config")
    var_dir = str(tmp_path / "var")
    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(var_dir, exist_ok=True)

    users = {
        "admin": {
            "password_hash": _ADMIN_HASH,
            "role": "admin",
            "display_name": "Administrator",
        }
    }
    (pathlib.Path(config_dir) / "users.json").write_text(
        json.dumps(users, indent=4), encoding="utf-8"
    )
    (pathlib.Path(config_dir) / "modules.json").write_text("{}", encoding="utf-8")
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
        resp = client.get("/api/watchfuls/filesystemusage/discover")
        assert resp.status_code == 302

    def test_post_requires_auth(self, client):
        resp = client.post("/api/watchfuls/datastore/test_connection", json={})
        assert resp.status_code == 302


# ── Input validation ──────────────────────────────────────────────────────────


class TestApiWatchfulActionValidation:
    """Module name and action name are validated before any import."""

    def test_invalid_module_name_uppercase(self, client):
        _login(client)
        resp = client.get("/api/watchfuls/FILESYSTEMUSAGE/discover")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_invalid_module_name_with_dash(self, client):
        _login(client)
        resp = client.get("/api/watchfuls/file-system/discover")
        assert resp.status_code == 400

    def test_invalid_action_name_uppercase(self, client):
        _login(client)
        resp = client.get("/api/watchfuls/filesystemusage/DISCOVER")
        assert resp.status_code == 400

    def test_invalid_action_name_with_dash(self, client):
        _login(client)
        resp = client.get("/api/watchfuls/filesystemusage/get-list")
        assert resp.status_code == 400

    def test_no_modules_dir_returns_404(self, client):
        """Default admin fixture has no modules_dir → 404 before any import."""
        _login(client)
        resp = client.get("/api/watchfuls/filesystemusage/discover")
        assert resp.status_code == 404


# ── Dispatch ──────────────────────────────────────────────────────────────────


class TestApiWatchfulActionDispatch:
    """Module loading, WATCHFUL_ACTIONS whitelist and response plumbing."""

    def test_unknown_module_returns_404(self, client_with_modules):
        _login(client_with_modules)
        resp = client_with_modules.get("/api/watchfuls/nonexistent_xyz/discover")
        assert resp.status_code == 404

    def test_action_not_in_watchful_actions_returns_404(self, client_with_modules):
        """'check' is a real method but NOT in datastore's WATCHFUL_ACTIONS."""
        _login(client_with_modules)
        resp = client_with_modules.post("/api/watchfuls/datastore/check", json={})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "Action not supported"

    def test_get_discover_filesystemusage(self, client_with_modules):
        """GET discover calls cls.discover() and returns the list."""
        _login(client_with_modules)
        fake_items = [{"key": "sda1", "label": "/dev/sda1", "mount": "/"}]
        with patch("watchfuls.filesystemusage.Watchful.discover", return_value=fake_items):
            resp = client_with_modules.get("/api/watchfuls/filesystemusage/discover")
        assert resp.status_code == 200
        assert resp.get_json() == fake_items

    def test_post_test_connection_datastore(self, client_with_modules):
        """POST test_connection calls cls.test_connection(config) and returns result."""
        _login(client_with_modules)
        fake_result = {"ok": True, "message": "MySQL / MariaDB: connection successful"}
        with patch("watchfuls.datastore.Watchful.test_connection", return_value=fake_result):
            resp = client_with_modules.post(
                "/api/watchfuls/datastore/test_connection",
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
                "/api/watchfuls/datastore/list_databases",
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
            resp = client_with_modules.get("/api/watchfuls/filesystemusage/discover")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["ok"] is False
        assert "boom" in data["message"]

    def test_post_empty_body_passes_empty_dict(self, client_with_modules):
        """POST with no JSON body must call the action with an empty dict."""
        _login(client_with_modules)
        captured = {}

        def fake_test_connection(config):
            captured["config"] = config
            return {"ok": True, "message": "ok"}

        with patch(
            "watchfuls.datastore.Watchful.test_connection",
            side_effect=fake_test_connection,
        ):
            client_with_modules.post("/api/watchfuls/datastore/test_connection")

        assert captured.get("config") == {}

    def test_get_discover_service_status(self, client_with_modules):
        """GET discover works on service_status module."""
        _login(client_with_modules)
        fake_items = [{"key": "nginx", "label": "nginx"}]
        with patch("watchfuls.service_status.Watchful.discover", return_value=fake_items):
            resp = client_with_modules.get("/api/watchfuls/service_status/discover")
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
            resp = client_with_modules.get(f"/api/watchfuls/{name}/discover")
            assert resp.status_code == 404, f"stdlib module '{name}' should be blocked"

    def test_third_party_package_names_return_404(self, client_with_modules):
        """Third-party packages not under watchfuls/ resolve to watchfuls.<name>
        which doesn't exist — they must not be imported."""
        _login(client_with_modules)
        for name in ("flask", "paramiko", "requests", "psutil", "pytest"):
            resp = client_with_modules.get(f"/api/watchfuls/{name}/discover")
            assert resp.status_code == 404, f"package '{name}' should be blocked"

    def test_private_and_base_methods_blocked_by_whitelist(self, client_with_modules):
        """Methods that exist on the Watchful class but are NOT in WATCHFUL_ACTIONS
        must return 404 — the whitelist is the only gate."""
        _login(client_with_modules)
        for method in ("check", "get_conf", "send_message", "discover_schemas",
                       "is_enabled", "check_status"):
            resp = client_with_modules.post(
                f"/api/watchfuls/datastore/{method}", json={}
            )
            assert resp.status_code == 404, f"method '{method}' should be blocked"

    def test_dunder_method_names_blocked_by_validation(self, client_with_modules):
        """Action names starting with _ or containing __ are rejected by input
        validation (regex ^[a-z][a-z0-9_]*$ requires lowercase start)."""
        _login(client_with_modules)
        for action in ("__init__", "_private", "__class__"):
            resp = client_with_modules.post(
                f"/api/watchfuls/datastore/{action}", json={}
            )
            assert resp.status_code == 400

    def test_numeric_leading_module_name_rejected(self, client_with_modules):
        """Module names starting with a digit fail the ^[a-z] regex."""
        _login(client_with_modules)
        resp = client_with_modules.get("/api/watchfuls/1ping/discover")
        assert resp.status_code == 400

    def test_long_action_name_not_in_whitelist_returns_404(self, client_with_modules):
        """A valid-regex but very long action name not in WATCHFUL_ACTIONS → 404."""
        _login(client_with_modules)
        long_action = "a" * 200
        resp = client_with_modules.get(f"/api/watchfuls/filesystemusage/{long_action}")
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
                "/api/watchfuls/datastore/test_connection",
                json={"password": "enc:attacker-payload", "host": "localhost"},
            )
        assert resp.status_code == 200
        assert captured["config"]["password"] == "enc:attacker-payload"

    def test_unauthenticated_user_cannot_call_any_action(self, client_with_modules):
        """No action is reachable without a valid session — always redirects."""
        for method, url in (
            ("GET",  "/api/watchfuls/filesystemusage/discover"),
            ("POST", "/api/watchfuls/datastore/test_connection"),
            ("GET",  "/api/watchfuls/os/discover"),
        ):
            resp = getattr(client_with_modules, method.lower())(url, json={})
            assert resp.status_code == 302, f"{method} {url} must redirect unauthenticated"
