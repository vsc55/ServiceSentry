#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the web server bind policy (WebAdmin.run / _bind_web_servers).

Binding is fail-soft per interface but fail-hard overall: partial failures keep
serving on the reachable addresses, a total failure aborts the process instead
of faking a started server.
"""

import os
import socket
import sys

import pytest

from lib.web_admin import WebAdmin
from lib.system.windows import parse_excluded_ranges, port_excluded

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


def _free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_bind_all_ok(admin):
    """A single reachable interface binds with no failures."""
    port = _free_port()
    servers, failed = WebAdmin._bind_web_servers(['127.0.0.1'], port, admin.app)
    try:
        assert [h for h, _ in servers] == ['127.0.0.1']
        assert failed == []
    finally:
        for _h, srv in servers:
            srv.server_close()


def test_bind_skips_unbindable_and_keeps_good(admin):
    """Partial failure: the bad interface is reported, the good one still binds."""
    port = _free_port()
    servers, failed = WebAdmin._bind_web_servers(
        ['127.0.0.1', _UNBINDABLE], port, admin.app)
    try:
        assert [h for h, _ in servers] == ['127.0.0.1']
        assert [h for h, _ in failed] == [_UNBINDABLE]
        assert isinstance(failed[0][1], OSError)
    finally:
        for _h, srv in servers:
            srv.server_close()


def test_run_aborts_when_no_interface_binds(admin, monkeypatch):
    """Total failure: run() hard-exits non-zero instead of pretending to serve.

    The abort uses ``os._exit`` (so a hung non-daemon thread can't keep the
    process alive); patch it to a catchable exception to assert the exit code.
    """
    def _fake_exit(code):
        raise SystemExit(code)
    monkeypatch.setattr(os, '_exit', _fake_exit)

    with pytest.raises(SystemExit) as exc:
        admin.run(host=_UNBINDABLE, port=_free_port())
    assert exc.value.code == 1


# ── Windows reserved-port-range diagnostics ──────────────────────────────────

def test_parse_excluded_ranges_reads_data_rows_only():
    """The parser keeps the integer pairs and ignores headers/dashes/'*'."""
    ranges = parse_excluded_ranges(_NETSH_SAMPLE)
    assert ranges == [(5357, 5357), (8054, 8153), (8846, 8945), (50000, 50059)]


def test_port_excluded_matches_range():
    ranges = parse_excluded_ranges(_NETSH_SAMPLE)
    assert port_excluded(8080, ranges) == (8054, 8153)   # the classic 10013 case
    assert port_excluded(18080, ranges) is None          # outside every range


def test_run_abort_hints_windows_reserved_range(admin, monkeypatch, capsys):
    """A total bind failure on a reserved port explains the Windows cause."""
    monkeypatch.setattr('lib.system.windows.port_excluded',
                        lambda port, ranges=None: (8054, 8153))
    monkeypatch.setattr(os, '_exit', lambda code: (_ for _ in ()).throw(SystemExit(code)))
    with pytest.raises(SystemExit):
        admin.run(host=_UNBINDABLE, port=_free_port())
    err = capsys.readouterr().err
    # Language-neutral tokens (present in both en_EN and es_ES via i18n).
    assert 'Windows' in err and 'winnat' in err
    assert 'config.json' in err   # the user can force the port there


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows reserved ranges')
def test_default_port_windows_reserved_state_is_visible():
    """Informative (non-fatal): surface whether the default web port currently
    falls in a live Windows reserved range.  These winnat/Hyper-V reservations
    are dynamic — when the default (8080) lands in one, binding fails and run()
    aborts with a hint.  Skip (don't fail) since it's an environmental state, not
    a code defect — the diagnostic message is what matters."""
    rng = port_excluded(WebAdmin.DEFAULT_PORT)
    if rng:
        pytest.skip(f"default port {WebAdmin.DEFAULT_PORT} is currently reserved by "
                    f"Windows {rng[0]}–{rng[1]}; bind would fail and run() aborts "
                    f"with a hint (free it: net stop winnat && net start winnat)")
