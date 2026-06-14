#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a command on a target host — local or remote over SSH.

The classmethod-friendly counterpart of :meth:`ModuleBase.host_exec`: watchful
``discover`` actions are classmethods (no monitor/instance), so they call this
with a plain host context dict to list items on the bound host.

A *host context* is::

    {"kind": "local"|"remote", "os": "<canonical>", "address": "<host>",
     "ssh": {ssh_port, ssh_user, ssh_password, ssh_key, ssh_key_string,
             ssh_verify_host}}

Never raises — failures come back as ``('', <error>, -1)``.
"""

from __future__ import annotations

from lib import ssh_client


def run(host: dict | None, cmd: str, timeout: int = 15) -> tuple:
    """Run *cmd* on *host* and return ``(stdout, stderr, exit_code)``."""
    if not cmd:
        return '', 'no command', -1
    if isinstance(host, dict) and str(host.get('kind') or '').strip().lower() == 'remote':
        if not ssh_client.HAS_PARAMIKO:
            return '', 'paramiko is not installed', -1
        ssh = host.get('ssh') or {}
        address = str(host.get('address') or ssh.get('ssh_host') or '').strip()
        if not address:
            return '', 'remote host has no address', -1
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
    # Local (local host or no host context).
    from lib.exe import Exec  # noqa: PLC0415
    result = Exec.execute(command=cmd)
    return (result.out or ''), (result.err or ''), result.code


def is_remote(host: dict | None) -> bool:
    return isinstance(host, dict) and str(host.get('kind') or '').strip().lower() == 'remote'
