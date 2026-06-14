#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/ram_swap — host-centric RAM/SWAP monitoring.

Memory figures are read via ``host_exec`` (mocked); the per-OS parsers run for
real against canned command output.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, hosts):
        self._h = hosts
    def get(self, uid, **_kw):
        return self._h.get(uid)


def _host(uid='h1', os='linux', kind='remote', maintenance=False):
    return {'uid': uid, 'address': '10.0.0.9', 'kind': kind, 'os': os,
            'maintenance': maintenance, 'profiles': {'ssh': {'ssh_user': 'root'}}}


def _watchful(items, hosts=None):
    from watchfuls.ram_swap import Watchful
    mm = create_mock_monitor({'watchfuls.ram_swap': {'list': items}})
    mm._hosts_store = _FakeStore(hosts or {'h1': _host()})
    return Watchful(mm)


# 8 GB total, 2 GB available → 75% used; 2 GB swap, 1.5 GB free → 25% used.
_MEMINFO = """MemTotal:        8000000 kB
MemFree:          500000 kB
MemAvailable:    2000000 kB
SwapTotal:       2000000 kB
SwapFree:        1500000 kB
"""

_WMIC = "\r\nFreePhysicalMemory=2000000\r\nTotalVisibleMemorySize=8000000\r\n\r\n"

_DARWIN = """8589934592
---SS---
Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free:                          100000.
Pages active:                       1000000.
Pages inactive:                      200000.
Pages wired down:                    500000.
Pages occupied by compressor:         48576.
---SS---
total = 2048.00M  used = 512.00M  free = 1536.00M  (encrypted)
"""


class TestParsers:

    def test_linux(self):
        from watchfuls.ram_swap import Watchful
        ram, swap = Watchful._parse_linux(_MEMINFO)
        assert round(ram, 1) == 75.0
        assert round(swap, 1) == 25.0

    def test_linux_no_swap(self):
        from watchfuls.ram_swap import Watchful
        ram, swap = Watchful._parse_linux("MemTotal: 1000 kB\nMemAvailable: 250 kB\n")
        assert round(ram, 1) == 75.0 and swap == 0.0

    def test_windows(self):
        from watchfuls.ram_swap import Watchful
        ram, swap = Watchful._parse_windows(_WMIC)
        assert round(ram, 1) == 75.0 and swap is None

    def test_darwin(self):
        from watchfuls.ram_swap import Watchful
        ram, swap = Watchful._parse_darwin(_DARWIN)
        # (active+wired+compressor) pages * 4096 / 8GiB
        assert ram is not None and 70 < ram < 80
        assert round(swap, 1) == 25.0     # 512/2048


class TestCheck:

    def test_normal_usage(self):
        w = _watchful({'srv': {'enabled': True, 'label': 'srv',
                               'alert_ram': 90, 'alert_swap': 90, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_MEMINFO, '', 0)):
            items = w.check().list
        assert items['srv_ram']['status'] is True
        assert items['srv_swap']['status'] is True
        assert items['srv_ram']['other_data']['used'] == 75.0
        # Display name for status views (the key is a derived UID).
        assert items['srv_ram']['other_data']['name'] == 'srv - RAM'
        assert items['srv_swap']['other_data']['name'] == 'srv - SWAP'

    def test_high_ram_triggers_alert(self):
        w = _watchful({'srv': {'enabled': True, 'alert_ram': 60, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_MEMINFO, '', 0)):
            items = w.check().list
        assert items['srv_ram']['status'] is False     # 75% >= 60%
        assert 'Excessive' in items['srv_ram']['message']

    def test_windows_reports_ram_only(self):
        w = _watchful({'srv': {'enabled': True, 'alert_ram': 90, 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='windows')})
        with patch.object(w, 'host_exec', return_value=(_WMIC, '', 0)) as he:
            items = w.check().list
        assert 'wmic' in he.call_args.args[1]
        assert 'srv_ram' in items and 'srv_swap' not in items

    def test_unsupported_os(self):
        w = _watchful({'srv': {'enabled': True, 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='other')})
        with patch.object(w, 'host_exec') as he:
            items = w.check().list
        he.assert_not_called()
        assert items['srv_ram']['status'] is False
        assert 'unsupported' in items['srv_ram']['message'].lower()

    def test_disabled_item_skipped(self):
        w = _watchful({'srv': {'enabled': False, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()

    def test_maintenance_host_skipped(self):
        w = _watchful({'srv': {'enabled': True, 'host_uid': 'h1'}},
                      hosts={'h1': _host(maintenance=True)})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()

    def test_command_failure_is_error(self):
        w = _watchful({'srv': {'enabled': True, 'label': 'srv', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('', 'refused', 255)):
            items = w.check().list
        assert items['srv']['status'] is False and 'Error' in items['srv']['message']

    def test_invalid_threshold_uses_default(self):
        from watchfuls.ram_swap import Watchful
        assert Watchful._alert('abc', 60) == 60
        assert Watchful._alert(150, 60) == 60
        assert Watchful._alert('80', 60) == 80
