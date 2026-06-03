#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for WebAdmin initialisation and construction."""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


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

    def test_creates_default_admin_on_first_run(self, config_dir):
        """Default admin is created in the DB on first run (no JSON file needed)."""
        wa = WebAdmin(config_dir, "myadmin", "mypass")
        users = wa._users_store.load()
        assert "myadmin" in users
        assert wa._uid_to_role_name(users["myadmin"]["role"]) == "admin"
        assert "password_hash" in users["myadmin"]

    def test_existing_db_users_are_preserved(self, config_dir):
        """Users already in the DB are loaded on subsequent starts (no overwrite)."""
        import uuid as _uuid
        from lib.web_admin.constants import BUILTIN_ROLE_UIDS
        # First start: creates default admin
        wa1 = WebAdmin(config_dir, "myadmin", "mypass")
        wa1._users["existinguser"] = {
            'uid':           str(_uuid.uuid4()),
            'password_hash': generate_password_hash("existingpass"),
            'role':          BUILTIN_ROLE_UIDS['editor'],
            'display_name':  "Existing",
        }
        wa1._persist_users()
        # Second start: must load existing users, not overwrite
        wa2 = WebAdmin(config_dir, "ignored", "ignored")
        assert "existinguser" in wa2._users
        assert "ignored" not in wa2._users
