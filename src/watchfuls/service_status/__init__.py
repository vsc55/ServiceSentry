#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry
#
# Copyright © 2019  Javier Pastor (aka VSC55)
# <jpastor at cerebelum dot net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Watchful module to monitor system services, on the bound host.

Host-centric: each check binds to a host (``host_uid``).  The service state is
read on that host via :meth:`ModuleBase.host_exec` — locally or over SSH — using
an OS-appropriate command (``systemctl`` on Linux, ``sc`` on Windows,
``launchctl`` on macOS, ``service`` on FreeBSD).  Optional auto-remediation
starts/stops the service to restore the expected state.  ``discover`` lists the
services of the machine running the web admin (autocomplete helper).
"""

import json
import os
import platform
import shlex

from lib.modules import ModuleBase

from .actions import ServiceDiscovery

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

# Per-OS command to read a service's state ({svc} substituted, shell-quoted).
def _win_quote(s: str) -> str:
    """Quote an argument for cmd.exe (host_exec runs with shell=True on Windows). Double
    quotes neutralise the command separators (& | < > ^) and embedded quotes are stripped so
    the value can't break out — the POSIX branches use shlex.quote instead. NB: this does
    NOT stop ``%VAR%`` environment-variable expansion (no command execution, and the value
    is admin/config-controlled), so it's not a full sandbox — just injection containment."""
    return '"' + str(s).replace('"', '') + '"'


_STATUS_CMDS = {
    'linux':   'systemctl is-active {svc}',
    'windows': 'sc query {svc}',
    'darwin':  'launchctl list {svc}',
    'freebsd': 'service {svc} status',
}
# Per-OS start/stop command ({action} = start|stop).
_ACTION_CMDS = {
    'linux':   'systemctl {action} {svc}',
    'windows': 'sc {action} {svc}',
    'darwin':  'launchctl {action} {svc}',
    'freebsd': 'service {svc} {action}',
}


def _detect_linux_init() -> str:
    import shutil  # noqa: PLC0415
    if os.path.exists('/run/systemd/system'):
        return 'systemd'
    if shutil.which('rc-service'):
        return 'openrc'
    return 'sysv'


class Watchful(ServiceDiscovery, ModuleBase):
    """Monitor service state per host (running/stopped), with optional remediation."""

    ITEM_SCHEMA = _SCHEMA
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'discover'})
    _PLATFORM: str = platform.system().lower()
    _INIT_SYSTEM: str = _detect_linux_init() if platform.system().lower() == 'linux' else 'systemd'

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            return self.dict_return
        items = []
        for key, value in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            if not value.get('enabled', self._DEFAULTS.get('enabled', True)):
                continue
            items.append((key, value))
        self.run_parallel(items, self._service_check, 'Service')
        super().check()
        return self.dict_return

    def _service_check(self, key, raw):
        item = self.resolve_host(raw)
        if item.get('_host_maintenance') or not item.get('enabled', True):
            return
        # The item key is a stable UID; the message uses the editable 'label'
        # (e.g. "host - service"), falling back to the service/unit name.  The
        # status is always tracked under the key so it stays stable across edits.
        service_name = (item.get('service', '') or '').strip() or key
        label = (item.get('label', '') or '').strip() or service_name
        expected = (item.get('expected', '') or 'running').strip().lower()
        if expected not in ('running', 'stopped'):
            expected = 'running'
        remediation = bool(item.get('remediation', False))
        os_ = self.host_os(item)
        if os_ not in _STATUS_CMDS:
            self.dict_return.set(key, False,
                                 self._msg('svc_unsupported_os', label, os_),
                                 name=label)
            return

        status, error, detail = self._service_state(item, os_, service_name)
        ok = status if expected == 'running' else not status
        s_message = self._fmt(label, ok, status, error, detail)

        # NOT ModuleBase._emit, deliberately: the gate is evaluated ONCE and governs TWO
        # notifications (the fall, then the outcome of the repair). _emit couples one gate
        # to one send, so routing this through it would silence the recovery message —
        # check_status compares against the STORED status, which the fall has not yet
        # updated within this cycle.
        remediation_use = None
        severity = None
        if self.check_status(ok, self.name_module, key):
            self.send_message(s_message, ok, item=label)
            if not ok and remediation:
                self._service_remediation(item, os_, service_name, expected)
                status, error, detail = self._service_state(item, os_, service_name)
                repaired = status if expected == 'running' else not status
                remediation_use = repaired
                s_message = self._msg('svc_recovery_prefix') + self._fmt(
                    label, repaired, status, error, detail, unsuccessful=True)
                # The ALERT reports the outcome, so a successful repair routes as a
                # recovery — that is the news the operator wants.
                self.send_message(s_message, repaired, item=label)
                # The RECORDED result does not: a cycle in which the service fell and had
                # to be restarted is not a clean OK, and storing it as one would erase the
                # incident from the panel and from history the moment it was fixed. It is
                # a warning — running again, but something happened. A repair that failed
                # stays a plain down.
                ok = False
                severity = 'warning' if repaired else None

        other_data = {'error': error, 'status_detail': detail, 'remediation': remediation_use}
        self.dict_return.set(key, ok, s_message, False, other_data,
                             severity=severity, name=label)

    def _fmt(self, display_name, ok, status, error, detail, unsuccessful=False):
        if ok:
            if unsuccessful:
                return self._msg('svc_ok', display_name)
            return self._msg('svc_running' if status else 'svc_stopped', display_name)
        if error and detail:
            return self._msg('svc_error', display_name, detail)
        if status:
            return self._msg('svc_running_unexpected', display_name)
        return self._msg('svc_unsuccessful' if unsuccessful else 'svc_stop', display_name)

    def _service_state(self, item, os_, service_name):
        """Return (running, error, detail) by running the per-OS status command."""
        svc = _win_quote(service_name) if os_ == 'windows' else shlex.quote(service_name)
        cmd = _STATUS_CMDS[os_].format(svc=svc)
        out, err, code = self.host_exec(
            item, cmd, timeout=self.module_default('timeout', 15))
        return self._parse_state(os_, out, err, code)

    @classmethod
    def _parse_state(cls, os_, out, err, code):
        out = out or ''
        err = err or ''
        if os_ == 'linux':
            state = (out.strip().splitlines() or [''])[-1].strip()
            if state == 'active':
                return True, False, 'running'
            if state in ('inactive', 'failed', 'activating', 'deactivating', 'reloading'):
                return False, False, state
            # No recognisable state and the command itself failed → detection error.
            return False, (not state and code != 0), (state or err.strip() or 'unknown')
        if os_ == 'windows':
            up = out.upper()
            if '1060' in out or 'does not exist' in out.lower():
                return False, True, 'service does not exist'
            if 'RUNNING' in up:
                return True, False, 'running'
            if 'STOPPED' in up:
                return False, False, 'stopped'
            return False, code != 0, (cls._clear_str(out) or err.strip() or 'unknown')
        if os_ == 'darwin':
            if code == 0 and '"PID"' in out and '"PID" = 0;' not in out:
                return True, False, 'running'
            if code != 0:
                return False, True, (err.strip() or 'could not find service')
            return False, False, 'stopped'
        # freebsd: `service <svc> status` → exit 0 when running.
        if code == 0:
            return True, False, 'running'
        combined = (out + err).strip()
        return False, ('unknown' in combined.lower() or not combined), (combined or 'stopped')

    def _service_remediation(self, item, os_, service_name, expected):
        action = 'stop' if expected == 'stopped' else 'start'
        svc = _win_quote(service_name) if os_ == 'windows' else shlex.quote(service_name)
        cmd = _ACTION_CMDS[os_].format(action=action, svc=svc)
        self.host_exec(item, cmd, timeout=self.module_default('timeout', 15))
