#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background-service defects found by the 2026-10-12 audit, through a real WebAdmin.

- The event worker's cursor skipped a row committed after a later one (concurrent writers on
  PostgreSQL/MySQL), and a cursor past the end of its table (a dedicated syslog database
  switched on, a restore) was never re-seeded: no rule fired again.
- A queued «run now» ran the whole cycle on the heartbeat thread, which also renews the
  lease: a long cycle let a standby take it.
- A module whose state failed to save was re-read from the database at the next cycle and
  re-alerted every cycle.
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

_DISP = 'lib.core.notify.notification_dispatcher.dispatch'


def _audit_row(admin, rid, event='login_failed'):
    """An audit row with an id chosen by the test — the shape of a late commit."""
    db = admin._audit_store._db
    db.execute('INSERT INTO audit (id, ts, event, "user", ip, detail) VALUES (?, ?, ?, ?, ?, ?)',
               (rid, '2026-10-12T00:00:00+00:00', event, 'x', '127.0.0.1', '{}'))
    db.commit()


@pytest.fixture()
def worker(admin, client):
    from tests.conftest import _login                               # noqa: PLC0415
    _login(client)
    client.post('/api/v1/event/rules', json={'name': 'w', 'source': 'audit',
                                             'events': ['login_failed'], 'channels': ['telegram'],
                                             # Every match must fire here; a new rule's own
                                             # default (60 s) would swallow the second one.
                                             'cooldown': 0})
    ev = admin._embedded_services['events']
    ev._is_leader = True
    return ev


class TestEventCursor:

    def test_a_row_committed_late_below_the_cursor_is_still_evaluated(self, admin, worker):
        base = admin._audit_store.max_id() + 10
        _audit_row(admin, base)
        worker._event_state.set_cursor('audit', base - 1)
        with mock.patch(_DISP):
            assert worker._event_worker_tick() >= 1
        assert worker._event_state.cursor('audit') == base
        _audit_row(admin, base - 3)                     # visible only now, below the cursor
        with mock.patch(_DISP) as disp:
            worker._event_worker_tick()
        assert disp.called, 'the late row reached the rules'
        with mock.patch(_DISP) as disp:
            worker._event_worker_tick()
        assert not disp.called, 'and only once'

    def test_a_cursor_past_the_end_is_reseeded(self, admin, worker):
        worker._event_state.set_cursor('audit', 10 ** 9)
        with mock.patch(_DISP):
            worker._event_worker_tick()
        assert worker._event_state.cursor('audit') <= admin._audit_store.max_id()
        admin._audit_system('login_failed', detail={})
        with mock.patch(_DISP) as disp:
            worker._event_worker_tick()
        assert disp.called

    def test_a_reseed_does_not_replay_the_rows_behind_the_new_cursor(self, admin, worker):
        with mock.patch(_DISP):
            worker._event_worker_tick()             # the late-window cache now exists
        # A restored table: its rows were evaluated by an earlier life, never by this cache.
        _audit_row(admin, admin._audit_store.max_id() + 5)
        worker._event_state.set_cursor('audit', 10 ** 9)
        with mock.patch(_DISP) as disp:
            worker._event_worker_tick()
        assert not disp.called, 'the rows behind the re-seeded cursor were replayed'


class TestRunNow:

    def test_run_now_does_not_hold_the_heartbeat(self, admin):
        mon = admin._embedded_services.get('monitoring') or admin
        if not hasattr(mon, '_apply_command'):
            pytest.skip('no monitoring service in this build')
        suelta = threading.Event()
        with mock.patch.object(type(mon), '_work_allowed', return_value=True, create=True), \
                mock.patch.object(mon, '_monitoring_run_one_cycle', side_effect=lambda: suelta.wait(5)):
            t0 = time.monotonic()
            ok, msg = mon._apply_command('run_now', {})
            assert ok and msg == 'started' and time.monotonic() - t0 < 1
            assert mon._apply_command('run_now', {}) == (False, 'busy'), 'one at a time'
            suelta.set()
            for _ in range(100):
                if mon._check_lock.acquire(blocking=False):
                    mon._check_lock.release()
                    break
                time.sleep(0.05)
            else:
                pytest.fail('the lock was never released')
