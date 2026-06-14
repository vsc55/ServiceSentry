#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/filesystemusage — host-centric disk usage monitoring.

Usage is read via ``host_exec`` (mocked); the per-OS parsers run for real
against canned ``df``/``wmic`` output.
"""

from unittest.mock import patch, MagicMock

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
    from watchfuls.filesystemusage import Watchful
    mm = create_mock_monitor({'watchfuls.filesystemusage': {'list': items}})
    mm._hosts_store = _FakeStore(hosts or {'h1': _host()})
    return Watchful(mm)


_DF = ("Filesystem 1024-blocks Used Available Capacity Mounted on\n"
       "/dev/sda1 100000 75000 25000 75% /\n"
       "/dev/sdb1 200000 180000 20000 90% /data\n")
_WMIC = ("\r\nDeviceID=C:\r\nFreeSpace=25000000\r\nSize=100000000\r\n\r\n"
         "DeviceID=D:\r\nFreeSpace=10000000\r\nSize=100000000\r\n\r\n")


class TestParsers:

    def test_df_by_mount(self):
        from watchfuls.filesystemusage import Watchful
        assert Watchful._parse_df(_DF, '/') == 75
        assert Watchful._parse_df(_DF, '/data') == 90
        assert Watchful._parse_df(_DF, '/dev/sda1') == 75   # match by device too
        assert Watchful._parse_df(_DF, '/nope') is None

    def test_wmic(self):
        from watchfuls.filesystemusage import Watchful
        assert Watchful._parse_wmic(_WMIC, 'C:') == 75       # (100-25)/100
        assert Watchful._parse_wmic(_WMIC, 'D:') == 90


class TestCheck:

    def test_ok_below_threshold(self):
        # Result is keyed by the item key (not the mount), so checks stay distinct.
        w = _watchful({'root': {'enabled': True, 'partition': '/', 'alert': 85, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_DF, '', 0)):
            items = w.check().list
        assert items['root']['status'] is True
        assert items['root']['other_data']['used'] == 75
        assert items['root']['other_data']['mount'] == '/'

    def test_alert_above_threshold(self):
        w = _watchful({'data': {'enabled': True, 'partition': '/data', 'alert': 85, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_DF, '', 0)):
            items = w.check().list
        assert items['data']['status'] is False        # 90 > 85
        assert 'Warning' in items['data']['message']

    def test_windows_host_uses_wmic(self):
        w = _watchful({'c': {'enabled': True, 'partition': 'C:', 'alert': 85, 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='windows')})
        with patch.object(w, 'host_exec', return_value=(_WMIC, '', 0)) as he:
            items = w.check().list
        assert 'wmic' in he.call_args.args[1]
        assert items['c']['status'] is True and items['c']['other_data']['used'] == 75

    def test_message_uses_label_to_identify_server(self):
        # The label (e.g. "NS1 - /") identifies the server in the notification.
        w = _watchful({'uid-a': {'enabled': True, 'partition': '/', 'label': 'NS1 - /',
                                 'alert': 85, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_DF, '', 0)):
            items = w.check().list
        assert 'NS1 - /' in items['uid-a']['message']

    def test_same_mount_distinct_items_do_not_collide(self):
        # Two checks on the same mount (e.g. on different hosts) must produce two
        # results, keyed by their item keys — not collapse into one.
        w = _watchful({
            'uid-a': {'enabled': True, 'partition': '/', 'alert': 85, 'host_uid': 'h1'},
            'uid-b': {'enabled': True, 'partition': '/', 'alert': 85, 'host_uid': 'h1'},
        })
        with patch.object(w, 'host_exec', return_value=(_DF, '', 0)):
            items = w.check().list
        assert set(items.keys()) == {'uid-a', 'uid-b'}

    def test_partition_not_found_is_error(self):
        w = _watchful({'x': {'enabled': True, 'partition': '/nope', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_DF, '', 0)):
            items = w.check().list
        assert items['x']['status'] is False and 'Error' in items['x']['message']

    def test_disabled_and_maintenance_skipped(self):
        w = _watchful({'a': {'enabled': False, 'partition': '/', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()
        w2 = _watchful({'a': {'enabled': True, 'partition': '/', 'host_uid': 'h1'}},
                       hosts={'h1': _host(maintenance=True)})
        with patch.object(w2, 'host_exec') as he2:
            assert len(w2.check().items()) == 0
        he2.assert_not_called()


class TestDiscover:

    def test_discover_remote_df(self):
        from watchfuls.filesystemusage import Watchful
        host = {'kind': 'remote', 'os': 'linux', 'address': '10.0.0.9', 'ssh': {}}
        with patch('lib.host_runner.run', return_value=(_DF, '', 0)) as run:
            names = {s['name'] for s in Watchful.discover({'__host__': host})}
        assert run.call_args.args[1] == 'df -P -k'
        assert '/' in names and '/data' in names

    @patch('watchfuls.filesystemusage.psutil.disk_partitions',
           return_value=[MagicMock(mountpoint='/', device='/dev/sda1', fstype='ext4')])
    @patch('watchfuls.filesystemusage.psutil.disk_usage',
           return_value=MagicMock(percent=42.0))
    def test_discover_local(self, _u, _p):
        out = _watchful({}).discover()
        assert out and out[0]['name'] == '/'
