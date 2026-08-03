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
    rng = port_excluded(WebAdmin.DEFAULT_PORT)
    if rng:
        pytest.skip(f"default port {WebAdmin.DEFAULT_PORT} is currently reserved by "
                    f"Windows {rng[0]}–{rng[1]}; bind would fail and run() aborts "
                    f"with a hint (free it: net stop winnat && net start winnat)")
