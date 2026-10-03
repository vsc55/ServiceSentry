#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a command on a target device — local or remote over SSH.

The classmethod-friendly counterpart of :meth:`ModuleBase.device_exec`: watchful
``discover`` actions are classmethods (no monitor/instance), so they call this
with a plain device context dict to list items on the bound device.

A *device context* is::

    {"kind": "local"|"remote", "os": "<canonical>", "address": "<device>",
     "ssh": {ssh_port, ssh_user, ssh_password, ssh_key, ssh_key_string,
             ssh_verify_host}}

Never raises — failures come back as ``('', <error>, -1)``.
"""

from __future__ import annotations

from lib.core.devices import ssh_client


#: What a device with no way to run commands answers instead of running one somewhere else.
NO_EXEC = 'this device has no connection for running commands'


def run(device: dict | None, cmd: str, timeout: int = 15) -> tuple:
    """Run *cmd* on *device* and return ``(stdout, stderr, exit_code)``."""
    if not cmd:
        return '', 'no command', -1
    # A device that says it runs nothing runs nothing. Falling through to the local branch is
    # what `kind` used to do with every value that was not `remote`, and it made "no
    # connection" mean "the panel's own machine": a check bound to a switch measured the panel
    # and filed the answer under the switch's name. No device at all still runs locally — that
    # is a classic inline check, which has always meant this machine and says so by having no
    # device to disagree with.
    if isinstance(device, dict) and str(device.get('kind') or '').strip().lower() == 'none':
        return '', NO_EXEC, -1
    if isinstance(device, dict) and str(device.get('kind') or '').strip().lower() == 'remote':
        if not ssh_client.HAS_PARAMIKO:
            return '', 'paramiko is not installed', -1
        ssh = device.get('ssh') or {}
        address = str(device.get('address') or ssh.get('ssh_host') or '').strip()
        if not address:
            return '', 'remote device has no address', -1
        client = None
        try:
            client = ssh_client.connect_host(ssh, address, timeout=timeout)
            return ssh_client.run_command(client, cmd, timeout=timeout)
        except Exception as exc:  # pylint: disable=broad-except
            return '', f'SSH error: {exc}', -1
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # pylint: disable=broad-except
                    pass
    # Local (local device or no device context).
    from lib.system.exe import Exec  # noqa: PLC0415
    result = Exec.execute(command=cmd)
    return (result.out or ''), (result.err or ''), result.code


def is_remote(device: dict | None) -> bool:
    return isinstance(device, dict) and str(device.get('kind') or '').strip().lower() == 'remote'
