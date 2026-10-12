#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/ram_swap (W16): `wmic` is gone from Windows 11 24H2.

The Windows reading is PowerShell CIM (`Format-List` of Win32_OperatingSystem), with
`wmic` kept only for a host where PowerShell itself is missing.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


def _watchful(items):
    from watchfuls.ram_swap import Watchful
    mm = create_mock_monitor({'watchfuls.ram_swap': {'list': items}})
    mm._devices_store = _FakeStore({'h1': {
        'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': 'windows',
        'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'admin'}}}})
    return Watchful(mm)


# 8 GB visible, 2 GB free → 75% used.
_CIM = "\r\n\r\nFreePhysicalMemory     : 2000000\r\nTotalVisibleMemorySize : 8000000\r\n\r\n\r\n\r\n"
_WMIC = "\r\r\nFreePhysicalMemory=2000000\r\r\nTotalVisibleMemorySize=8000000\r\r\n\r\r\n"


class TestWindows:

    def test_the_windows_command_is_cim_not_wmic(self):
        from watchfuls.ram_swap import _MEM_CMDS
        (cmd,) = _MEM_CMDS['windows']
        assert 'Get-CimInstance Win32_OperatingSystem' in cmd and 'wmic' not in cmd
        arg = cmd.split(' -Command ', 1)[1]
        assert arg.startswith('"') and arg.endswith('"') and arg.count('"') == 2
        for token in ('$', "'", ';', '|', '&', '`', '%'):
            assert token not in arg, token

    def test_cim_format_list_is_read(self):
        from watchfuls.ram_swap import Watchful
        ram, swap = Watchful._parse_windows(_CIM)
        assert ram == 75.0 and swap is None

    def test_without_powershell_falls_back_to_wmic(self):
        w = _watchful({'srv': {'enabled': True, 'alert_ram': 90, 'device_uid': 'h1'}})
        with patch.object(w, 'device_exec',
                          side_effect=[('', 'powershell: not found', 1), (_WMIC, '', 0)]) as he:
            items = w.check().list
        assert he.call_count == 2
        assert he.call_args_list[1].args[1].startswith('wmic ')
        assert items['srv_ram']['other_data']['used'] == 75.0
