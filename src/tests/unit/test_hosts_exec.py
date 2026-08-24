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


class TestADeviceThatRunsNothing:
    """`kind == 'none'` — the default, and the answer for most equipment: a switch, a router,
    a UPS or a NAS is read over SNMP and there is nothing to run a shell command on.

    It has to REFUSE, not fall through. Every value that was not `remote` used to mean "here",
    so a check bound to a device with no connection ran on the panel's own machine and filed
    the answer under that device's name — no error, no warning, a number that was true about
    the wrong box. An option that changes nothing would be worse than not having one.
    """

    def test_it_does_not_run_the_command_anywhere(self):
        with patch('subprocess.run') as sr:
            out, err, code = _w().host_exec({'host_kind': 'none'}, 'echo hi')
        assert code == -1 and out == ''
        assert not sr.called, "it ran the device's command on the panel"

    def test_it_says_why(self):
        _, err, _ = _w().host_exec({'host_kind': 'none'}, 'echo hi')
        assert 'connection' in err.lower(), err

    def test_the_runner_agrees_with_it(self):
        """Two entry points, one decision: `hosts.runner.run` is the other side of the same
        question and must answer it the same way."""
        from lib.core.hosts import runner                      # noqa: PLC0415
        with patch('subprocess.run') as sr:
            out, err, code = runner.run({'kind': 'none', 'address': 'sw1'}, 'echo hi')
        assert (out, code) == ('', -1) and not sr.called
        assert err == runner.NO_EXEC
        _, err2, _ = _w().host_exec({'host_kind': 'none'}, 'echo hi')
        assert err2 == runner.NO_EXEC, 'two wordings for one refusal'

    def test_no_host_at_all_still_runs_here(self):
        """A classic inline check has always meant this machine, and says so by having no host
        to disagree with. Refusing that would be reading "no connection" out of "no device"."""
        from lib.core.hosts import runner                      # noqa: PLC0415
        fake = MagicMock(stdout='OUT', stderr='', returncode=0)
        with patch('subprocess.run', return_value=fake):
            assert runner.run(None, 'echo hi') == ('OUT', '', 0)

    def test_a_bound_host_always_carries_one_of_the_three(self):
        """An item with NO `host_kind` is the inline case and runs here — that is the classic
        check and it has no device to disagree with. What must not exist is a BOUND host whose
        kind arrives as something else: the binding writes the store's own value through, so
        the refusal above can be trusted to fire when it should."""
        from lib.core.hosts.store import HostsStore            # noqa: PLC0415
        src = _read_binding()
        assert "resolved['host_kind'] = str(primary.get('kind') or 'none')" in src, (
            'the binding collapses the kind again, so `none` never reaches host_exec')
        assert set(HostsStore.KINDS) == {'none', 'local', 'remote'}


def _read_binding():
    import os as _os                                            # noqa: PLC0415
    root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
    with open(_os.path.join(root, 'lib', 'modules', 'host_binding.py'),
              encoding='utf-8') as fh:
        return fh.read()


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
