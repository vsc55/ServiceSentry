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
from lib.i18n import DEFAULT_LANG, translate


# The refusals below end up as the message of a check, and from there in a notification, so
# they are language keys and not English sentences. `run` and ModuleBase.device_exec translate
# them at the edge — `exec_error` is the one place that does it.

#: What a device with no way to run commands answers instead of running one somewhere else.
NO_EXEC = 'device_exec_no_exec'

#: What a check bound to a device that no longer exists answers. Never run locally: the
#: panel's own machine is not the device the check is about, and its numbers filed under that
#: label are worse than an error.
DEVICE_MISSING = 'device_exec_missing'

NO_COMMAND = 'device_exec_no_command'
INVALID = 'device_exec_invalid'
NO_PARAMIKO = 'device_exec_no_paramiko'
NO_ADDRESS = 'device_exec_no_address'
SSH_ERROR = 'device_exec_ssh_error'


def exec_error(key: str, *args, lang: str = '') -> tuple:
    """``('', <translated refusal>, -1)`` — the failure shape of :func:`run`."""
    return '', translate(lang or DEFAULT_LANG, key, *args), -1


def run(device: dict | None, cmd: str, timeout: int = 15, lang: str = '') -> tuple:
    """Run *cmd* on *device* and return ``(stdout, stderr, exit_code)``.

    A refusal comes back in *lang* (the default language when not given)."""
    if not cmd:
        return exec_error(NO_COMMAND, lang=lang)
    # A device that says it runs nothing runs nothing. Falling through to the local branch is
    # what `kind` used to do with every value that was not `remote`, and it made "no
    # connection" mean "the panel's own machine": a check bound to a switch measured the panel
    # and filed the answer under the switch's name. No device at all still runs locally — that
    # is a classic inline check, which has always meant this machine and says so by having no
    # device to disagree with.
    if isinstance(device, dict) and str(device.get('kind') or '').strip().lower() == 'none':
        return exec_error(NO_EXEC, lang=lang)
    if isinstance(device, dict) and str(device.get('kind') or '').strip().lower() == 'remote':
        if not ssh_client.HAS_PARAMIKO:
            return exec_error(NO_PARAMIKO, lang=lang)
        ssh = device.get('ssh') or {}
        address = str(device.get('address') or ssh.get('ssh_host') or '').strip()
        if not address:
            return exec_error(NO_ADDRESS, lang=lang)
        client = None
        try:
            client = ssh_client.connect_host(ssh, address, timeout=timeout)
            return ssh_client.run_command(client, cmd, timeout=timeout)
        except Exception as exc:  # pylint: disable=broad-except
            return exec_error(SSH_ERROR, exc, lang=lang)
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
