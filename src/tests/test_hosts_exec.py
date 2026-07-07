#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host-aware command runner (ModuleBase.host_exec & helpers).

These back the OS modules (raid, ram_swap, process, service_status…): a check
bound to a remote host runs its command over the host's SSH connection; a local
or inline check runs it locally.
"""

from unittest.mock import patch, MagicMock

from conftest import create_mock_monitor

import watchfuls.ping as ping
from lib.core.hosts import ssh_client


def _w():
    return ping.Watchful(create_mock_monitor({'watchfuls.ping': {}}))


class TestHostCmdFor:

    def test_picks_by_os(self):
        cmds = {'linux': 'free', 'windows': 'wmic', 'darwin': 'vm_stat'}
        assert _w().host_cmd_for({'host_os': 'windows'}, cmds) == 'wmic'
        assert _w().host_cmd_for({'host_os': 'darwin'}, cmds) == 'vm_stat'

    def test_falls_back_to_default_os(self):
        cmds = {'linux': 'free'}
        assert _w().host_cmd_for({'host_os': 'freebsd'}, cmds) == 'free'

    def test_empty_cmds(self):
        assert _w().host_cmd_for({'host_os': 'linux'}, {}) == ''


class TestHostExecLocal:

    def test_local_inline_runs_locally(self):
        w = _w()
        # Local path runs through the shell (subprocess.run shell=True).
        fake = MagicMock(stdout='OUT', stderr='', returncode=0)
        with patch('subprocess.run', return_value=fake) as sr:
            out, err, code = w.host_exec({'host_kind': 'local'}, 'echo hi')
        assert (out, err, code) == ('OUT', '', 0)
        assert sr.call_args.kwargs.get('shell') is True

    def test_no_command_is_error(self):
        out, err, code = _w().host_exec({'host_kind': 'local'}, '')
        assert code == -1 and 'command' in err


class TestHostExecRemote:

    def _remote_item(self):
        return {'host_kind': 'remote', 'host_os': 'linux', 'ssh_host': '10.0.0.9',
                'ssh_user': 'root', 'ssh_port': 22}

    def test_remote_runs_over_ssh(self):
        w = _w()
        fake_client = object()
        with patch.object(ssh_client, 'HAS_PARAMIKO', True), \
             patch.object(ssh_client, 'connect_host', return_value=fake_client) as conn, \
             patch.object(ssh_client, 'run_command', return_value=('MEM', '', 0)) as run:
            out, err, code = w.host_exec(self._remote_item(), 'free -b')
        assert (out, err, code) == ('MEM', '', 0)
        assert conn.call_args.args[1] == '10.0.0.9'      # address used as ssh host
        assert run.call_args.args[1] == 'free -b'

    def test_remote_without_address_errors(self):
        w = _w()
        item = {'host_kind': 'remote', 'ssh_host': ''}
        with patch.object(ssh_client, 'HAS_PARAMIKO', True):
            out, err, code = w.host_exec(item, 'free')
        assert code == -1 and 'address' in err

    def test_remote_without_paramiko(self):
        w = _w()
        with patch.object(ssh_client, 'HAS_PARAMIKO', False):
            out, err, code = w.host_exec(self._remote_item(), 'free')
        assert code == -1 and 'paramiko' in err.lower()

    def test_remote_ssh_failure_caught(self):
        w = _w()
        with patch.object(ssh_client, 'HAS_PARAMIKO', True), \
             patch.object(ssh_client, 'connect_host', side_effect=OSError('refused')):
            out, err, code = w.host_exec(self._remote_item(), 'free')
        assert code == -1 and 'refused' in err


class TestRunCommand:

    def test_run_command_decodes_and_exit_code(self):
        class _Chan:
            def recv_exit_status(self): return 0
        class _Std:
            def __init__(self, b, chan=None): self._b = b; self.channel = chan
            def read(self): return self._b
        class _Client:
            def exec_command(self, cmd, timeout=None):
                return None, _Std(b'hello\n', _Chan()), _Std(b'')
        out, err, code = ssh_client.run_command(_Client(), 'echo hello')
        assert out.strip() == 'hello' and err == '' and code == 0

    def test_run_command_transport_error(self):
        class _Client:
            def exec_command(self, cmd, timeout=None):
                raise OSError('boom')
        out, err, code = ssh_client.run_command(_Client(), 'x')
        assert out == '' and 'boom' in err and code == -1
