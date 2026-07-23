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
# syslog is enabled by default now; its listener must NOT bind at fixture boot (it would
# grab the privileged port 514 — fails as non-root, and many workers conflict). This env
# var does NOT reach the embedded boot path, so it is not enough on its own — the real
# switch is `syslog: {autostart: False}` in the config_dir fixture below. Kept as a
# belt-and-braces default in case a standalone code path reads it.
os.environ.setdefault('SS_SYSLOG_AUTOSTART', '0')

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
        # Events autostart defaults to True, so WebAdmin.__init__ would boot the
        # background worker (polls audit/syslog every 2s and dispatches). Tests drive
        # evaluation synchronously via _eval_event(); a concurrent worker tick landing
        # inside a test's `mock.patch(dispatch)` window fires a match and flips
        # disp.called → flaky failures. Disable autostart so the worker never starts
        # (events stays embedded; the few tests that need it start it explicitly).
        "events": {"autostart": False},
        # Syslog autostart defaults to True, so WebAdmin.__init__ binds a real UDP+TCP
        # listener on the privileged default port 514. That fails as non-root (CI) and,
        # worse, every test's listener competes on 514 with live sockets → non-deterministic
        # message counts (a test's own listener receives stray traffic, so e.g. stats sees
        # 5 rows where it seeded 3). The env var SS_SYSLOG_AUTOSTART is NOT honoured by the
        # embedded boot path, so it must be set here as config. Syslog stays enabled (the
        # status endpoint reports enabled=True, running=False); tests that exercise the
        # listener start it explicitly on a free port.
        "syslog": {"autostart": False},
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
    wa._csrf_enabled = False   # CSRF is exercised by dedicated tests; off elsewhere
                               # so the many form/JSON POSTs need no token plumbing.
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
    yield wa
    # Teardown — stop the background workers this WebAdmin started in __init__
    # (per-service heartbeat lease loop + any scheduler/worker). Without this every
    # test leaks live threads and the full suite piles up CPU/RAM until it runs away.
    for _svc in getattr(wa, "_embedded_services", {}).values():
        try:
            _svc.stop_heartbeat()
        except Exception:
            pass
        try:
            _svc.stop()
        except Exception:
            try:
                _svc.control("stop")
            except Exception:
                pass


@pytest.fixture()
def client(admin):
    """Flask test client (not logged in)."""
    admin.app.config["TESTING"] = True
    return admin.app.test_client()


def _login(client, username="admin", password="secret"):
    """Helper — POST to /login and follow redirects.

    CSRF-aware: GETs /login first to seed the session CSRF token and includes it, so it
    works whether the instance has CSRF enabled (default) or disabled (the `admin`
    fixture)."""
    client.get("/login")
    with client.session_transaction() as s:
        tok = s.get("_csrf")
    data = {"username": username, "password": password}
    if tok:
        data["csrf_token"] = tok
    return client.post("/login", data=data, follow_redirects=True)
