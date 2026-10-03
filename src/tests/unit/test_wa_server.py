#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the web server bind policy (WebAdmin.run / _bind_web_servers).

Binding is fail-soft per interface but fail-hard overall: partial failures keep
serving on the reachable addresses, a total failure aborts the process instead
of faking a started server.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_server.py`` lives in ``tests/integration/test_wa_server.py``."""

import sys

import pytest

from lib.system.windows import parse_excluded_ranges, port_excluded

# `WebAdmin` se importa dentro del único test que lo usa (y solo por una constante de clase):
# a nivel de módulo arrastraría Flask y tumbaría la colección entera en una instalación sin
# panel web, llevándose por delante los dos tests puros de este fichero.

# Sample `netsh interface ipv4 show excludedportrange protocol=tcp` output
# (Spanish locale, with headers, dashes and a managed-exclusion '*' marker).
_NETSH_SAMPLE = """
Protocolo tcp Intervalos de exclusión de puertos

Puerto de inicio    Puerto final
----------          --------
      5357        5357
      8054        8153
      8846        8945
     50000       50059     *

* - Exclusiones de puertos administrados.
"""

# An address in TEST-NET-3 (RFC 5737) — guaranteed not assigned to this host, so
# binding to it raises OSError (EADDRNOTAVAIL) on every platform.  More reliable
# than an in-use port, which SO_REUSEADDR may let us re-bind on Windows.
_UNBINDABLE = '203.0.113.250'


# ── Windows reserved-port-range diagnostics ──────────────────────────────────

def test_parse_excluded_ranges_reads_data_rows_only():
    """The parser keeps the integer pairs and ignores headers/dashes/'*'."""
    ranges = parse_excluded_ranges(_NETSH_SAMPLE)
    assert ranges == [(5357, 5357), (8054, 8153), (8846, 8945), (50000, 50059)]


def test_port_excluded_matches_range():
    ranges = parse_excluded_ranges(_NETSH_SAMPLE)
    assert port_excluded(8080, ranges) == (8054, 8153)   # the classic 10013 case
    assert port_excluded(18080, ranges) is None          # outside every range




@pytest.mark.skipif(sys.platform != 'win32', reason='Windows reserved ranges')
def test_default_port_windows_reserved_state_is_visible():
    """Informative (non-fatal): surface whether the default web port currently
    falls in a live Windows reserved range.  These winnat/Hyper-V reservations
    are dynamic — when the default (8080) lands in one, binding fails and run()
    aborts with a hint.  Skip (don't fail) since it's an environmental state, not
    a code defect — the diagnostic message is what matters."""
    try:                    # arrastra Flask: aquí dentro, no a nivel de módulo (tumbaría la
        from lib.web_admin import WebAdmin          # colección y con ella los tests puros)
    except ImportError:
        pytest.skip('Flask is not installed')
    rng = port_excluded(WebAdmin.DEFAULT_PORT)
    if rng:
        pytest.skip(f"default port {WebAdmin.DEFAULT_PORT} is currently reserved by "
                    f"Windows {rng[0]}–{rng[1]}; bind would fail and run() aborts "
                    f"with a hint (free it: net stop winnat && net start winnat)")


# ── Clean exit: SIGTERM and the background services ───────────────────────────────────────
# Only KeyboardInterrupt was handled: on `docker stop` (SIGTERM) the embedded syslog writer's
# queue was lost, no lease was released and this instance's rows stayed "running".

def _server_mixin():
    try:                    # the mixins package imports Flask
        from lib.web_admin.mixins.server import _ServerMixin
    except ImportError:
        pytest.skip('Flask is not installed')
    return _ServerMixin


class _Svc:
    def __init__(self, log, name):
        self._log, self._name = log, name

    def on_shutdown(self):
        self._log.append((self._name, 'on_shutdown'))

    def stop_heartbeat(self):
        self._log.append((self._name, 'stop_heartbeat'))


def test_shutdown_services_stops_every_service_then_the_scanners():
    mixin = _server_mixin()
    log = []

    class _Host(mixin):
        _embedded_services = {'syslog': _Svc(log, 'syslog'), 'monitoring': _Svc(log, 'monitoring')}

        def stop_background(self):
            log.append(('panel', 'stop_background'))

    h = _Host()
    h.shutdown_services()
    h.shutdown_services()                     # idempotent
    assert log == [('syslog', 'on_shutdown'), ('syslog', 'stop_heartbeat'),
                   ('monitoring', 'on_shutdown'), ('monitoring', 'stop_heartbeat'),
                   ('panel', 'stop_background')]


def test_a_failing_service_does_not_stop_the_others():
    mixin = _server_mixin()
    log = []

    class _Bad:
        def on_shutdown(self):
            raise RuntimeError('boom')

        def stop_heartbeat(self):
            log.append('bad-hb')

    class _Host(mixin):
        _embedded_services = {'a': _Bad(), 'b': _Svc(log, 'b')}

        def stop_background(self):
            log.append('bg')

    _Host().shutdown_services()
    assert log == ['bad-hb', ('b', 'on_shutdown'), ('b', 'stop_heartbeat'), 'bg']


def test_sigterm_is_routed_to_the_stop_request_and_restored():
    import signal
    import threading
    mixin = _server_mixin()
    before = signal.getsignal(signal.SIGTERM)
    ev = threading.Event()
    prev = mixin._install_stop_signals(ev)
    try:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler) and handler is not before, 'SIGTERM is not handled'
        handler(signal.SIGTERM, None)
        assert ev.is_set()
    finally:
        mixin._restore_signals(prev)
    assert signal.getsignal(signal.SIGTERM) == before


def test_no_signal_handler_off_the_main_thread():
    import threading
    mixin = _server_mixin()
    out = {}
    t = threading.Thread(target=lambda: out.setdefault('p', mixin._install_stop_signals(
        threading.Event())))
    t.start()
    t.join()
    assert out['p'] == {}


def test_the_syslog_listener_is_stopped_and_drained_on_exit():
    from lib.services.syslog.embedded import EmbeddedSyslog
    calls = []
    svc = EmbeddedSyslog.__new__(EmbeddedSyslog)
    svc.stop = lambda: calls.append('stop')
    svc.on_shutdown()
    assert calls == ['stop']
