#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the standalone syslog receiver (``lib.services.syslog.service.SyslogService``).

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
    from lib.services.syslog.service import SyslogService
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _free_port(proto: str = 'tcp') -> int:
    """A free port for *proto* (``'tcp'`` or ``'udp'``).

    Probe with the SAME socket type the caller will bind: the two port spaces are
    independent, so a number free for TCP can already be taken for UDP. Asking the wrong
    one is what made these tests fail under a full parallel run and pass on their own.
    """
    kind = socket.SOCK_DGRAM if proto == 'udp' else socket.SOCK_STREAM
    s = socket.socket(socket.AF_INET, kind)
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

    def test_router_loads_webhooks(self, service):
        # Channel loading is owned by the webhook channel, over the router the service builds.
        from lib.core.notify.webhook import channel as webhook_channel
        assert isinstance(webhook_channel.load(service._notify), list)

    def test_read_config_file_is_effective(self, admin, service):
        admin._write_config({'notifications': {'telegram_on_syslog': True}})
        admin._invalidate_config_cache()
        cfg = service._read_config_file(service._CONFIG_FILE)
        assert (cfg.get('notifications') or {}).get('telegram_on_syslog') is True


class TestReceive:

    def test_udp_message_is_stored(self, admin, service):
        port = _free_port('udp')
        # UDP only: pin TCP/TLS off so the listener never binds the privileged default
        # port 514 (a bind that fails as non-root — e.g. on CI). Configuring just
        # ``udp_port`` would leave ``tcp_port`` at its registry default (514), which the
        # service then tries — and fails — to bind. This test exercises UDP alone.
        admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                        'udp_port': port, 'tcp_port': 0, 'tls_port': 0}})
        admin._invalidate_config_cache()
        problems = service._syslog_apply_config()
        assert problems == [] and service._syslog_server is not None
        assert service._syslog_server._tcp_port == 0   # TCP off → no privileged bind attempted
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
        assert service._syslog_apply_config() == []
        assert service._syslog_server is None

    def test_enable_only_still_has_default_ports(self, admin, service):
        # Regression: saving just ``enabled`` must not drop the ports — the
        # registry defaults are merged underneath, so the listener still binds.
        admin._write_config({'syslog': {'enabled': True}})
        admin._invalidate_config_cache()
        cfg = service._syslog_cfg()
        assert cfg['enabled'] is True
        assert int(cfg['udp_port']) == 514 and int(cfg['tcp_port']) == 514


def _add_syslog_rule(service, **over):
    """Create an enabled syslog event-rule on the service's shared store and make
    the manager pick it up (the standalone service evaluates the same rules)."""
    rule = {'name': 'r', 'enabled': True, 'source': 'syslog',
            'severity_max': 3, 'host': '', 'app': '',
            'match_type': 'any', 'match_text': '',
            'channels': ['webhook'], 'cooldown': 0}
    rule.update(over)
    service._event_rules_store.upsert(rule, actor='test')
    service._events_reload()


class TestAlert:
    """Rule evaluation is decoupled from the standalone listener: it only stores
    messages; the event worker (embedded web admin, or a dedicated events process)
    evaluates them. So the listener itself never dispatches a notification."""

    def test_listener_does_not_dispatch(self, service):
        _add_syslog_rule(service)
        with mock.patch('lib.core.notify.notification_dispatcher.dispatch') as disp:
            service._syslog_store.add({
                'ts': 0.0, 'received_at': '', 'source': '9.9.9.9', 'hostname': 'h',
                'app': '', 'procid': '', 'severity': 2, 'facility': 1, 'msgid': '',
                'message': 'kernel panic', 'raw': ''})
        assert not disp.called

    def test_cooldown_suppresses_second(self, service):
        _add_syslog_rule(service, cooldown=60)
        rec = {'severity': 1, 'severity_name': 'alert', 'source': '9.9.9.7',
               'message': 'down', 'hostname': 'h', 'received_at': ''}
        with mock.patch('lib.core.notify.notification_dispatcher.dispatch') as disp:
            service._eval_event('syslog',dict(rec))
            service._eval_event('syslog',dict(rec))
        assert disp.call_count == 1            # second within cooldown is dropped

    def test_no_rule_no_dispatch(self, service):
        with mock.patch('lib.core.notify.notification_dispatcher.dispatch') as disp:
            service._eval_event('syslog',{'severity': 1, 'source': '9.9.9.6', 'message': 'x',
                                 'hostname': 'h', 'received_at': ''})
        assert not disp.called                 # nothing configured → nothing sent


class TestDedicatedDb:

    def test_disabled_shares_system_db(self, service):
        # No syslog_db config → the syslog store uses the system connector.
        assert service._syslog_db_connector is service._db_connector

    def test_enabled_uses_separate_db(self, admin):
        admin._write_config({'syslog_db': {'enabled': True, 'driver': 'sqlite', 'path': ''}})
        admin._invalidate_config_cache()
        svc = SyslogService(admin._config_dir, admin._var_dir)
        try:
            assert svc._syslog_db_connector is not svc._db_connector
            svc._syslog_store.add({'ts': 1.0, 'received_at': '', 'source': '1.1.1.1',
                                   'hostname': 'h', 'app': 'a', 'procid': '', 'severity': 5,
                                   'facility': 1, 'msgid': '', 'message': 'sep', 'raw': ''})
            assert svc._syslog_store.count() == 1
        finally:
            svc.stop()

    def test_env_enables_dedicated_db(self, admin):
        # Docker: SS_SYSLOG_DB_* env enables a dedicated DB without any saved config.
        with mock.patch.dict('os.environ', {'SS_SYSLOG_DB_ENABLED': 'true',
                                            'SS_SYSLOG_DB_DRIVER': 'sqlite'}):
            svc = SyslogService(admin._config_dir, admin._var_dir)
        try:
            assert svc._syslog_db_connector is not svc._db_connector
        finally:
            svc.stop()


class TestAutostartEnv:
    """SS_SYSLOG_AUTOSTART must overlay onto the effective syslog config.

    Regression: the embedded boot path read the raw config section, which applies neither
    the registry default nor the env override — so SS_SYSLOG_AUTOSTART was silently ignored
    and the listener always bound port 514 (see the config→DB / env-overlay design). The
    fix routes autostart through _syslog_cfg(), which now overlays the section's env vars."""

    def test_env_overrides_effective_config(self, service):
        # _syslog_cfg() is the single source; the env must win over saved/defaults.
        with mock.patch.dict('os.environ', {'SS_SYSLOG_AUTOSTART': 'true'}):
            assert service._syslog_cfg().get('autostart') is True
        with mock.patch.dict('os.environ', {'SS_SYSLOG_AUTOSTART': '0'}):
            assert service._syslog_cfg().get('autostart') is False

    def test_embedded_autostart_honours_env(self, admin):
        # The embedded listener's boot gate reflects the env, not just the True default.
        emb = admin._embedded_services['syslog']
        with mock.patch.dict('os.environ', {'SS_SYSLOG_AUTOSTART': 'true'}):
            assert emb._syslog_autostart() is True
        with mock.patch.dict('os.environ', {'SS_SYSLOG_AUTOSTART': '0'}):
            assert emb._syslog_autostart() is False


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
        assert service._syslog_server is None         # nothing bound while disabled
        service.stop()
        t.join(timeout=3.0)
        assert not t.is_alive() and rc == [0]

    def test_watch_reloads_on_enable(self, admin, service):
        # The config watcher picks up an enable made elsewhere (the web UI) and
        # binds the listener without a restart.
        import threading
        port = _free_port('udp')
        admin._write_config({'syslog': {'enabled': False}})
        admin._invalidate_config_cache()
        t = threading.Thread(target=service.run, daemon=True)
        t.start()
        try:
            t.join(timeout=0.5)
            assert service._syslog_server is None
            admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                            'udp_port': port, 'tcp_port': 0, 'tls_port': 0}})
            admin._invalidate_config_cache()
            # force an immediate reload rather than waiting for the poll interval
            service._config_mgr.invalidate()
            service._syslog_apply_config()
            assert service._syslog_server is not None and service._syslog_server.running
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
        port = _free_port('udp')
        admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                        'udp_port': port, 'tcp_port': 0, 'tls_port': 0}})
        admin._invalidate_config_cache()
        service._syslog_apply_config()
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

    def test_event_rule_match_is_logged(self, service, capsys):
        self._trace_on(service)
        _add_syslog_rule(service)
        with mock.patch('lib.core.notify.notification_dispatcher.dispatch'):
            service._eval_event('syslog',{'severity': 1, 'severity_name': 'alert', 'source': '7.7.7.7',
                                 'message': 'boom', 'hostname': 'h', 'received_at': ''})
        assert 'matched' in capsys.readouterr().out


class TestRouterEnvOverlay:
    """The notification router applies SS_* env on the consumption side (central overlay).

    Regression: telegram credentials set purely via env (Docker) were ignored at send time
    because the router read the raw stored config. `_read_config_file` now overlays env, so
    the cfg every channel sees carries SS_TELEGRAM_*."""

    def test_telegram_env_reaches_the_router_config(self, service):
        with mock.patch.dict('os.environ', {'SS_TELEGRAM_TOKEN': 'ENVT',
                                            'SS_TELEGRAM_CHAT_ID': 'ENVC'}):
            cfg = service._notify._read_config_file()
        assert (cfg.get('telegram') or {}).get('token') == 'ENVT'
        assert (cfg.get('telegram') or {}).get('chat_id') == 'ENVC'




class TestIpbanStandalone:
    """A standalone syslog receiver (Docker, no WebAdmin) must enforce the shared,
    DB-backed fail2ban jail: drop jailed IPs and converge with every replica."""

    def test_builds_a_jail_and_blocks_a_banned_ip(self, service):
        assert service._ipban is not None
        service._ipban.ban('9.9.9.9', duration_secs=3600, reason='test')
        assert service._ipban.is_banned_flag('9.9.9.9') is True
        assert service._ipban.is_banned_flag('1.2.3.4') is False

    def test_listener_is_wired_to_the_jail(self, admin, service):
        # apply_config builds the server with non-null is_banned/on_offense from _ipban
        port = _free_port('udp')
        admin._write_config({'syslog': {'enabled': True, 'bind_host': '127.0.0.1',
                                        'udp_port': port, 'tcp_port': 0, 'tls_port': 0}})
        admin._invalidate_config_cache()
        service._syslog_apply_config()
        srv = service._syslog_server
        assert srv is not None
        assert srv._is_banned is not None and srv._on_offense is not None

    def test_ban_is_shared_across_receivers(self, admin):
        # a second receiver on the SAME main DB sees the ban (shared desired-state)
        s1 = SyslogService(admin._config_dir, admin._var_dir)
        s2 = SyslogService(admin._config_dir, admin._var_dir)
        try:
            s1._ipban.ban('8.8.8.8', duration_secs=3600, reason='x')
            assert s2._ipban.is_banned_flag('8.8.8.8') is True
        finally:
            s1.stop()
            s2.stop()
