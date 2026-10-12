#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/filesystemusage (W16): `wmic` is gone from Windows 11 24H2.

The Windows reading is PowerShell CIM (`Format-List` of Win32_LogicalDisk), with `wmic`
kept only for a host where PowerShell itself is missing. Samples are recorded answers.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


_WIN_DEVICE = {'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': 'windows',
               'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'admin'}}}


def _watchful(items):
    from watchfuls.filesystemusage import Watchful
    mm = create_mock_monitor({'watchfuls.filesystemusage': {'list': items}})
    mm._devices_store = _FakeStore({'h1': _WIN_DEVICE})
    return Watchful(mm)


# PowerShell Format-List of Win32_LogicalDisk: C: 75% used, an empty DVD drive (blank
# Size/FreeSpace), D: 90% used.
_CIM = ("\r\n\r\nDeviceID  : C:\r\nFreeSpace : 25000000\r\nSize      : 100000000\r\n\r\n"
        "DeviceID  : E:\r\nFreeSpace : \r\nSize      : \r\n\r\n"
        "DeviceID  : D:\r\nFreeSpace : 10000000\r\nSize      : 100000000\r\n\r\n\r\n\r\n")
_WMIC = ("\r\r\nDeviceID=C:\r\r\nFreeSpace=25000000\r\r\nSize=100000000\r\r\n\r\r\n"
         "DeviceID=D:\r\r\nFreeSpace=10000000\r\r\nSize=100000000\r\r\n\r\r\n")
_NO_PS_ERR = "'powershell' is not recognized as an internal or external command,\r\n"


class TestWindowsCommand:

    def test_the_windows_command_is_cim_not_wmic(self):
        from watchfuls.filesystemusage import _DF_CMDS
        cmd = _DF_CMDS['windows']
        assert cmd.startswith('powershell -NoProfile -NonInteractive -Command ')
        assert 'Get-CimInstance Win32_LogicalDisk' in cmd
        assert 'wmic' not in cmd

    def test_the_command_is_allowlist_friendly_in_both_shells(self):
        """No pipe or chaining (docs/caso-ssh-hardening.md), and nothing cmd.exe or
        PowerShell would expand inside the single quoted argument."""
        from watchfuls.filesystemusage import _DF_CMDS
        arg = _DF_CMDS['windows'].split(' -Command ', 1)[1]
        assert arg.startswith('"') and arg.endswith('"') and arg.count('"') == 2
        for token in ('$', "'", ';', '|', '&', '`', '%'):
            assert token not in arg, token


class TestParseCim:

    def test_used_percent_per_device(self):
        from watchfuls.filesystemusage import Watchful
        assert Watchful._parse_wmic(_CIM, 'C:') == 75
        assert Watchful._parse_wmic(_CIM, 'D:') == 90
        assert Watchful._parse_wmic(_CIM, 'd:\\') == 90

    def test_an_empty_drive_is_not_a_reading(self):
        from watchfuls.filesystemusage import Watchful
        assert Watchful._parse_wmic(_CIM, 'E:') is None

    def test_discover_reads_cim(self):
        from watchfuls.filesystemusage import Watchful
        found = {d['name']: d['status'] for d in Watchful._discover_parse('windows', _CIM)}
        assert found == {'C:': '75%', 'D:': '90%', 'E:': '?'}

    def test_legacy_wmic_still_read(self):
        from watchfuls.filesystemusage import Watchful
        assert Watchful._parse_wmic(_WMIC, 'C:') == 75


class TestFallback:

    def test_powershell_answer_is_used_and_wmic_never_runs(self):
        w = _watchful({'c': {'enabled': True, 'partition': 'C:', 'alert': 85, 'device_uid': 'h1'}})
        with patch.object(w, 'device_exec', return_value=(_CIM, '', 0)) as he:
            items = w.check().list
        assert he.call_count == 1
        assert items['c']['status'] is True and items['c']['other_data']['used'] == 75

    def test_without_powershell_falls_back_to_wmic(self):
        w = _watchful({'c': {'enabled': True, 'partition': 'D:', 'alert': 85, 'device_uid': 'h1'}})
        with patch.object(w, 'device_exec',
                          side_effect=[('', _NO_PS_ERR, 9009), (_WMIC, '', 0)]) as he:
            items = w.check().list
        assert he.call_count == 2
        assert he.call_args_list[1].args[1].startswith('wmic ')
        assert items['c']['status'] is False and items['c']['other_data']['used'] == 90

    def test_remote_discover_falls_back_to_wmic(self):
        from watchfuls.filesystemusage import Watchful
        device = {'kind': 'remote', 'os': 'windows', 'address': '10.0.0.9', 'ssh': {}}
        with patch('lib.core.devices.runner.is_remote', return_value=True), \
             patch('lib.core.devices.runner.run',
                   side_effect=[('', _NO_PS_ERR, 1), (_WMIC, '', 0)]) as run:
            found = Watchful.discover({'__device__': device})
        assert run.call_count == 2
        assert [d['name'] for d in found] == ['C:', 'D:']
