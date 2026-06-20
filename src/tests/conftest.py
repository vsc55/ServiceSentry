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

from lib.modules import ModuleBase
from watchfuls.web import Watchful as WebWatchful



# ──────────────────────────── Fixtures ─────────────────────────────

# Sample module/item configuration the tests expect. Seeded directly into the
# DB-backed modules store by the ``admin`` fixture (module config lives in the
# database).
_SAMPLE_MODULES = {
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


@pytest.fixture()
def config_dir(tmp_path):
    """Temporary config directory with a sample config.json."""
    config = {
        "daemon": {"timer_check": 300},
        "global": {"log_level": "off"},
        "telegram": {
            "token": "test-token-123",
            "chat_id": "12345",
            "group_messages": False,
        },
    }
    (tmp_path / "config.json").write_text(
        json.dumps(config, indent=4), encoding="utf-8"
    )
    return str(tmp_path)


@pytest.fixture()
def var_dir(tmp_path):
    """Temporary var directory.

    The working check state lives in the ``check_state`` DB table now; the
    sample state the tests expect (ping/192.168.1.1 OK) is seeded into that
    table by the ``admin`` fixture below.
    """
    d = tmp_path / "var"
    d.mkdir()
    return str(d)


@pytest.fixture()
def admin(config_dir, var_dir):
    """WebAdmin instance with testing config (users are stored in the DB)."""
    wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                  pw_require_upper=False, pw_require_digit=False)
    # Module config lives in the DB — seed the sample.
    wa._save_modules(_SAMPLE_MODULES)
    # The working check state lives in the DB now (no status.json). Seed the
    # sample state the tests expect (ping/192.168.1.1 OK) into check_state.
    if getattr(wa, "_check_state_store", None):
        wa._check_state_store.persist_status(
            {"ping": {"192.168.1.1": {"status": True, "other_data": {}}}}
        )
    return wa


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
