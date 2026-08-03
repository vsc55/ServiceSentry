#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the standalone syslog receiver (``lib.services.syslog.service.SyslogService``).

The service shares the database and config with the rest of the app, so the
``admin`` fixture is reused to lay down the config dir, secret key and DB; the
service is then built against the same directories and exercised on its own.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_syslog_service.py`` lives in ``tests/integration/test_syslog_service.py``."""

from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    from lib.services.syslog.service import SyslogService
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


@pytest.fixture()
def service(admin):
    """A SyslogService sharing the admin's config dir / var dir / database."""
    svc = SyslogService(admin._config_dir, admin._var_dir)
    yield svc
    svc.stop()






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




