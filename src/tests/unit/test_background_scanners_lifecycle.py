#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The panel's own background scanners: what they remember, and whether they can stop.

Two families of fault, found together because they live in the same four classes:

* **They forgot what they had said.** The certificate and secret scanners alert once per
  severity, and that memory was a dict in the scanner. Every web restart — and every time the
  lease moved to another replica — started from an empty dict and announced every certificate
  inside the window again. The lease itself lasted an hour against a daily scan, so it moved
  every day. Now the memory is a row in ``health_alerts`` and the lease outlives three scans.

* **They could not be restarted.** ``stop()`` left the thread reference set, so ``start()``
  was a no-op for ever after; the cable scanner cleared the SAME Event on restart, reviving the
  old loop beside the new one; and ``WebAdmin.stop_background`` kept the references the
  ``_start_*`` guards test, and never gave the leases back.
"""

import threading
import time

import pytest

from lib.core.health.alert_state import AlertState
from lib.core.health.cable_scan import CableDriftScanner
from lib.core.health.cert_scan import CertExpiryScanner
from lib.core.health.health import ServiceHealthMonitor
from lib.core.health.secret_scan import SecretExpiryScanner
from lib.db import get_connector


def _db():
    return get_connector(None, default_sqlite_path=':memory:')


def _cert(db, emitted, days=5):
    return CertExpiryScanner(
        targets_provider=lambda: [{'key': 'a', 'label': 'A'}],
        dispatch=lambda kind, **f: emitted.append(f['item']),
        config_getter=lambda: {'notify_expiry': True, 'warn_days': 21},
        days_fn=lambda _t: days, text_fn=lambda k, *a: k,
        state=AlertState(db, scope='cert') if db is not None else None)


def _secret(db, emitted):
    expires = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 5 * 86400))
    return SecretExpiryScanner(
        config_getter=lambda: {'enabled': True, 'secret_notify_expiry': True,
                               'secret_expires_at': expires},
        dispatch=lambda kind, **f: emitted.append(kind),
        rotate_fn=lambda: {}, save_fn=lambda *a: None, text_fn=lambda k, *a: k,
        state=AlertState(db, scope='secret'))


class TestWhatWasSaidSurvivesTheProcess:

    def test_a_new_cert_scanner_on_the_same_database_does_not_alert_again(self):
        db, emitted = _db(), []
        _cert(db, emitted).evaluate_once(now=time.time())
        _cert(db, emitted).evaluate_once(now=time.time())      # the restarted process
        assert emitted == ['A'], 'every restart announced the certificate again'

    def test_a_renewed_cert_re_arms_across_processes(self):
        db, emitted = _db(), []
        _cert(db, emitted).evaluate_once(now=time.time())
        _cert(db, emitted, days=300).evaluate_once(now=time.time())   # renewed
        _cert(db, emitted).evaluate_once(now=time.time())             # expiring again
        assert emitted == ['A', 'A']

    def test_escalation_is_still_announced(self):
        db, emitted = _db(), []
        _cert(db, emitted).evaluate_once(now=time.time())
        _cert(db, emitted, days=-1).evaluate_once(now=time.time())
        assert emitted == ['A', 'A']

    def test_a_new_secret_scanner_on_the_same_database_does_not_alert_again(self):
        db, emitted = _db(), []
        _secret(db, emitted).evaluate_once(now=time.time())
        _secret(db, emitted).evaluate_once(now=time.time())
        assert emitted == ['secret_expiring']

    def test_without_a_database_it_is_the_old_in_memory_behaviour(self):
        emitted = []
        sc = _cert(None, emitted)
        sc.evaluate_once(now=time.time())
        sc.evaluate_once(now=time.time())
        assert emitted == ['A']


def _scanners():
    noop = lambda *a, **k: None  # noqa: E731
    return [
        CertExpiryScanner(targets_provider=list, dispatch=noop, config_getter=dict),
        SecretExpiryScanner(config_getter=dict, dispatch=noop, rotate_fn=dict, save_fn=noop),
        ServiceHealthMonitor(instances_provider=list, dispatch=noop, config_getter=dict),
        CableDriftScanner(check_provider=dict, state=None, dispatch=noop, config_getter=dict,
                          is_leader=lambda: True),
    ]


def _loops(name):
    return [t for t in threading.enumerate() if t.name == name and t.is_alive()]


class TestAScannerCanBeStoppedAndStartedAgain:

    @pytest.mark.parametrize('idx,name', [(0, 'cert-scan'), (1, 'secret-scan'),
                                          (2, 'svc-health'), (3, 'cable-scan')])
    def test_start_after_stop_runs_exactly_one_loop(self, idx, name):
        sc = _scanners()[idx]
        before = len(_loops(name))
        sc.start(poll_getter=lambda: 3600)
        sc.stop()
        assert len(_loops(name)) == before, 'stop() did not end the loop'
        sc.start(poll_getter=lambda: 3600)
        try:
            assert sc._thread is not None and sc._thread.is_alive(), \
                'start() after stop() was a no-op'
            assert len(_loops(name)) == before + 1, 'the old loop came back beside the new one'
        finally:
            sc.stop()
        assert len(_loops(name)) == before


# ── the host side (WebAdmin mixin): needs Flask only to import the mixins package ─────────

class _Leases:
    def __init__(self):
        self.ttls, self.released = {}, []

    def try_acquire(self, key, inst, host='', ttl=0):
        self.ttls[key] = ttl
        return True

    def release(self, key, inst):
        self.released.append(key)


def _host():
    try:                    # the mixins package imports Flask
        from lib.web_admin.mixins.scanners import _ScannersMixin
    except ImportError:
        pytest.skip('Flask is not installed')

    class _Host(_ScannersMixin):
        _CONFIG_FILE = None

        def __init__(self):
            self._service_leader_store = _Leases()
            self._service_instances_store = type('I', (), {'list_instances': lambda s: []})()
            self._db_connector = _db()
            self._modules_facade = type('F', (), {'read': lambda s: {}})()

        def _config_section(self, name):
            return {'scan_every_secs': 86400} if name == 'certs' else {}

        def _dbg(self, *a, **k):
            pass

        def _notify_text(self, k, *a):
            return k

    return _Host()


class TestTheHostLetsGo:

    def test_the_expiry_leases_outlive_three_scans(self):
        h = _host()
        h._start_cert_scanner()
        h._start_secret_scanner()
        try:
            h._cert_scanner._is_leader()
            h._secret_scanner._is_leader()
            assert h._service_leader_store.ttls['cert_scan'] >= 3 * 86400
            assert h._service_leader_store.ttls['secret_scan'] >= 3 * 86400
        finally:
            h.stop_background()

    def test_the_expiry_scanners_remember_in_the_database(self):
        h = _host()
        h._start_cert_scanner()
        try:
            assert h._cert_scanner._alerted._db is h._db_connector
        finally:
            h.stop_background()

    def test_stop_background_releases_the_leases_and_allows_a_restart(self):
        h = _host()
        h._start_cert_scanner()
        h._start_service_health_monitor()
        h.stop_background()
        assert sorted(h._service_leader_store.released) == ['cert_scan', 'svc_health']
        assert h._cert_scanner is None and h._service_health is None
        h._start_cert_scanner()
        try:
            assert h._cert_scanner is not None and h._cert_scanner._thread.is_alive()
        finally:
            h.stop_background()
