#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/temperature — host-centric sensor temperature (Linux).

Sensors are read via ``host_exec`` (mocked); the thermal-zone parser runs for
real against canned ``/sys/class/thermal`` output.
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
    from watchfuls.temperature import Watchful
    mm = create_mock_monitor({'watchfuls.temperature': {'list': items}})
    mm._hosts_store = _FakeStore(hosts or {'h1': _host()})
    return Watchful(mm)


_THERMAL = "x86_pkg_temp|45000\nacpitz|39500\nacpitz|41000\n"


class TestParser:

    def test_parse_and_dedup(self):
        from watchfuls.temperature import Watchful
        d = dict(Watchful._parse_thermal(_THERMAL))
        assert d['x86_pkg_temp'] == 45.0
        assert d['acpitz'] == 39.5
        assert d['acpitz_1'] == 41.0       # duplicate type → suffixed


class TestCheck:

    def test_ok_below_threshold(self):
        w = _watchful({'cpu': {'enabled': True, 'sensor': 'x86_pkg_temp',
                               'alert': 80, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_THERMAL, '', 0)):
            items = w.check().list
        assert items['cpu']['status'] is True
        assert items['cpu']['other_data']['temp'] == 45.0

    def test_over_threshold_warns(self):
        w = _watchful({'cpu': {'enabled': True, 'sensor': 'x86_pkg_temp',
                               'alert': 40, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_THERMAL, '', 0)):
            items = w.check().list
        assert items['cpu']['status'] is False
        assert 'Warning' in items['cpu']['message']

    def test_non_linux_unsupported(self):
        w = _watchful({'cpu': {'enabled': True, 'sensor': 'x', 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='windows')})
        with patch.object(w, 'host_exec') as he:
            items = w.check().list
        he.assert_not_called()
        assert items['cpu']['status'] is False and 'Linux' in items['cpu']['message']

    def test_sensor_not_found_is_error(self):
        w = _watchful({'cpu': {'enabled': True, 'sensor': 'nope', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_THERMAL, '', 0)):
            items = w.check().list
        assert items['cpu']['status'] is False and 'Error' in items['cpu']['message']

    def test_disabled_and_maintenance_skipped(self):
        w = _watchful({'cpu': {'enabled': False, 'sensor': 'x', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()
        w2 = _watchful({'cpu': {'enabled': True, 'sensor': 'x', 'host_uid': 'h1'}},
                       hosts={'h1': _host(maintenance=True)})
        with patch.object(w2, 'host_exec') as he2:
            assert len(w2.check().items()) == 0
        he2.assert_not_called()


class TestDiscover:

    def test_discover_remote(self):
        from watchfuls.temperature import Watchful
        host = {'kind': 'remote', 'os': 'linux', 'address': '10.0.0.9', 'ssh': {}}
        with patch('lib.host_runner.run', return_value=(_THERMAL, '', 0)):
            names = {s['name'] for s in Watchful.discover({'__host__': host})}
        assert {'x86_pkg_temp', 'acpitz', 'acpitz_1'} <= names
