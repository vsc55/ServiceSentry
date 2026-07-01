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

    def test_external_runtime_overlaid_from_leader(self, admin):
        # An external service's card takes its live next/last-run from the leader
        # instance's heartbeat, not the web's idle stub.
        entry = {'state': 'external', 'running': False, 'detail': [
            {'label_key': 'svc_next_run', 'value': None, 'fmt': 'in'},
            {'label_key': 'svc_last_run', 'value': None, 'fmt': 'ago'},
        ]}
        insts = [{'detail': {'leader': True, 'next_in': 12},
                  'last_cycle_at': 1000.0, 'derived_state': 'alive'}]
        admin._overlay_external_runtime(entry, insts)
        rows = {r['label_key']: r['value'] for r in entry['detail']}
        assert rows['svc_next_run'] == 12
        assert rows['svc_last_run'] == 1000.0
        assert entry['running'] is True


class TestPoke:

    def test_poke_reaches_stopped_instance(self, admin, monkeypatch):
        # Regression: a Services-tab start of a STOPPED external instance (heartbeating,
        # control server up) must poke it now — the old filter skipped 'stopped' and
        # only the 15s watch tick would eventually apply it.
        import lib.web_admin.mixins.services as svcmod

        class _Immediate:                      # run the poke thread synchronously
            def __init__(self, target, args=(), daemon=None):
                self._t, self._a = target, args

            def start(self):
                self._t(*self._a)
        monkeypatch.setattr(svcmod.threading, 'Thread', _Immediate)
        monkeypatch.setenv('SS_CONTROL_TOKEN', 'tok')
        poked = []
        monkeypatch.setattr(admin, '_poke_one', lambda url, token: poked.append(url))
        monkeypatch.setattr(admin, '_service_instances_list', lambda key=None: [
            {'control_url': 'http://syslog:8765', 'is_self': False, 'derived_state': 'stopped'},
            {'control_url': 'http://dead:8765', 'is_self': False, 'derived_state': 'down'},
        ])
        admin._poke_service_instances('syslog')
        # the stopped (reachable) instance is poked; the down (unreachable) one is not
        assert poked == ['http://syslog:8765/control/reconcile']


class TestDebugAccessor:

    def test_debug_property_applies_log_level(self, admin):
        # Regression: main.py --log-level (SS_LOG_LEVEL) does
        # ``admin.debug.set_from_config(level)``; the property must exist and work
        # (it was missing, so any non-empty SS_LOG_LEVEL crashed the web at boot).
        admin.debug.set_from_config('debug')
        assert admin.debug.enabled is True
        admin.debug.set_from_config('off')
        assert admin.debug.enabled is False


class TestExternalControl:
    """A service owned by a dedicated container (SS_*_EMBEDDED=0) is controllable
    from the Services tab: start/stop edits the shared desired-state it reconciles,
    not a local thread."""

    def test_external_monitoring_is_controllable(self, admin):
        # Harness default: SS_MONITORING_EMBEDDED=0 → monitoring is external.
        st = admin._services_status_dict()['monitoring']
        assert st['state'] == 'external'
        assert st['controllable'] is True and st['embedded'] is False

    def test_external_start_stop_writes_enabled(self, admin):
        # stop → monitoring|enabled False; start → True (desired-state knob).
        ok, reason = admin._service_control('monitoring', 'stop')
        assert ok is True and reason == ''
        assert admin._config_section('monitoring').get('enabled') is False
        ok, reason = admin._service_control('monitoring', 'start')
        assert ok is True and reason == ''
        assert admin._config_section('monitoring').get('enabled') is True

    def test_external_events_stop_sets_enabled_false(self, admin):
        # Harness default: SS_EVENTS_EMBEDDED=0 → events is external; stop → enabled false.
        ok, reason = admin._service_control('events', 'stop')
        assert ok is True and reason == ''
        assert admin._config_section('events').get('enabled') is False
        # And the worker idles when disabled, even when it holds the lease.
        evsvc = admin._embedded_services['events']
        evsvc._is_leader = True
        assert evsvc._event_worker_tick() == 0
        # start → enabled true, worker no longer gated by the master switch.
        ok, reason = admin._service_control('events', 'start')
        assert ok is True and reason == ''
        assert admin._config_section('events').get('enabled') is True


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
