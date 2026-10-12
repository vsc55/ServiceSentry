#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/service_status from the second 2026-10-12 audit (NET-5, WF-5).

* A Windows service name went into ``sc.exe query "<name>"``: cmd.exe double quotes, which a
  PowerShell remote shell expands (``"$(...)"`` runs). The name is now whitelisted.
* On Linux only ``systemctl`` was tried: an OpenRC or SysV host reported every service as an
  error. ``rc-service`` / ``service`` are the fallbacks when systemctl is missing.

``device_exec`` is patched throughout: nothing runs.
"""

from unittest.mock import patch

import pytest

from conftest import create_mock_monitor


class _FakeStore:
    def __init__(self, devices):
        self._h = devices

    def get(self, uid, **_kw):
        return self._h.get(uid)


def _watchful(os_, service='nginx', remediation=False, expected='running'):
    from watchfuls.service_status import Watchful
    mm = create_mock_monitor({'watchfuls.service_status': {'list': {
        'svc': {'enabled': True, 'service': service, 'device_uid': 'h1',
                'remediation': remediation, 'expected': expected}}}})
    mm._devices_store = _FakeStore({'h1': {
        'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': os_,
        'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'admin'}}}})
    return Watchful(mm)


class TestWindowsServiceName:

    @pytest.mark.parametrize('bad', [
        '$(New-Item -Path pwn)', 'a"b', 'svc & calc', 'svc`n', 'a;b', 'a|b', '%COMSPEC%',
        '-help'])
    def test_hostile_name_runs_nothing(self, bad):
        w = _watchful('windows', service=bad, remediation=True)
        with patch.object(w, 'device_exec', return_value=('', '', 1)) as de:
            items = w.check().list
        de.assert_not_called()
        assert items['svc']['status'] is False
        assert items['svc']['other_data']['error'] is True

    @pytest.mark.parametrize('name', ['Spooler', 'MSSQL$SQLEXPRESS', 'Windows Update',
                                      'svc_name-1.2', 'user@domain'])
    def test_real_names_still_run(self, name):
        w = _watchful('windows', service=name)
        with patch.object(w, 'device_exec',
                          return_value=('STATE : 4  RUNNING', '', 0)) as de:
            items = w.check().list
        assert de.call_args.args[1] == f'sc.exe query "{name}"'
        assert items['svc']['status'] is True

    def test_linux_names_are_not_restricted(self):
        """POSIX goes through shlex.quote; unit names carry `\\x2d` and `:`."""
        w = _watchful('linux', service=r'systemd-fsck@dev-disk-by\x2duuid.service')
        with patch.object(w, 'device_exec', return_value=('active\n', '', 0)) as de:
            items = w.check().list
        assert de.call_args.args[1].startswith('systemctl is-active ')
        assert items['svc']['status'] is True


class TestLinuxWithoutSystemd:

    def _exec(self, answers):
        """device_exec stand-in: answers by command prefix, records the commands."""
        calls = []

        def fake(item, cmd, timeout=15):
            calls.append(cmd)
            for prefix, ans in answers:
                if cmd.startswith(prefix):
                    return ans
            return ('', 'sh: not found', 127)
        return fake, calls

    def test_openrc_started(self):
        w = _watchful('linux')
        fake, calls = self._exec([
            ('systemctl', ('', 'sh: systemctl: not found', 127)),
            ('rc-service', (' * status: started\n', '', 0))])
        with patch.object(w, 'device_exec', side_effect=fake):
            items = w.check().list
        assert calls[1] == 'rc-service nginx status'
        assert items['svc']['status'] is True

    def test_openrc_stopped_is_a_stop_not_an_error(self):
        w = _watchful('linux')
        fake, _calls = self._exec([
            ('systemctl', ('', 'sh: systemctl: not found', 127)),
            ('rc-service', (' * status: stopped\n', '', 3))])
        with patch.object(w, 'device_exec', side_effect=fake):
            items = w.check().list
        assert items['svc']['status'] is False
        assert items['svc']['other_data']['error'] is False

    def test_sysv_service_when_rc_service_is_missing_too(self):
        w = _watchful('linux')
        fake, calls = self._exec([
            ('systemctl', ('', 'bash: systemctl: command not found', 127)),
            ('rc-service', ('', 'bash: rc-service: command not found', 127)),
            ('service', ('nginx is running.\n', '', 0))])
        with patch.object(w, 'device_exec', side_effect=fake):
            items = w.check().list
        assert calls[-1] == 'service nginx status'
        assert items['svc']['status'] is True

    def test_unknown_service_is_an_error(self):
        w = _watchful('linux')
        fake, _calls = self._exec([
            ('systemctl', ('', 'sh: systemctl: not found', 127)),
            ('rc-service', ('', " * rc-service: service `nginx' does not exist", 1))])
        with patch.object(w, 'device_exec', side_effect=fake):
            items = w.check().list
        assert items['svc']['other_data']['error'] is True

    def test_remediation_uses_the_init_that_answered(self):
        w = _watchful('linux', remediation=True)
        state = {'started': False}

        def fake(item, cmd, timeout=15):
            if cmd.startswith('systemctl'):
                return '', 'sh: systemctl: not found', 127
            if cmd == 'rc-service nginx start':
                state['started'] = True
                return '', '', 0
            if cmd == 'rc-service nginx status':
                return ((' * status: started\n', '', 0) if state['started']
                        else (' * status: stopped\n', '', 3))
            return '', 'unexpected', 1
        w._monitor.check_status.return_value = True     # the fall is a status change
        with patch.object(w, 'device_exec', side_effect=fake) as de:
            w.check()
        cmds = [c.args[1] for c in de.call_args_list]
        assert 'rc-service nginx start' in cmds
        assert not any(c.startswith('systemctl start') for c in cmds)

    def test_systemd_host_never_tries_the_fallbacks(self):
        w = _watchful('linux')
        with patch.object(w, 'device_exec', return_value=('inactive\n', '', 3)) as de:
            w.check()
        assert de.call_count == 1
