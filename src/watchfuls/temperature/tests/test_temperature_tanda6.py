#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/temperature from the second 2026-10-12 audit (WF-3).

A remote device left on ``os: auto`` that never reported its platform keeps the token; cpu,
process and the rest read it as Linux through their per-OS tables, and this module refused
it as "unsupported OS: auto" without running anything. ``device_os()`` now answers Linux for
it. ``device_exec`` is patched: nothing runs.
"""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


_OUT = '/sys/class/thermal/thermal_zone0/type:x86_pkg_temp\n/sys/class/thermal/thermal_zone0/temp:45000\n'


def _watchful(os_='auto'):
    from watchfuls.temperature import Watchful
    mm = create_mock_monitor({'watchfuls.temperature': {'list': {
        'k': {'enabled': True, 'device_uid': 'h1', 'sensor': 'x86_pkg_temp'}}}})
    mm._devices_store = _FakeStore({'h1': {
        'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': os_,
        'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'admin'}}}})
    return Watchful(mm)


class TestRemoteAutoIsLinux:

    def test_remote_auto_runs_the_linux_reading(self):
        w = _watchful('auto')
        with patch.object(w, 'device_exec', return_value=(_OUT, '', 0)) as de:
            items = w.check().list
        assert de.called
        assert 'thermal' in de.call_args_list[0].args[1]
        assert not any('unsupported' in str(v.get('message', '')).lower()
                       for v in items.values())
        assert all(v['status'] is True for v in items.values()), items

    def test_device_os_answers_linux_for_auto(self):
        w = _watchful('auto')
        assert w.device_os({'device_os': 'auto'}) == 'linux'
        assert w.device_os({'device_os': 'Windows'}) == 'windows'

    def test_an_explicit_other_os_is_still_refused(self):
        w = _watchful('windows')
        with patch.object(w, 'device_exec', return_value=('', '', 0)) as de:
            items = w.check().list
        de.assert_not_called()
        assert all(v['status'] is False for v in items.values())
