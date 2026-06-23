#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the standalone syslog receiver (``lib.syslog.service.SyslogService``).

The service shares the database and config with the rest of the app, so the
``admin`` fixture is reused to lay down the config dir, secret key and DB; the
service is then built against the same directories and exercised on its own.
"""

import socket
import time
from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    from lib.syslog.service import SyslogService
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture()
def service(admin):
    """A SyslogService sharing the admin's config dir / var dir / database."""
    svc = SyslogService(admin._config_dir, admin._var_dir)
    yield svc
    svc.stop()


class TestContextSurface:
    """The minimal surface the notification dispatcher relies on."""

    def test_reads_shared_config(self, admin, service):
        admin._write_config({'syslog': {'enabled': True, 'retention_days': 7}})
        admin._invalidate_config_cache()
        cfg = service._config_section('syslog')
        assert cfg.get('enabled') is True
        assert int(cfg.get('retention_days')) == 7

    def test_load_webhooks_returns_list(self, service):
        assert isinstance(service._load_webhooks(), list)

    def test_read_config_file_is_effective(self, admin, service):
        admin._write_config({'notifications': {'telegram_on_syslog': True}})
        admin._invalidate_config_cache()
        cfg = service._read_config_file(service._CONFIG_FILE)
        assert (cfg.get('notifications') or {}).get('telegram_on_syslog') is True


class TestReceive:

    def test_udp_message_is_stored(self, admin, service):
        port = _free_port()
        admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                        'udp_port': port}})
        admin._invalidate_config_cache()
        problems = service._apply_config()
        assert problems == [] and service._server is not None
        c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        c.sendto(b'<34>Oct 11 22:14:15 myhost su: failed login', ('127.0.0.1', port))
        c.close()
        deadline = time.time() + 3.0
        while service._syslog_store.count() == 0 and time.time() < deadline:
            time.sleep(0.05)
        rows = service._syslog_store.query(limit=10)
        assert any('su' in (r.get('app') or '') or 'failed' in (r.get('message') or '')
                   for r in rows)

    def test_disabled_does_not_bind(self, admin, service):
        admin._write_config({'syslog': {'enabled': False}})
        admin._invalidate_config_cache()
        assert service._apply_config() == []
        assert service._server is None

    def test_enable_only_still_has_default_ports(self, admin, service):
        # Regression: saving just ``enabled`` must not drop the ports — the
        # registry defaults are merged underneath, so the listener still binds.
        admin._write_config({'syslog': {'enabled': True}})
        admin._invalidate_config_cache()
        cfg = service._syslog_cfg()
        assert cfg['enabled'] is True
        assert int(cfg['udp_port']) == 514 and int(cfg['tcp_port']) == 514


class TestAlert:

    def _enable_rule(self, admin, **over):
        cfg = {'alert_enabled': True, 'alert_severity_max': 3, 'alert_regex': ''}
        cfg.update(over)
        admin._write_config({'syslog': cfg})
        admin._invalidate_config_cache()

    def test_alert_dispatched(self, admin, service):
        self._enable_rule(admin)
        with mock.patch('lib.web_admin.notification_dispatcher.dispatch') as disp:
            service._on_message({'severity': 2, 'severity_name': 'crit', 'source': '9.9.9.9',
                                 'message': 'kernel panic', 'hostname': 'h', 'received_at': ''})
        assert disp.called and disp.call_args.kwargs['kind'] == 'syslog'

    def test_no_alert_below_threshold(self, admin, service):
        self._enable_rule(admin)
        with mock.patch('lib.web_admin.notification_dispatcher.dispatch') as disp:
            service._on_message({'severity': 6, 'source': '9.9.9.8', 'message': 'fine',
                                 'hostname': 'h', 'received_at': ''})
        assert not disp.called

    def test_cooldown_suppresses_second(self, admin, service):
        self._enable_rule(admin)
        rec = {'severity': 1, 'severity_name': 'alert', 'source': '9.9.9.7',
               'message': 'down', 'hostname': 'h', 'received_at': ''}
        with mock.patch('lib.web_admin.notification_dispatcher.dispatch') as disp:
            service._on_message(dict(rec))
            service._on_message(dict(rec))
        assert disp.call_count == 1            # second within cooldown is dropped


class TestRun:

    def test_run_stays_alive_when_disabled_then_stops(self, admin, service):
        # Disabled at start: run() must NOT exit (it watches for a later enable),
        # and stop() must unblock it cleanly.
        import threading
        admin._write_config({'syslog': {'enabled': False}})
        admin._invalidate_config_cache()
        rc = []
        t = threading.Thread(target=lambda: rc.append(service.run()), daemon=True)
        t.start()
        t.join(timeout=1.0)
        assert t.is_alive()                    # still running, not exited
        assert service._server is None         # nothing bound while disabled
        service.stop()
        t.join(timeout=3.0)
        assert not t.is_alive() and rc == [0]

    def test_watch_reloads_on_enable(self, admin, service):
        # The config watcher picks up an enable made elsewhere (the web UI) and
        # binds the listener without a restart.
        import threading
        port = _free_port()
        admin._write_config({'syslog': {'enabled': False}})
        admin._invalidate_config_cache()
        t = threading.Thread(target=service.run, daemon=True)
        t.start()
        try:
            t.join(timeout=0.5)
            assert service._server is None
            admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                            'udp_port': port}})
            admin._invalidate_config_cache()
            # force an immediate reload rather than waiting for the poll interval
            service._config_mgr.invalidate()
            service._apply_config()
            assert service._server is not None and service._server.running
        finally:
            service.stop()
            t.join(timeout=3.0)


class TestTraceability:
    """Startup / stop / lifecycle is logged so the standalone process is traceable."""

    def _trace_on(self, service):
        from lib.debug import DebugLevel
        service._debug.enabled = True
        service._debug.level = DebugLevel.debug

    def test_init_is_logged(self, admin, capsys):
        # honour the configured log level: with 'info' the init line is emitted.
        admin._write_config({'global': {'log_level': 'info'}})
        admin._invalidate_config_cache()
        SyslogService(admin._config_dir, admin._var_dir)
        assert 'service init' in capsys.readouterr().out

    def test_init_respects_log_off(self, admin, capsys):
        admin._write_config({'global': {'log_level': 'off'}})
        admin._invalidate_config_cache()
        SyslogService(admin._config_dir, admin._var_dir)
        assert 'service init' not in capsys.readouterr().out

    def test_start_and_stop_are_logged(self, admin, service, capsys):
        self._trace_on(service)
        port = _free_port()
        admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                        'udp_port': port}})
        admin._invalidate_config_cache()
        service._apply_config()
        service.stop()
        out = capsys.readouterr().out
        assert 'starting listener' in out
        assert 'listener started' in out
        assert 'listener stopped' in out

    def test_disabled_is_logged(self, admin, service, capsys):
        import threading
        self._trace_on(service)
        admin._write_config({'syslog': {'enabled': False}})
        admin._invalidate_config_cache()
        t = threading.Thread(target=service.run, daemon=True)
        t.start()
        t.join(timeout=1.0)              # run() blocks (waits for a later enable)
        service.stop()
        t.join(timeout=3.0)
        out = capsys.readouterr().out
        assert 'disabled in config' in out

    def test_alert_match_is_logged(self, admin, service, capsys):
        self._trace_on(service)
        admin._write_config({'syslog': {'alert_enabled': True, 'alert_severity_max': 3}})
        admin._invalidate_config_cache()
        with mock.patch('lib.web_admin.notification_dispatcher.dispatch'):
            service._on_message({'severity': 1, 'severity_name': 'alert', 'source': '7.7.7.7',
                                 'message': 'boom', 'hostname': 'h', 'received_at': ''})
        assert 'alert match' in capsys.readouterr().out
