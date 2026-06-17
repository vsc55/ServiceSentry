#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/raid — host-centric RAID (mdstat) monitoring.

Each check binds to a host (``host_uid``); ``/proc/mdstat`` is read on that host
via ``host_exec`` (local or over SSH) and parsed by ``RaidMdstat.parse_lines``.
``host_exec`` is mocked here so no real command/SSH runs; the parser runs for
real against canned mdstat text.
"""

from unittest.mock import patch

from lib.linux.raid_mdstat import RaidMdstat
from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, hosts):
        self._h = hosts
    def get(self, uid, **_kw):
        return self._h.get(uid)


def _host(uid='h1', os='linux', kind='remote', maintenance=False):
    return {'uid': uid, 'address': '10.0.0.9', 'kind': kind, 'os': os,
            'maintenance': maintenance,
            'profiles': {'ssh': {'ssh_user': 'root'}}}


def _watchful(items, hosts=None):
    from watchfuls.raid import Watchful
    mm = create_mock_monitor({'watchfuls.raid': {'list': items}})
    mm._hosts_store = _FakeStore(hosts or {'h1': _host()})
    return Watchful(mm)


_MDSTAT_OK = """Personalities : [raid1]
md0 : active raid1 sda1[0] sdb1[1]
      976630336 blocks super 1.2 [2/2] [UU]

unused devices: <none>
"""

_MDSTAT_DEGRADED = """Personalities : [raid1]
md0 : active raid1 sda1[0]
      976630336 blocks super 1.2 [2/1] [U_]

unused devices: <none>
"""

_MDSTAT_RECOVERY = """Personalities : [raid1]
md0 : active raid1 sda1[0] sdb1[2]
      976630336 blocks super 1.2 [2/1] [U_]
      [==>..................]  recovery = 12.6% (123/456) finish=127.5min speed=33440K/sec

unused devices: <none>
"""

_MDSTAT_EMPTY = "Personalities : [raid1]\nunused devices: <none>\n"


class TestParseLines:
    """The reusable parser used by the module (and read_status)."""

    def test_ok(self):
        md = RaidMdstat.parse_lines(_MDSTAT_OK)
        assert md['md0']['update'] == RaidMdstat.UpdateStatus.ok

    def test_degraded(self):
        md = RaidMdstat.parse_lines(_MDSTAT_DEGRADED)
        assert md['md0']['update'] == RaidMdstat.UpdateStatus.error

    def test_recovery(self):
        md = RaidMdstat.parse_lines(_MDSTAT_RECOVERY)
        assert md['md0']['update'] == RaidMdstat.UpdateStatus.recovery
        assert md['md0']['recovery']['percent'] == 12.6

    def test_empty(self):
        assert RaidMdstat.parse_lines(_MDSTAT_EMPTY) == {}

    def test_accepts_list_of_lines(self):
        md = RaidMdstat.parse_lines(_MDSTAT_OK.splitlines())
        assert 'md0' in md


class TestRaidDefaults:

    def test_module_defaults(self):
        from watchfuls.raid import Watchful
        md = Watchful._MODULE_DEFAULTS
        assert md['threads'] == 5 and md['timeout'] == 30
        assert md['mdstat_path'] == '/proc/mdstat'

    def test_schema_is_host_centric(self):
        from watchfuls.raid import Watchful
        sch = Watchful.ITEM_SCHEMA
        assert '__host_profile__' in sch and sch['__host_profile__']['key'] == 'ssh'
        assert 'local' not in sch['__module__']        # dropped: use a local host
        assert 'host' not in sch['list']               # no inline SSH on the check


class TestRaidCheck:

    def test_raid_ok(self):
        w = _watchful({'1': {'enabled': True, 'label': 'NAS', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_MDSTAT_OK, '', 0)):
            items = w.check().list
        assert items['1_md0']['status'] is True
        assert 'good status' in items['1_md0']['message']

    def test_raid_degraded(self):
        w = _watchful({'1': {'enabled': True, 'label': 'NAS', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_MDSTAT_DEGRADED, '', 0)):
            items = w.check().list
        assert items['1_md0']['status'] is False
        assert 'degraded' in items['1_md0']['message']

    def test_raid_recovery(self):
        w = _watchful({'1': {'enabled': True, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_MDSTAT_RECOVERY, '', 0)):
            items = w.check().list
        assert items['1_md0']['status'] is False
        assert 'recovery' in items['1_md0']['message']
        assert items['1_md0']['other_data']['percent'] == 12.6

    def test_no_raids(self):
        w = _watchful({'1': {'enabled': True, 'label': 'NAS', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_MDSTAT_EMPTY, '', 0)):
            items = w.check().list
        assert items['1']['status'] is True
        assert 'No RAID' in items['1']['message']

    def test_disabled_item_skipped(self):
        w = _watchful({'1': {'enabled': False, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec') as he:
            result = w.check()
        he.assert_not_called()
        assert len(result.items()) == 0

    def test_non_linux_host_reports_unsupported(self):
        w = _watchful({'1': {'enabled': True, 'label': 'WinBox', 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='windows')})
        with patch.object(w, 'host_exec') as he:
            items = w.check().list
        he.assert_not_called()                     # no mdstat attempt off-Linux
        assert items['1']['status'] is False
        assert 'Linux' in items['1']['message']

    def test_maintenance_host_skipped(self):
        w = _watchful({'1': {'enabled': True, 'host_uid': 'h1'}},
                      hosts={'h1': _host(maintenance=True)})
        with patch.object(w, 'host_exec') as he:
            result = w.check()
        he.assert_not_called()
        assert len(result.items()) == 0

    def test_command_failure_is_error(self):
        w = _watchful({'1': {'enabled': True, 'label': 'NAS', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('', 'No such file', 1)):
            items = w.check().list
        assert items['1']['status'] is False
        assert 'Error' in items['1']['message']

    def test_module_disabled(self):
        from watchfuls.raid import Watchful
        mm = create_mock_monitor({'watchfuls.raid': {'enabled': False,
                                                      'list': {'1': {'enabled': True, 'host_uid': 'h1'}}}})
        mm._hosts_store = _FakeStore({'h1': _host()})
        w = Watchful(mm)
        with patch.object(w, 'host_exec') as he:
            result = w.check()
        he.assert_not_called()
        assert len(result.items()) == 0


class TestRaidLabel:

    def test_label_from_item(self):
        w = _watchful({'1': {'label': 'MyServer', 'host_uid': 'h1'}})
        assert w._label('1') == 'MyServer'

    def test_label_falls_back_to_key(self):
        w = _watchful({'nas-server': {'host_uid': 'h1'}})
        assert w._label('nas-server') == 'nas-server'
