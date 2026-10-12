#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/snmp found by the 2026-10-12 audit."""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor

from watchfuls.snmp import Watchful


def _make(checks, **server):
    srv = {'enabled': True, 'host': '10.0.0.1', 'version': '2c', 'community': 'public',
           **server, 'checks': checks}
    mon = create_mock_monitor({'watchfuls.snmp': {'servers': {'s': srv}}})
    with patch('watchfuls.snmp._startup_compile_mibs'):
        return Watchful(mon)


class TestClearedAlertField:
    """A cleared `alert` box is stored as null (or ''): `int(None)` raised inside the check,
    so the check went DOWN on every cycle with a TypeError instead of being read."""

    @pytest.mark.parametrize('alert', [None, ''])
    def test_a_cleared_alert_falls_back_to_the_default(self, alert):
        w = _make({'c': {'enabled': True, 'oid': 'x', 'operator': 'any', 'alert': alert}})
        with patch.object(Watchful, '_snmp_get', return_value=('1', None)):
            row = w.check().list['s.c']
        assert row['status'] is True, row['message']


class TestRetriesZero:
    """`retries: 0` is a legitimate ask (one try, no repeat). `int(v or default)` read the 0
    as blank and silently retried anyway."""

    def test_zero_retries_is_kept(self):
        w = _make({'c': {'enabled': True, 'oid': 'x', 'operator': 'any'}}, retries=0)
        with patch.object(Watchful, '_snmp_get', return_value=('1', None)) as get:
            w.check()
        assert get.call_args.kwargs['retries'] == 0

    def test_blank_retries_uses_the_default(self):
        from watchfuls.snmp.defaults import _SERVER_DEFAULTS
        w = _make({'c': {'enabled': True, 'oid': 'x', 'operator': 'any'}}, retries=None)
        with patch.object(Watchful, '_snmp_get', return_value=('1', None)) as get:
            w.check()
        assert get.call_args.kwargs['retries'] == int(_SERVER_DEFAULTS['retries'])

    def test_cfg_int_contract(self):
        from watchfuls.snmp.defaults import _cfg_int
        assert _cfg_int(0, 3) == 0
        assert _cfg_int('0', 3) == 0
        assert _cfg_int(None, 3) == 3
        assert _cfg_int('  ', 3) == 3
        assert _cfg_int('abc', 3) == 3
        assert _cfg_int('7', 3) == 7
