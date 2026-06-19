#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/cpu — host-centric CPU usage monitoring.

CPU is sampled via ``host_exec`` (mocked here); the per-OS parsers run for real
against canned command output.
"""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor


@pytest.fixture(autouse=True)
def _no_sleep():
    """Linux/FreeBSD CPU now waits the interval in Python between two samples;
    skip the real sleep so the suite stays fast."""
    with patch('watchfuls.cpu.time.sleep'):
        yield


class _FakeStore:
    def __init__(self, hosts):
        self._h = hosts
    def get(self, uid, **_kw):
        return self._h.get(uid)


def _host(uid='h1', os='linux', kind='remote', maintenance=False):
    return {'uid': uid, 'address': '10.0.0.9', 'kind': kind, 'os': os,
            'maintenance': maintenance, 'profiles': {'ssh': {'ssh_user': 'root'}}}


def _watchful(items, hosts=None):
    from watchfuls.cpu import Watchful
    mm = create_mock_monitor({'watchfuls.cpu': {'list': items}})
    mm._hosts_store = _FakeStore(hosts or {'h1': _host()})
    return Watchful(mm)


# /proc/stat: total +1000, idle (idle+iowait) +250 → 75% busy.
_PROC_STAT = ("cpu  1000 0 0 8000 1000 0 0 0 0 0\n"
              "cpu  1750 0 0 8250 1000 0 0 0 0 0\n")
_WMIC = "\r\nLoadPercentage=42\r\n\r\n"
_DARWIN = ("Processes: 400 total\n"
           "CPU usage: 5.00% user, 3.00% sys, 92.00% idle\n"
           "CPU usage: 60.00% user, 15.00% sys, 25.00% idle\n")
# kern.cp_time (user nice sys intr idle): total +1000, idle (last) +250 → 75% busy.
_CP_TIME = "1000 0 0 0 8000\n1750 0 0 0 8250\n"


class TestParsers:

    def test_proc_stat(self):
        from watchfuls.cpu import Watchful
        assert round(Watchful._parse_proc_stat(_PROC_STAT), 1) == 75.0

    def test_cp_time(self):
        from watchfuls.cpu import Watchful
        assert round(Watchful._parse_cp_time(_CP_TIME), 1) == 75.0

    def test_windows(self):
        from watchfuls.cpu import Watchful
        assert Watchful._parse_windows(_WMIC) == 42

    def test_darwin_uses_last_sample(self):
        from watchfuls.cpu import Watchful
        assert round(Watchful._parse_darwin(_DARWIN), 1) == 75.0   # 100 - 25 idle

    def test_single_sample_is_none(self):
        from watchfuls.cpu import Watchful
        assert Watchful._parse_proc_stat("cpu 1 0 0 1 0\n") is None

    def test_commands_are_allowlist_friendly(self):
        """Each per-OS command is a single binary with no shell chaining, so it
        fits a strict SSH command allowlist (docs/ssh-hardening.md)."""
        from watchfuls.cpu import _cpu_cmd
        for os_ in ('linux', 'freebsd', 'darwin', 'windows'):
            cmd = _cpu_cmd(os_)
            for token in (';', '|', '&&', '$(', '`', ' for '):
                assert token not in cmd, f'{os_}: {cmd!r} contains {token!r}'


class TestCheck:

    def test_below_threshold_ok(self):
        w = _watchful({'c': {'enabled': True, 'label': 'srv', 'alert': 85, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_PROC_STAT, '', 0)):
            items = w.check().list
        assert items['c']['status'] is True
        assert items['c']['other_data']['used'] == 75.0

    def test_above_threshold_alert(self):
        w = _watchful({'c': {'enabled': True, 'alert': 60, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_PROC_STAT, '', 0)):
            items = w.check().list
        assert items['c']['status'] is False        # 75% >= 60%
        assert 'Excessive' in items['c']['message']

    def test_windows_host_uses_wmic(self):
        w = _watchful({'c': {'enabled': True, 'alert': 85, 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='windows')})
        with patch.object(w, 'host_exec', return_value=(_WMIC, '', 0)) as he:
            items = w.check().list
        assert 'wmic' in he.call_args.args[1]
        assert items['c']['status'] is True and items['c']['other_data']['used'] == 42.0

    def test_disabled_item_skipped(self):
        w = _watchful({'c': {'enabled': False, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()

    def test_maintenance_host_skipped(self):
        w = _watchful({'c': {'enabled': True, 'host_uid': 'h1'}},
                      hosts={'h1': _host(maintenance=True)})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()

    def test_command_failure_is_error(self):
        w = _watchful({'c': {'enabled': True, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('', 'refused', 255)):
            items = w.check().list
        assert items['c']['status'] is False and 'Error' in items['c']['message']

    def test_module_disabled(self):
        from watchfuls.cpu import Watchful
        mm = create_mock_monitor({'watchfuls.cpu': {'enabled': False,
                                  'list': {'c': {'enabled': True, 'host_uid': 'h1'}}}})
        mm._hosts_store = _FakeStore({'h1': _host()})
        w = Watchful(mm)
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()


class TestSchema:

    def test_host_centric(self):
        from watchfuls.cpu import Watchful
        sch = Watchful.ITEM_SCHEMA
        assert sch['__host_profile__']['key'] == 'ssh'
        assert 'alert' in sch['list'] and 'label' in sch['list']
