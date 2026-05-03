#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for WebAdmin initialisation and construction."""

import json
import os

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
