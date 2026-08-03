#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the service command queue API (/api/v1/services/<k>/command/<a>)."""

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


class TestServiceCommands:

    def test_requires_auth(self, client):
        assert client.post(
            '/api/v1/services/monitoring/command/reload').status_code == 401

    def test_bad_action_400(self, client):
        _login(client)
        r = client.post('/api/v1/services/monitoring/command/frobnicate')
        assert r.status_code == 400
        assert r.get_json()['reason'] == 'bad_action'

    def test_unknown_service_404(self, client):
        _login(client)
        r = client.post('/api/v1/services/nope/command/reload')
        assert r.status_code == 404
        assert r.get_json()['reason'] == 'unknown_service'

    def test_read_only_service_rejected(self, client):
        _login(client)
        # 'database' is a read-only view → takes no commands.
        r = client.post('/api/v1/services/database/command/reload')
        assert r.status_code == 409
        assert r.get_json()['reason'] == 'not_controllable'

    def test_reload_enqueues_and_runs_when_embedded(self, admin, client, monkeypatch):
        _login(client)
        # Host the monitor embedded here so the command drains synchronously.
        monkeypatch.setenv('SS_MONITORING_EMBEDDED', '1')
        r = client.post('/api/v1/services/monitoring/command/reload')
        assert r.status_code == 200
        body = r.get_json()
        assert body['ok'] is True
        assert body['command_id'] is not None
        # The command was claimed + completed in the shared queue.
        rows = admin._service_commands_store.list_recent('monitoring')
        assert rows and rows[0]['action'] == 'reload'
        assert rows[0]['done_at'] is not None
        assert rows[0]['ok'] is True

    def test_enqueued_only_when_external(self, admin, client, monkeypatch):
        _login(client)
        # A dedicated container owns monitoring → the web process must NOT run it;
        # the command is queued for the remote worker to claim.
        monkeypatch.setenv('SS_MONITORING_EMBEDDED', '0')
        r = client.post('/api/v1/services/monitoring/command/reload')
        assert r.status_code == 200 and r.get_json()['ok'] is True
        rows = admin._service_commands_store.list_recent('monitoring')
        assert rows and rows[0]['claimed_at'] is None     # left for the remote worker
        assert rows[0]['done_at'] is None
