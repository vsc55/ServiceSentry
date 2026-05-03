#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared fixtures and helpers for the web_admin test suite."""

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
