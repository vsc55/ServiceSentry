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
import subprocess

import psutil

from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

# Per-OS command to read a service's state ({svc} substituted, shell-quoted).
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


class Watchful(ModuleBase):
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
                                 f'Service: {label} - *unsupported host OS: {os_}* ⚠️')
            return

        status, error, detail = self._service_state(item, os_, service_name)
        ok = status if expected == 'running' else not status
        s_message = self._fmt(label, ok, status, error, detail)

        remediation_use = None
        if self.check_status(ok, self.name_module, key):
            self.send_message(s_message, ok)
            if not ok and remediation:
                self._service_remediation(item, os_, service_name, expected)
                status, error, detail = self._service_state(item, os_, service_name)
                ok = status if expected == 'running' else not status
                remediation_use = ok
                s_message = '*Recovery* ' + self._fmt(label, ok, status, error, detail,
                                                      unsuccessful=True)
                self.send_message(s_message, ok)

        other_data = {'error': error, 'status_detail': detail, 'remediation': remediation_use}
        self.dict_return.set(key, ok, s_message, False, other_data)

    @staticmethod
    def _fmt(display_name, ok, status, error, detail, unsuccessful=False):
        msg = f'Service: {display_name} '
        if ok:
            msg += ' - *OK* ✅' if unsuccessful else \
                f' - *{"Running" if status else "Stopped"}* ✅'
        else:
            if error and detail:
                msg += f'- *Error: {detail}* '
            elif status:
                msg += '- *Running (expected: Stopped)* '
            else:
                msg += '- *UNSUCCESSFUL* ' if unsuccessful else '- *Stop* '
            msg += '⚠️'
        return msg

    def _service_state(self, item, os_, service_name):
        """Return (running, error, detail) by running the per-OS status command."""
        svc = service_name if os_ == 'windows' else shlex.quote(service_name)
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
        svc = service_name if os_ == 'windows' else shlex.quote(service_name)
        cmd = _ACTION_CMDS[os_].format(action=action, svc=svc)
        self.host_exec(item, cmd, timeout=self.module_default('timeout', 15))

    # ── Discover (local autocomplete, or over SSH for a remote host) ──────────
    @classmethod
    def discover(cls, config=None) -> list:
        """Return [{name, display_name, status}] for the host's services.

        With a remote host context (``config['__host__']``, injected by the route
        for the Servers modal) the list is read over SSH; otherwise from THIS
        machine.
        """
        from lib.hosts import runner as host_runner  # noqa: PLC0415
        host = (config or {}).get('__host__') if isinstance(config, dict) else None
        if host_runner.is_remote(host):
            return cls._discover_remote(host, str(host.get('os') or 'linux'))
        if cls._PLATFORM == 'windows':
            return cls._discover_windows()
        if cls._INIT_SYSTEM == 'openrc':
            return cls._discover_openrc()
        if cls._INIT_SYSTEM == 'sysv':
            return cls._discover_sysv()
        try:
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--all',
                 '--no-pager', '--no-legend', '--plain'],
                capture_output=True, text=True, timeout=10,
            )
            return cls._parse_systemd_list(result.stdout)
        except Exception:
            return []

    # ── Remote discovery (over SSH) ──────────────────────────────────────────
    _DISCOVER_CMDS = {
        'linux':   'systemctl list-units --type=service --all --no-pager --no-legend --plain',
        'windows': 'sc query state= all',
        'darwin':  'launchctl list',
        'freebsd': 'service -e',
    }

    @classmethod
    def _discover_remote(cls, host, os_: str) -> list:
        from lib.hosts import runner as host_runner  # noqa: PLC0415
        cmd = cls._DISCOVER_CMDS.get(os_) or cls._DISCOVER_CMDS['linux']
        out, _err, code = host_runner.run(host, cmd, timeout=15)
        if code != 0 and not out:
            return []
        if os_ == 'windows':
            return cls._parse_sc_query(out)
        if os_ == 'darwin':
            return cls._parse_launchctl(out)
        if os_ == 'freebsd':
            return cls._parse_service_e(out)
        return cls._parse_systemd_list(out)

    @staticmethod
    def _parse_systemd_list(stdout: str) -> list:
        services = []
        for line in (stdout or '').split('\n'):
            cols = line.split()
            if len(cols) < 4:
                continue
            raw_name = cols[0]
            if not raw_name.endswith('.service'):
                continue
            name = raw_name[:-len('.service')]
            status = cols[3]
            display = ' '.join(cols[4:]) if len(cols) > 4 else ''
            services.append({'name': name, 'display_name': display, 'status': status})
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _parse_sc_query(stdout: str) -> list:
        """Parse `sc query state= all` blocks (SERVICE_NAME / STATE …RUNNING)."""
        services, name = [], None
        for line in (stdout or '').splitlines():
            s = line.strip()
            if s.upper().startswith('SERVICE_NAME:'):
                name = s.split(':', 1)[1].strip()
            elif 'STATE' in s.upper() and name:
                up = s.upper()
                status = 'running' if 'RUNNING' in up else ('stopped' if 'STOPPED' in up else 'unknown')
                services.append({'name': name, 'display_name': name, 'status': status})
                name = None
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _parse_launchctl(stdout: str) -> list:
        """Parse `launchctl list` lines: <PID>\t<status>\t<label>."""
        services = []
        for line in (stdout or '').splitlines()[1:]:   # skip header
            cols = line.split('\t') if '\t' in line else line.split()
            if len(cols) < 3:
                continue
            pid, label = cols[0].strip(), cols[-1].strip()
            if not label:
                continue
            status = 'running' if pid not in ('-', '') and pid.lstrip('-').isdigit() else 'stopped'
            services.append({'name': label, 'display_name': label, 'status': status})
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _parse_service_e(stdout: str) -> list:
        """Parse FreeBSD `service -e` (paths to enabled rc scripts)."""
        services = []
        for line in (stdout or '').splitlines():
            path = line.strip()
            if not path:
                continue
            name = path.rsplit('/', 1)[-1]
            services.append({'name': name, 'display_name': name, 'status': 'unknown'})
        return sorted(services, key=lambda x: x['name'].lower())

    @staticmethod
    def _discover_openrc() -> list:
        try:
            result = subprocess.run(
                ['rc-status', '--all', '--nocolor'],
                capture_output=True, text=True, timeout=10,
            )
            services, seen = [], set()
            for line in result.stdout.split('\n'):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith('Runlevel:') or stripped.startswith('Dynamic'):
                    continue
                if '[' not in stripped or ']' not in stripped:
                    continue
                name = stripped.split()[0]
                raw_st = stripped[stripped.index('[') + 1:stripped.index(']')].strip()
                status = 'running' if raw_st.lower() == 'started' else raw_st.lower()
                if name not in seen:
                    seen.add(name)
                    services.append({'name': name, 'display_name': name, 'status': status})
            return sorted(services, key=lambda x: x['name'].lower())
        except Exception:
            return []

    @staticmethod
    def _discover_sysv() -> list:
        try:
            init_dir = '/etc/init.d'
            if not os.path.isdir(init_dir):
                return []
            skip = {'README', 'functions', 'rc', 'rc.local', 'rcS', 'skeleton',
                    'halt', 'reboot', 'single', 'killprocs', 'sendsigs'}
            services = []
            for name in sorted(os.listdir(init_dir)):
                if name.startswith('.') or name in skip or name.startswith('_'):
                    continue
                path = os.path.join(init_dir, name)
                if not os.access(path, os.X_OK) or os.path.isdir(path):
                    continue
                services.append({'name': name, 'display_name': name, 'status': 'unknown'})
            return services
        except Exception:
            return []

    @staticmethod
    def _discover_windows() -> list:
        try:
            services = [
                {'name': svc.name(), 'display_name': svc.display_name(), 'status': svc.status()}
                for svc in psutil.win_service_iter()
            ]
            return sorted(services, key=lambda x: x['name'].lower())
        except Exception:
            return []

    @staticmethod
    def _clear_str(text: str) -> str:
        if text:
            return str(text).strip().replace("(", "").replace(")", "")
        return ''
