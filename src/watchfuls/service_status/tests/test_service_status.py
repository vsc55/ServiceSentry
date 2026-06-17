#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/service_status — host-centric service monitoring.

Service state is read via ``host_exec`` (mocked); the per-OS state parser runs
for real against canned command output.  ``discover`` (local autocomplete) is
unchanged and still covered.
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
    from watchfuls.service_status import Watchful
    mm = create_mock_monitor({'watchfuls.service_status': {'list': items}})
    mm._hosts_store = _FakeStore(hosts or {'h1': _host()})
    return Watchful(mm)


_SC_RUNNING = "SERVICE_NAME: nginx\n        STATE              : 4  RUNNING\n"
_SC_STOPPED = "SERVICE_NAME: nginx\n        STATE              : 1  STOPPED\n"
_SC_MISSING = "[SC] EnumQueryServicesStatus:OpenService FAILED 1060:\n"


class TestParseState:

    def test_linux_active(self):
        from watchfuls.service_status import Watchful
        assert Watchful._parse_state('linux', 'active\n', '', 0) == (True, False, 'running')

    def test_linux_inactive(self):
        from watchfuls.service_status import Watchful
        running, error, _ = Watchful._parse_state('linux', 'inactive\n', '', 3)
        assert running is False and error is False

    def test_linux_failed(self):
        from watchfuls.service_status import Watchful
        running, error, detail = Watchful._parse_state('linux', 'failed\n', '', 3)
        assert running is False and error is False and detail == 'failed'

    def test_linux_missing_is_error(self):
        from watchfuls.service_status import Watchful
        running, error, _ = Watchful._parse_state('linux', '', 'command not found', 127)
        assert running is False and error is True

    def test_windows_running(self):
        from watchfuls.service_status import Watchful
        assert Watchful._parse_state('windows', _SC_RUNNING, '', 0)[0] is True

    def test_windows_stopped(self):
        from watchfuls.service_status import Watchful
        running, error, detail = Watchful._parse_state('windows', _SC_STOPPED, '', 0)
        assert running is False and error is False and detail == 'stopped'

    def test_windows_missing_is_error(self):
        from watchfuls.service_status import Watchful
        running, error, _ = Watchful._parse_state('windows', _SC_MISSING, '', 1060)
        assert running is False and error is True

    def test_darwin_running(self):
        from watchfuls.service_status import Watchful
        out = '{\n\t"PID" = 1234;\n\t"Label" = "com.x";\n};\n'
        assert Watchful._parse_state('darwin', out, '', 0)[0] is True

    def test_freebsd_running(self):
        from watchfuls.service_status import Watchful
        assert Watchful._parse_state('freebsd', 'nginx is running.\n', '', 0)[0] is True

    def test_freebsd_stopped(self):
        from watchfuls.service_status import Watchful
        running, error, _ = Watchful._parse_state('freebsd', 'nginx is not running.\n', '', 1)
        assert running is False


class TestCheck:

    def test_running_ok(self):
        w = _watchful({'web': {'enabled': True, 'service': 'nginx', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('active', '', 0)):
            items = w.check().list
        assert items['web']['status'] is True
        assert 'Running' in items['web']['message']

    def test_expected_stopped_ok(self):
        w = _watchful({'web': {'enabled': True, 'service': 'nginx',
                               'expected': 'stopped', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('inactive', '', 3)):
            items = w.check().list
        assert items['web']['status'] is True
        assert 'Stopped' in items['web']['message']

    def test_running_but_expected_stopped(self):
        w = _watchful({'web': {'enabled': True, 'service': 'nginx',
                               'expected': 'stopped', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('active', '', 0)):
            items = w.check().list
        assert items['web']['status'] is False
        assert 'expected: Stopped' in items['web']['message']

    def test_windows_host_uses_sc(self):
        w = _watchful({'svc': {'enabled': True, 'service': 'nginx', 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='windows')})
        with patch.object(w, 'host_exec', return_value=(_SC_RUNNING, '', 0)) as he:
            items = w.check().list
        assert he.call_args.args[1].startswith('sc query')
        assert items['svc']['status'] is True

    def test_remediation_recovers(self):
        w = _watchful({'web': {'enabled': True, 'service': 'nginx',
                               'remediation': True, 'host_uid': 'h1'}})
        # Remediation only runs on a state *change* → make check_status report one.
        w._monitor.check_status = MagicMock(return_value=True)
        # First status call: stopped; remediation start; second call: active.
        calls = [('inactive', '', 3), ('', '', 0), ('active', '', 0)]
        with patch.object(w, 'host_exec', side_effect=calls) as he:
            items = w.check().list
        # status + start + re-check = 3 host_exec calls
        assert he.call_count == 3
        assert any('start' in c.args[1] for c in he.call_args_list)
        assert items['web']['status'] is True
        assert items['web']['other_data']['remediation'] is True

    def test_unsupported_os(self):
        w = _watchful({'web': {'enabled': True, 'service': 'nginx', 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='other')})
        with patch.object(w, 'host_exec') as he:
            items = w.check().list
        he.assert_not_called()
        assert items['web']['status'] is False and 'unsupported' in items['web']['message'].lower()

    def test_disabled_item_skipped(self):
        w = _watchful({'web': {'enabled': False, 'service': 'nginx', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()

    def test_maintenance_host_skipped(self):
        w = _watchful({'web': {'enabled': True, 'service': 'nginx', 'host_uid': 'h1'}},
                      hosts={'h1': _host(maintenance=True)})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()


class TestDiscover:

    def test_parse_systemd_list(self):
        from watchfuls.service_status import Watchful
        out = ("  nginx.service   loaded active running  Web server\n"
               "  cron.service    loaded active running  Cron\n")
        res = Watchful._parse_systemd_list(out)
        names = [s['name'] for s in res]
        assert 'nginx' in names and 'cron' in names

    def test_parse_sc_query(self):
        from watchfuls.service_status import Watchful
        out = ("SERVICE_NAME: nginx\n        STATE              : 4  RUNNING\n\n"
               "SERVICE_NAME: spooler\n        STATE              : 1  STOPPED\n")
        res = {s['name']: s['status'] for s in Watchful._parse_sc_query(out)}
        assert res == {'nginx': 'running', 'spooler': 'stopped'}

    def test_remote_discovery_uses_ssh(self):
        from watchfuls.service_status import Watchful
        host = {'kind': 'remote', 'os': 'linux', 'address': '10.0.0.9', 'ssh': {}}
        out = "  nginx.service   loaded active running  Web server\n"
        with patch('lib.hosts.runner.run', return_value=(out, '', 0)) as run:
            res = Watchful.discover({'__host__': host})
        assert run.call_args.args[1].startswith('systemctl list-units')
        assert any(s['name'] == 'nginx' for s in res)

    def test_clear_str(self):
        from watchfuls.service_status import Watchful
        assert Watchful._clear_str('(running)') == 'running'
        assert Watchful._clear_str(None) == ''
