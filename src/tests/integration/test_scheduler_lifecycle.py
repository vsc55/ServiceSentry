#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scheduler start/stop lifecycle: single actor-aware audit + opt-in notification.

Covers the two fixes for "Scheduler: Started/Stopped shows duplicated in the audit
log and never notifies":
  * ``_audit_auto`` writes ONE row — attributed to the request user when a Flask
    context is active, to 'system' otherwise (no more admin + system pair).
  * the scheduler forwards its lifecycle change to the notification router as a
    discovered ``scheduler_started`` / ``scheduler_stopped`` event.


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_scheduler_lifecycle.py`` lives in ``tests/unit/test_scheduler_lifecycle.py``."""

import pytest

from lib.core.notify import events as notify_events

# Tests de integración: sin Flask no pueden correr. Con guarda saltan limpio, que es lo que
# hacen los otros 54 ficheros de integration/; sin ella tumbaban la colección de la suite.
try:
    import flask
    from lib.core.audit.mixin import _AuditMixin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False
    flask = None
    _AuditMixin = object

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


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


