#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background loops survive a failing iteration (a DB outage costs one tick).

Every long-running service thread — the heartbeat, the scheduler, the config
watchers, the retention sweeps, the event worker and the health scanners — used
to run its body unguarded, so a single exception (typically a config read while
the database is down) ended the thread for good, with nothing to restart it.
These tests drive each loop with a hook that raises and check it keeps going.
"""

import threading
import time

from lib.services.heartbeat import _HeartbeatMixin


# ── helpers ───────────────────────────────────────────────────────────────────
class _FakeInstances:
    def __init__(self):
        self.beats = 0

    def heartbeat(self, *_a, **_k):
        self.beats += 1

    def clear_others(self, *_a):
        pass

    def mark_down(self, *_a):
        pass

    def prune(self, *_a):
        pass

    def set_env(self, *_a):
        pass


class _FakeLeader:
    """try_acquire answers from a script: True/False, or an exception to raise."""

    def __init__(self):
        self.calls = 0
        self.mode = True

    def try_acquire(self, *_a, **_k):
        self.calls += 1
        if isinstance(self.mode, BaseException):
            raise self.mode
        return self.mode

    def release(self, *_a):
        pass


class _HB(_HeartbeatMixin):
    _HB_KEY = 'monitoring'
    _LEADER_GATED = True

    def __init__(self, detail_raises=False):
        self._service_instances_store = _FakeInstances()
        self._service_leader_store = _FakeLeader()
        self.detail_raises = detail_raises
        self.logged = []

    def _hb_detail(self):
        if self.detail_raises:
            raise RuntimeError('db down (config read)')
        return {}

    def _dbg(self, message, *_a):
        self.logged.append(message)

    def status(self):
        return {}


def _wait_until(pred, timeout=3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _stop_hb(hb):
    t = hb._hb_thread
    hb.stop_heartbeat()
    if t is not None:
        t.join(2)


class _ScriptedStop(threading.Event):
    """An Event whose wait() never sleeps: it records the requested timeout and
    reports 'stopped' once *rounds* waits have been made."""

    def __init__(self, rounds):
        super().__init__()
        self.waits = []
        self._rounds = rounds

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return len(self.waits) >= self._rounds or self.is_set()


# ── S1: heartbeat ─────────────────────────────────────────────────────────────
class TestHeartbeatLoop:

    def test_loop_survives_a_raising_beat(self):
        hb = _HB()
        hb.start_heartbeat(every=0.05)
        try:
            hb.detail_raises = True               # DB goes down after the first beat
            calls = hb._service_leader_store.calls
            assert _wait_until(lambda: hb._service_leader_store.calls >= calls + 3)
            assert hb._hb_thread.is_alive()
            assert any('heartbeat write failed' in m for m in hb.logged)
            hb.detail_raises = False              # DB back → beats are written again
            beats = hb._service_instances_store.beats
            assert _wait_until(lambda: hb._service_instances_store.beats > beats)
        finally:
            _stop_hb(hb)

    def test_failed_renewal_drops_leadership_then_recovers(self):
        hb = _HB()
        hb.start_heartbeat(every=0.05)
        try:
            assert hb._is_leader is True and hb._work_allowed() is True
            hb._service_leader_store.mode = RuntimeError('db down')
            assert _wait_until(lambda: hb._is_leader is False)
            assert hb._work_allowed() is False    # fail safe: no work on an unrenewed lease
            assert hb._hb_thread.is_alive()
            hb._service_leader_store.mode = True
            assert _wait_until(lambda: hb._is_leader is True)
        finally:
            _stop_hb(hb)

    def test_start_survives_db_down_at_boot(self):
        hb = _HB(detail_raises=True)
        hb._service_leader_store.mode = RuntimeError('db down')
        hb.start_heartbeat(every=0.05)           # must not raise
        try:
            assert hb._hb_thread is not None and hb._hb_thread.is_alive()
            assert hb._is_leader is False
            hb.detail_raises = False
            hb._service_leader_store.mode = True
            assert _wait_until(lambda: hb._is_leader is True
                               and hb._service_instances_store.beats > 0)
        finally:
            _stop_hb(hb)


# ── S1/S2: monitoring interval + scheduler loop ─────────────────────────────────
def _bare_monitor(read_config):
    from lib.services.monitoring.service import MonitorService
    svc = MonitorService.__new__(MonitorService)
    svc._env_override_values = {}
    svc._read_config_file = read_config
    svc._dbg = lambda *_a, **_k: None
    svc._monitoring_init_state()
    return svc


def _raise(*_a, **_k):
    raise RuntimeError('db down')


class TestMonitoringInterval:

    def test_hb_detail_survives_config_read_failure(self):
        from lib.config.spec import cfg_default
        svc = _bare_monitor(_raise)
        assert svc._hb_detail() == {'interval': cfg_default('monitoring|timer_check'),
                                    'next_in': None}

    def test_interval_falls_back_to_last_known_value(self):
        cfg = {'monitoring': {'timer_check': 120}}
        svc = _bare_monitor(lambda *_a: cfg)
        assert svc._monitoring_interval == 120
        svc._read_config_file = _raise
        assert svc._monitoring_interval == 120

    def test_scheduler_loop_survives_interval_read_failure(self):
        svc = _bare_monitor(_raise)
        svc._check_lock = threading.Lock()
        cycles = []

        def _cycle():
            cycles.append(1)
            svc._monitoring_stop_event.set()      # leave after this pass
            return {}, []
        svc._monitoring_run_one_cycle = _cycle
        svc._monitoring_loop_body(run_now=True)   # used to raise on the interval read
        assert cycles == [1]
        assert svc._monitoring_next_run_ts == 0.0


# ── S2: config watchers ─────────────────────────────────────────────────────────
def _drive_watch_loop(monkeypatch, module, cls, extra=None):
    """Run cls._watch_loop with a reconcile that always raises; it must keep
    polling until stopped (stop is set on the third call)."""
    monkeypatch.setattr(module, '_CONFIG_WATCH_EVERY', 0.01)
    svc = cls.__new__(cls)
    svc._stop = threading.Event()
    svc._dbg = lambda *_a, **_k: None
    calls = []

    def _reconcile():
        calls.append(1)
        if len(calls) >= 3:
            svc._stop.set()
        raise RuntimeError('db down')
    svc._reconcile_once = _reconcile
    for k, v in (extra or {}).items():
        setattr(svc, k, v)
    svc._watch_loop()
    return calls


class TestWatchLoops:

    def test_monitor_watch_loop_survives(self, monkeypatch):
        from lib.services.monitoring import service as mod
        assert len(_drive_watch_loop(monkeypatch, mod, mod.MonitorService)) == 3

    def test_events_watch_loop_survives(self, monkeypatch):
        from lib.services.events import service as mod
        assert len(_drive_watch_loop(monkeypatch, mod, mod.EventService)) == 3

    def test_syslog_watch_loop_survives_including_first_read(self, monkeypatch):
        from lib.services.syslog import service as mod
        calls = _drive_watch_loop(monkeypatch, mod, mod.SyslogService,
                                  extra={'_config_signature': _raise})
        assert len(calls) == 3


# ── S2: syslog retention ────────────────────────────────────────────────────────
class TestSyslogRetention:

    def test_prune_once_survives_config_read_failure(self):
        from lib.services.syslog.manager import _SyslogMixin

        class _Store:
            def prune(self, **_k):
                raise AssertionError('must not prune without a config')

        class _Host(_SyslogMixin):
            def __init__(self):
                self._syslog_store = _Store()
                self.logged = []

            def _syslog_cfg(self):
                raise RuntimeError('db down')

            def _dbg(self, message, *_a):
                self.logged.append(message)

        h = _Host()
        h._syslog_prune_once()                    # used to raise
        assert any('retention sweep failed' in m for m in h.logged)

    def _drive(self, svc, stop_attr):
        stop = _ScriptedStop(rounds=4)
        setattr(svc, stop_attr, stop)
        svc.RETENTION_EVERY = 0
        svc._syslog_prune_once = _raise
        svc._retention_loop()
        return stop.waits

    def test_standalone_retention_loop_survives(self):
        from lib.services.syslog.service import SyslogService
        svc = SyslogService.__new__(SyslogService)
        svc._dbg = lambda *_a, **_k: None
        assert len(self._drive(svc, '_stop')) == 4

    def test_embedded_retention_loop_survives(self):
        from lib.services.syslog.embedded import EmbeddedSyslog

        class _Host:
            def _dbg(self, *_a, **_k):
                pass
        svc = EmbeddedSyslog.__new__(EmbeddedSyslog)
        svc._host = _Host()
        assert len(self._drive(svc, '_syslog_retention_stop')) == 4


# ── S2: event worker ──────────────────────────────────────────────────────────
class TestEventWorkerLoop:

    def test_worker_loop_survives_a_raising_tick(self):
        from lib.services.events.manager import _EventsMixin

        class _W(_EventsMixin):
            def __init__(self):
                self.ticks = 0
                self.stop = threading.Event()

            def _dbg(self, *_a, **_k):
                pass

            def _event_worker_tick(self):
                self.ticks += 1
                if self.ticks >= 2:
                    self.stop.set()
                raise RuntimeError('db down (events|enabled read)')

        w = _W()
        w._event_worker_loop(w.stop, poll_secs=0.2)   # used to raise on the first tick
        assert w.ticks == 2


# ── S2: health monitor + scanners ─────────────────────────────────────────────
def _run_loop(obj, poll_getter):
    obj.start(poll_getter=poll_getter)
    obj._thread.join(3)
    assert not obj._thread.is_alive()


class TestHealthLoops:
    """The poll getter reads config; a failed read must keep the last interval."""

    def test_service_health_loop(self):
        from lib.core.health.health import ServiceHealthMonitor
        m = ServiceHealthMonitor(instances_provider=lambda: [], dispatch=lambda *a, **k: None,
                                 config_getter=lambda: {})
        m._stop = _ScriptedStop(rounds=1)
        _run_loop(m, _raise)
        assert m._stop.waits == [30]

    def test_cert_scan_loop(self):
        from lib.core.health.cert_scan import CertExpiryScanner
        s = CertExpiryScanner(targets_provider=lambda: [], dispatch=lambda *a, **k: None,
                              config_getter=lambda: {})
        s.evaluate_once = lambda **_k: None
        s._stop = _ScriptedStop(rounds=2)
        _run_loop(s, _raise)
        assert s._stop.waits == [30, 86400]

    def test_secret_scan_loop(self):
        from lib.core.health.secret_scan import SecretExpiryScanner
        s = SecretExpiryScanner(config_getter=lambda: {}, dispatch=lambda *a, **k: None,
                                rotate_fn=_raise, save_fn=lambda *a: None)
        s.evaluate_once = lambda **_k: None
        s._stop = _ScriptedStop(rounds=2)
        _run_loop(s, _raise)
        assert s._stop.waits == [45, 86400]

    def test_cable_scan_loop(self):
        from lib.core.health.cable_scan import DEFAULT_EVERY, CableDriftScanner
        s = CableDriftScanner(check_provider=lambda: None, state=None,
                              dispatch=lambda *a, **k: None, config_getter=lambda: {},
                              is_leader=lambda: True)
        s.evaluate_once = lambda **_k: None
        s._stop = _ScriptedStop(rounds=2)
        _run_loop(s, _raise)
        assert s._stop.waits == [120, DEFAULT_EVERY]
