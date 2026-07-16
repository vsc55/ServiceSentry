#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service-health evaluator (lib.core.health.health): liveness classification and
one-shot service_down / service_up transition notifications."""

from lib.core.health.health import classify, ServiceHealthMonitor


def _row(key, *, running, age):
    # age = seconds since last beat (now - last_seen)
    return {'service_key': key, 'running': running, 'last_seen': 1000.0 - age}


class TestClassify:
    def test_up_down_idle(self):
        now = 1000.0
        rows = [
            _row('monitoring', running=True, age=5),     # fresh + running → up
            _row('syslog', running=True, age=999),        # stale + running → down (crashed)
            _row('events', running=False, age=999),       # stopped → idle
        ]
        st = classify(rows, now=now, down_after_secs=60)
        assert st == {'monitoring': 'up', 'syslog': 'down', 'events': 'idle'}

    def test_any_fresh_running_instance_makes_service_up(self):
        now = 1000.0
        rows = [_row('m', running=True, age=999), _row('m', running=True, age=2)]
        assert classify(rows, now=now, down_after_secs=60) == {'m': 'up'}

    def test_ignores_blank_service_key(self):
        assert classify([{'service_key': '', 'running': True, 'last_seen': 1000}],
                        now=1000.0, down_after_secs=60) == {}


class _Mon(ServiceHealthMonitor):
    """Convenience: build a monitor over static rows/config with captured emissions."""


def _make(rows, *, enabled=True, leader=True):
    emitted = []
    mon = ServiceHealthMonitor(
        instances_provider=lambda: rows,
        dispatch=lambda kind, **f: emitted.append((kind, f.get('item'))),
        config_getter=lambda: {'notify_down': enabled, 'down_after_secs': 60},
        is_leader=lambda: leader,
    )
    return mon, emitted


class TestTransitions:
    def test_disabled_never_emits(self):
        mon, emitted = _make([_row('m', running=True, age=999)], enabled=False)
        mon.evaluate_once(now=1000.0)
        assert emitted == []

    def test_first_observation_seeds_without_alert(self):
        mon, emitted = _make([_row('m', running=True, age=999)])   # already down at boot
        mon.evaluate_once(now=1000.0)
        assert emitted == []                       # seeded, no boot-time alert
        assert mon._state['m'] == 'down'

    def test_up_to_down_emits_service_down(self):
        rows = [_row('m', running=True, age=2)]
        mon, emitted = _make(rows)
        mon.evaluate_once(now=1000.0)              # seed 'up'
        assert emitted == []
        rows[0] = _row('m', running=True, age=999)  # now stale → down
        mon.evaluate_once(now=1000.0)
        assert emitted == [('service_down', 'm')]

    def test_down_to_up_emits_service_up(self):
        rows = [_row('m', running=True, age=999)]
        mon, emitted = _make(rows)
        mon.evaluate_once(now=1000.0)              # seed 'down'
        rows[0] = _row('m', running=True, age=2)   # recovered
        mon.evaluate_once(now=1000.0)
        assert emitted == [('service_up', 'm')]

    def test_idle_clears_state_and_never_alerts(self):
        rows = [_row('m', running=True, age=2)]
        mon, emitted = _make(rows)
        mon.evaluate_once(now=1000.0)              # seed 'up'
        rows[0] = _row('m', running=False, age=999)  # operator stopped → idle
        mon.evaluate_once(now=1000.0)
        assert emitted == [] and 'm' not in mon._state

    def test_non_leader_updates_state_but_does_not_emit(self):
        rows = [_row('m', running=True, age=2)]
        mon, emitted = _make(rows, leader=False)
        mon.evaluate_once(now=1000.0)              # seed 'up'
        rows[0] = _row('m', running=True, age=999)
        mon.evaluate_once(now=1000.0)
        assert emitted == [] and mon._state['m'] == 'down'   # tracked, but not the leader
