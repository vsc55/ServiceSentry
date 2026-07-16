#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scheduler start/stop lifecycle: single actor-aware audit + opt-in notification.

Covers the two fixes for "Scheduler: Started/Stopped shows duplicated in the audit
log and never notifies":
  * ``_audit_auto`` writes ONE row — attributed to the request user when a Flask
    context is active, to 'system' otherwise (no more admin + system pair).
  * the scheduler forwards its lifecycle change to the notification router as a
    discovered ``scheduler_started`` / ``scheduler_stopped`` event.
"""

import flask
import pytest

from lib.core.audit.mixin import _AuditMixin
from lib.core.notify import events as notify_events
from lib.services.monitoring.manager import _MonitoringMixin


class _FakeAudit(_AuditMixin):
    """Captures audit writes without a DB."""

    def __init__(self):
        self.rows = []

    def _audit_write(self, event, user, ip, detail):
        self.rows.append((event, user, ip, detail))


class TestAuditAutoDedup:

    def test_background_writes_a_single_system_row(self):
        # No Flask request context (autostart / scheduler thread) → 'system'/'internal'.
        a = _FakeAudit()
        a._audit_auto('daemon_started', {'run_now': True})
        assert a.rows == [('daemon_started', 'system', 'internal', {'run_now': True})]

    def test_request_context_attributes_to_the_actor(self):
        # A manual start (inside a request, logged in) → the actor, not 'system'.
        a = _FakeAudit()
        app = flask.Flask(__name__)
        app.secret_key = 'x'
        with app.test_request_context('/', environ_base={'REMOTE_ADDR': '192.168.0.1'}):
            flask.session['username'] = 'admin'
            a._audit_auto('daemon_started', {'run_now': False})
        assert a.rows == [('daemon_started', 'admin', '192.168.0.1', {'run_now': False})]

    def test_request_context_without_login_falls_back_to_system(self):
        a = _FakeAudit()
        app = flask.Flask(__name__)
        app.secret_key = 'x'
        with app.test_request_context('/'):
            a._audit_auto('daemon_stopped', {})
        assert a.rows[-1][1:3] == ('system', 'internal')


class TestSchedulerNotify:

    def test_start_stop_are_discovered_matrix_events(self):
        keys = notify_events.matrix_event_keys()
        assert 'scheduler_started' in keys and 'scheduler_stopped' in keys

    @pytest.mark.parametrize('kind, expected_msg', [
        ('scheduler_started', 'Scheduler started (every 60s)'),
        ('scheduler_stopped', 'Scheduler stopped'),
    ])
    def test_lifecycle_dispatches_a_translated_body(self, monkeypatch, kind, expected_msg):
        calls = []
        monkeypatch.setattr('lib.core.notify.notification_dispatcher.dispatch',
                            lambda wa, **kw: calls.append(kw))
        m = _MonitoringMixin.__new__(_MonitoringMixin)
        m._CONFIG_FILE = 'x'
        m._read_config_file = lambda _f: {}      # empty cfg → default (en_EN) notification language
        # Args after the kind fill the message template's {} (interval for started).
        m._monitoring_notify(kind, *([60] if kind == 'scheduler_started' else []))
        assert len(calls) == 1
        assert calls[0]['kind'] == kind and calls[0]['module'] == 'scheduler'
        assert calls[0]['message'] == expected_msg
