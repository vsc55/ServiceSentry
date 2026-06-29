#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared fixtures and helpers for the web_admin test suite."""

import json
import os
import unittest.mock

import pytest

# Keep the background event worker out of the test harness: tests drive evaluation
# directly (``_eval_event`` / ``_event_worker_tick``) so a polling thread never
# interferes with mocked-dispatch assertions.
os.environ.setdefault('SS_EVENTS_EMBEDDED', '0')
os.environ.setdefault('SS_MONITORING_EMBEDDED', '0')

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
        "monitoring": {"timer_check": 300},
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


def _seed_editable_config(wa, config_dir):
    """Move the sample editable config from config.json into the DB.

    The production file→DB migration was removed (data already migrated), so for
    tests we replicate it: a field left in config.json is a read-only override, so
    to exercise *editable* config we clear the sample from the file and seed it
    into the DB (the single source) through the normal write path.
    """
    p = os.path.join(config_dir, "config.json")
    try:
        with open(p, encoding="utf-8") as f:
            sample = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if not sample:
        return
    with open(p, "w", encoding="utf-8") as f:
        json.dump({}, f)
    wa._config_mgr.invalidate()
    wa._read_config_file(wa._CONFIG_FILE)   # recompute file_locked from the now-empty file
    wa._write_config(sample)
    wa._apply_saved_config()
    wa._apply_log_level()


@pytest.fixture()
def admin(config_dir, var_dir):
    """WebAdmin instance with testing config (users are stored in the DB)."""
    wa = WebAdmin(config_dir, "admin", "secret", var_dir,
                  pw_require_upper=False, pw_require_digit=False)
    # Editable config lives in the DB (single source) — seed the sample there.
    _seed_editable_config(wa, config_dir)
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
