#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the Services dashboard API (/api/v1/services)."""

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


class TestServicesStatus:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/services').status_code == 401

    def test_status_lists_all_services(self, client):
        _login(client)
        r = client.get('/api/v1/services')
        assert r.status_code == 200
        s = r.get_json()['services']
        # The core services are always present; 'database_syslog' appears only when
        # syslog uses a dedicated DB (absent here — sqlite shared).
        assert {'monitoring', 'syslog', 'worker', 'database'} <= set(s)
        assert 'database_syslog' not in s
        # each carries a state + the control/embedded flags the UI relies on
        for svc in s.values():
            assert 'state' in svc and 'controllable' in svc and 'embedded' in svc

    def test_database_reports_driver_and_connectivity(self, client):
        _login(client)
        db = client.get('/api/v1/services').get_json()['services']['database']
        assert db['driver'] in ('sqlite', 'mysql', 'mariadb', 'postgresql')
        assert db['state'] == 'running'        # in-test sqlite is reachable
        assert db['controllable'] is False

    def test_worker_reflects_history_activity(self, admin, client):
        _login(client)
        # No recent history → worker unknown/stale, never crashes.
        st = client.get('/api/v1/services').get_json()['services']['worker']
        assert st['state'] in ('unknown', 'stale', 'active', 'embedded')
        assert st['controllable'] is False


class TestMonitoringControl:

    def test_start_then_stop(self, admin, client, monkeypatch):
        _login(client)
        # The monitor is start/stop-able only when hosted embedded here; the test
        # harness disables that by default (SS_MONITORING_EMBEDDED=0), so enable it.
        monkeypatch.setenv('SS_MONITORING_EMBEDDED', '1')
        r = client.post('/api/v1/services/monitoring/start')
        assert r.status_code == 200 and r.get_json()['ok'] is True
        assert admin._embedded_services['monitoring'].running is True
        r = client.post('/api/v1/services/monitoring/stop')
        assert r.status_code == 200 and r.get_json()['ok'] is True
        assert admin._embedded_services['monitoring'].running is False

    def test_unknown_service_404(self, client):
        _login(client)
        assert client.post('/api/v1/services/nope/start').status_code == 404

    def test_bad_action_400(self, client):
        _login(client)
        assert client.post('/api/v1/services/monitoring/frobnicate').status_code == 400


class TestSyslogControl:

    def test_start_disabled_is_409(self, admin, client):
        _login(client)
        admin._write_config({'syslog': {'enabled': False}})
        admin._invalidate_config_cache()
        r = client.post('/api/v1/services/syslog/start')
        assert r.status_code == 409
        assert r.get_json()['reason'] == 'disabled'

    def test_start_stop_when_enabled(self, admin, client):
        _login(client)
        # pick a free TCP port to avoid privileged 514 in CI
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
        admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                        'udp_port': port}})
        admin._invalidate_config_cache()
        r = client.post('/api/v1/services/syslog/start')
        assert r.status_code == 200 and r.get_json()['ok'] is True
        assert admin._services_status_dict()['syslog']['running'] is True
        r = client.post('/api/v1/services/syslog/stop')
        assert r.status_code == 200 and r.get_json()['ok'] is True
        assert admin._services_status_dict()['syslog']['running'] is False


class TestPermissions:

    def test_control_requires_services_control(self, admin, client, monkeypatch):
        _login(client)
        # Strip services_control from the logged-in user's effective permissions.
        orig = admin._get_session_permissions

        def _no_control():
            return frozenset(p for p in orig() if p != 'services_control')
        monkeypatch.setattr(admin, '_get_session_permissions', _no_control)
        assert client.post('/api/v1/services/monitoring/start').status_code == 403
        # …but viewing is still allowed (services_view retained)
        assert client.get('/api/v1/services').status_code == 200
