#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/cpu (W16): `wmic` is gone from Windows 11 24H2.

The Windows reading is PowerShell CIM now, with `wmic` kept only for a host where
PowerShell itself is missing. Samples are recorded answers of both commands.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


def _watchful(items):
    from watchfuls.cpu import Watchful
    mm = create_mock_monitor({'watchfuls.cpu': {'list': items}})
    mm._devices_store = _FakeStore({'h1': {
        'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': 'windows',
        'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'admin'}}}})
    return Watchful(mm)


# `(Get-CimInstance Win32_Processor).LoadPercentage` on a two-socket host.
_CIM_TWO_SOCKETS = "30\r\n50\r\n"
_CIM_ONE = "17\r\n"
_WMIC = "\r\r\nLoadPercentage=42\r\r\n\r\r\n"
# cmd.exe without PowerShell on the PATH (Spanish locale): nothing on stdout.
_NO_PS_ERR = ("\"powershell\" no se reconoce como un comando interno o externo,\r\n"
              "programa o archivo por lotes ejecutable.\r\n")


class TestWindowsCommand:

    def test_the_windows_command_is_cim_not_wmic(self):
        from watchfuls.cpu import _cpu_cmd
        cmd = _cpu_cmd('windows')
        assert cmd.startswith('powershell -NoProfile -NonInteractive -Command ')
        assert 'Get-CimInstance Win32_Processor' in cmd
        assert 'wmic' not in cmd

    def test_the_command_reads_the_same_to_cmd_and_powershell(self):
        """Nothing either shell would expand or split inside the quoted argument."""
        from watchfuls.cpu import _cpu_cmd
        arg = _cpu_cmd('windows').split(' -Command ', 1)[1]
        assert arg.startswith('"') and arg.endswith('"') and arg.count('"') == 2
        for token in ('$', "'", ';', '|', '&', '`', '%'):
            assert token not in arg, token


class TestParseWindows:

    def test_cim_average_over_sockets(self):
        from watchfuls.cpu import Watchful
        assert Watchful._parse_windows(_CIM_TWO_SOCKETS) == 40

    def test_cim_single(self):
        from watchfuls.cpu import Watchful
        assert Watchful._parse_windows(_CIM_ONE) == 17

    def test_legacy_wmic_still_read(self):
        from watchfuls.cpu import Watchful
        assert Watchful._parse_windows(_WMIC) == 42

    def test_null_load_is_unparsable(self):
        from watchfuls.cpu import Watchful
        assert Watchful._parse_windows("\r\n") is None


class TestFallback:

    def test_powershell_answer_is_used_and_wmic_never_runs(self):
        w = _watchful({'c': {'enabled': True, 'alert': 85, 'device_uid': 'h1'}})
        with patch.object(w, 'device_exec', return_value=(_CIM_TWO_SOCKETS, '', 0)) as he:
            items = w.check().list
        assert he.call_count == 1
        assert 'Get-CimInstance' in he.call_args.args[1]
        assert items['c']['status'] is True and items['c']['other_data']['used'] == 40.0

    def test_without_powershell_falls_back_to_wmic(self):
        w = _watchful({'c': {'enabled': True, 'alert': 85, 'device_uid': 'h1'}})
        with patch.object(w, 'device_exec',
                          side_effect=[('', _NO_PS_ERR, 1), (_WMIC, '', 0)]) as he:
            items = w.check().list
        assert he.call_count == 2
        assert he.call_args_list[1].args[1].startswith('wmic ')
        assert items['c']['status'] is True and items['c']['other_data']['used'] == 42.0
