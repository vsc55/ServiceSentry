#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/process — host-centric process monitoring.

Each check binds to a host; the process list is read via ``host_exec`` (mocked
here, so no real command/SSH runs) and matched against ``min_count``.  The
per-OS match parser runs for real against canned ``ps``/``tasklist`` output.
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
    from watchfuls.process import Watchful
    mm = create_mock_monitor({'watchfuls.process': {'list': items}})
    mm._hosts_store = _FakeStore(hosts or {'h1': _host()})
    return Watchful(mm)


_PS_OUT = "systemd\nsshd\nnginx\nnginx\npython3\n"
_TASKLIST_OUT = (
    '"nginx.exe","1234","Services","0","12,000 K"\r\n'
    '"nginx.exe","1235","Services","0","12,000 K"\r\n'
    '"explorer.exe","999","Console","1","40,000 K"\r\n'
)


class TestCountMatches:

    def test_unix_counts_by_comm(self):
        from watchfuls.process import Watchful
        assert Watchful._count_matches(_PS_OUT, 'linux', 'nginx') == 2
        assert Watchful._count_matches(_PS_OUT, 'linux', 'sshd') == 1
        assert Watchful._count_matches(_PS_OUT, 'linux', 'absent') == 0

    def test_windows_counts_with_or_without_exe(self):
        from watchfuls.process import Watchful
        assert Watchful._count_matches(_TASKLIST_OUT, 'windows', 'nginx') == 2
        assert Watchful._count_matches(_TASKLIST_OUT, 'windows', 'nginx.exe') == 2
        assert Watchful._count_matches(_TASKLIST_OUT, 'windows', 'explorer') == 1


class TestProcessCheck:

    def test_disabled_module_empty(self):
        from watchfuls.process import Watchful
        mm = create_mock_monitor({'watchfuls.process': {'enabled': False,
                                  'list': {'a': {'enabled': True, 'process': 'nginx', 'host_uid': 'h1'}}}})
        mm._hosts_store = _FakeStore({'h1': _host()})
        w = Watchful(mm)
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()

    def test_disabled_item_skipped(self):
        w = _watchful({'a': {'enabled': False, 'process': 'nginx', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()

    def test_running_ok(self):
        w = _watchful({'web': {'enabled': True, 'process': 'nginx', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_PS_OUT, '', 0)):
            items = w.check().list
        assert items['web']['status'] is True
        assert items['web']['other_data']['count'] == 2

    def test_min_count_not_met(self):
        w = _watchful({'web': {'enabled': True, 'process': 'nginx',
                               'min_count': 3, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_PS_OUT, '', 0)):
            items = w.check().list
        assert items['web']['status'] is False
        assert '2/3' in items['web']['message']

    def test_windows_host_uses_tasklist(self):
        w = _watchful({'web': {'enabled': True, 'process': 'nginx', 'host_uid': 'h1'}},
                      hosts={'h1': _host(os='windows')})
        with patch.object(w, 'host_exec', return_value=(_TASKLIST_OUT, '', 0)) as he:
            items = w.check().list
        assert 'tasklist' in he.call_args.args[1]
        assert items['web']['status'] is True and items['web']['other_data']['count'] == 2

    def test_empty_process_uses_key(self):
        w = _watchful({'nginx': {'enabled': True, 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=(_PS_OUT, '', 0)):
            items = w.check().list
        assert items['nginx']['status'] is True

    def test_command_failure_is_error(self):
        w = _watchful({'web': {'enabled': True, 'process': 'nginx', 'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('', 'connection refused', 255)):
            items = w.check().list
        assert items['web']['status'] is False
        assert 'Error' in items['web']['message']

    def test_maintenance_host_skipped(self):
        w = _watchful({'web': {'enabled': True, 'process': 'nginx', 'host_uid': 'h1'}},
                      hosts={'h1': _host(maintenance=True)})
        with patch.object(w, 'host_exec') as he:
            assert len(w.check().items()) == 0
        he.assert_not_called()


class TestProcessDiscover:

    @patch('watchfuls.process.psutil.process_iter')
    def test_discover_counts_and_sorts(self, mock_iter):
        def _p(name):
            m = MagicMock(); m.info = {'name': name}; return m
        mock_iter.return_value = [_p('bash'), _p('bash'), _p('aaa')]
        out = _watchful({}).discover()
        assert out[0]['name'] == 'aaa'
        bash = next(x for x in out if x['name'] == 'bash')
        assert bash['status'] == '×2'

    @patch('watchfuls.process.psutil.process_iter', side_effect=Exception('boom'))
    def test_discover_exception_returns_empty(self, _):
        assert _watchful({}).discover() == []

    def test_discover_remote_over_ssh(self):
        from watchfuls.process import Watchful
        host = {'kind': 'remote', 'os': 'linux', 'address': '10.0.0.9', 'ssh': {}}
        with patch('lib.core.hosts.runner.run', return_value=(_PS_OUT, '', 0)) as run:
            res = {s['name']: s['status'] for s in Watchful.discover({'__host__': host})}
        assert run.call_args.args[1] == 'ps -A -o comm='
        assert res['nginx'] == '×2' and res['sshd'] == '×1'

    def test_discover_remote_windows_tasklist(self):
        from watchfuls.process import Watchful
        host = {'kind': 'remote', 'os': 'windows', 'address': '10.0.0.9', 'ssh': {}}
        with patch('lib.core.hosts.runner.run', return_value=(_TASKLIST_OUT, '', 0)) as run:
            res = {s['name']: s['status'] for s in Watchful.discover({'__host__': host})}
        assert 'tasklist' in run.call_args.args[1]
        assert res['nginx.exe'] == '×2'
