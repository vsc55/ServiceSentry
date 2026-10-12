#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/service_status found by the 2026-10-12 audit."""

from unittest.mock import patch

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


def _watchful(os_):
    from watchfuls.service_status import Watchful
    mm = create_mock_monitor({'watchfuls.service_status': {'list': {
        'svc': {'enabled': True, 'service': 'nginx', 'device_uid': 'h1',
                'remediation': True}}}})
    mm._devices_store = _FakeStore({'h1': {
        'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': os_,
        'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'admin'}}}})
    return Watchful(mm)


class TestWindowsUsesScExe:
    """Over SSH a Windows device usually lands in PowerShell, where bare `sc` is the alias of
    Set-Content: the "query" wrote a file and never read the service."""

    def test_status_and_remediation_commands_name_sc_exe(self):
        from watchfuls.service_status import _ACTION_CMDS, _STATUS_CMDS
        assert _STATUS_CMDS['windows'].startswith('sc.exe ')
        assert _ACTION_CMDS['windows'].startswith('sc.exe ')

    def test_discovery_command_names_sc_exe(self):
        from watchfuls.service_status import Watchful
        assert Watchful._DISCOVER_CMDS['windows'].startswith('sc.exe ')


class TestRemoteAutoOs:
    """A remote device left on `os: auto` keeps the token; every other OS module reads it as
    Linux, and this one refused it as "unsupported" without running anything."""

    def test_auto_is_checked_as_linux(self):
        w = _watchful('auto')
        with patch.object(w, 'device_exec', return_value=('active\n', '', 0)) as he:
            row = w.check().list['svc']
        assert he.call_args.args[1].startswith('systemctl is-active')
        assert row['status'] is True
