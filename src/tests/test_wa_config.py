#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for config routes: /api/config (GET, PUT)."""

import json
import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── API: config ──────────────────────────

class TestApiConfig:
    """GET / PUT /api/config."""

    def test_get_requires_auth(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 302

    def test_put_requires_auth(self, client):
        resp = client.put("/api/config", json={})
        assert resp.status_code == 302

    def test_get_returns_data(self, client):
        _login(client)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["daemon"]["timer_check"] == 300
        assert data["telegram"]["token"] == "test-token-123"

    def test_put_saves_data(self, client, config_dir):
        _login(client)
        new = {"daemon": {"timer_check": 600}, "global": {"debug": True}}
        resp = client.put("/api/config", json=new)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        with open(f"{config_dir}/config.json", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["daemon"]["timer_check"] == 600

    def test_put_invalid_json(self, client):
        _login(client)
        resp = client.put(
            "/api/config", data="{bad", content_type="application/json"
        )
        assert resp.status_code == 400
