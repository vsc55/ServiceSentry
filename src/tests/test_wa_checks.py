#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the /api/checks/run endpoint."""

import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


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
