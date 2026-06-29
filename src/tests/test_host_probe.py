#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/hosts/probe — running a single module check once for the
Servers "test" feature (reuses the module's real check() with a minimal
Monitor stand-in)."""

from contextlib import contextmanager
from unittest.mock import patch

from lib.system import ssh_client
from lib.hosts import probe as host_probe


@contextmanager
def _mock_ssh(out):
    """Mock the remote SSH path used by host_exec (connect_host + run_command)."""
    with patch.object(ssh_client, 'HAS_PARAMIKO', True), \
         patch.object(ssh_client, 'connect_host', return_value=object()), \
         patch.object(ssh_client, 'run_command', return_value=(out, '', 0)):
        yield


class _FakeStore:
    def __init__(self, hosts):
        self._h = hosts
    def get(self, uid, **_kw):
        return self._h.get(uid)


_HOST = {'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': 'linux',
         'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'root'}}}

_PS_OUT = "nginx\nnginx\nsshd\n"


class TestProbeMonitor:

    def test_is_a_monitor(self):
        # Must satisfy ModuleBase's isinstance(obj, Monitor) check.
        import lib
        mon = host_probe._ProbeMonitor({}, None, None)
        assert isinstance(mon, lib.Monitor)
        assert mon.send_message('x', True) is None      # no-op, no Telegram

    def test_runs_process_check_remote(self):
        cfg = {'watchfuls.process': {'list': {
            'web': {'process': 'nginx', 'min_count': 2, 'enabled': True, 'host_uid': 'h1'}}}}
        store = host_probe.ProbeHostsStore(_HOST, _FakeStore({'h1': _HOST}))
        with _mock_ssh(_PS_OUT):
            results = host_probe.run_module_check('process', cfg, hosts_store=store)
        assert len(results) == 1
        assert results[0]['key'] == 'web' and results[0]['status'] is True
        assert results[0]['other_data']['count'] == 2

    def test_runs_process_check_failure(self):
        cfg = {'watchfuls.process': {'list': {
            'web': {'process': 'nginx', 'min_count': 5, 'enabled': True, 'host_uid': 'h1'}}}}
        store = host_probe.ProbeHostsStore(_HOST, _FakeStore({'h1': _HOST}))
        with _mock_ssh(_PS_OUT):
            results = host_probe.run_module_check('process', cfg, hosts_store=store)
        assert results[0]['status'] is False


class TestProbeHostsStore:

    def test_returns_draft_for_its_uid(self):
        real = _FakeStore({'real': {'uid': 'real', 'address': 'x'}})
        draft = {'uid': '__probe__', 'address': '10.0.0.9'}
        store = host_probe.ProbeHostsStore(draft, real)
        assert store.get('__probe__')['address'] == '10.0.0.9'
        assert store.get('real')['address'] == 'x'
        assert store.get('nope') is None
