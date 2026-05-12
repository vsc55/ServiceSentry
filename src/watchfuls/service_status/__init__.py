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

import concurrent.futures
import json
import os
import platform
import shutil
import subprocess

import psutil

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


def _detect_linux_init() -> str:
    if os.path.exists('/run/systemd/system'):
        return 'systemd'
    if shutil.which('rc-service'):
        return 'openrc'
    return 'sysv'


class Watchful(ModuleBase):

    ITEM_SCHEMA = _SCHEMA
    _PLATFORM: str = platform.system().lower()
    _INIT_SYSTEM: str = _detect_linux_init() if platform.system().lower() == 'linux' else 'systemd'

    def __init__(self, monitor):
        super().__init__(monitor, __package__)
        if self._PLATFORM == 'windows':
            self.paths.set('sc', 'sc')
        elif self._INIT_SYSTEM == 'openrc':
            self.paths.set('rc-service', shutil.which('rc-service') or 'rc-service')
        elif self._INIT_SYSTEM == 'sysv':
            self.paths.set('service', shutil.which('service') or 'service')
        else:  # systemd
            self.paths.set('systemctl', '/bin/systemctl')

    def check(self):
        list_service = []
        for (key, value) in self.get_conf('list', {}).items():
            enabled = str(value.get('enabled', '')).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            remediation = str(value.get('remediation', '')).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            service_name = (value.get('service', '') or '').strip() or key
            expected = (value.get('expected', '') or 'running').strip().lower()
            if expected not in ('running', 'stopped'):
                expected = 'running'
            self._debug(f"Service: {key} - Enabled: {enabled} - Expected: {expected} - Remediation: {remediation}", DebugLevel.info)
            if enabled:
                list_service.append({"key": key, "service": service_name, "remediation": remediation, "expected": expected})

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_service = {executor.submit(self._service_check, service): service for service in list_service}
            for future in concurrent.futures.as_completed(future_to_service):
                service = future_to_service[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'Service: {service["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(service['key'], False, message)

        super().check()
        return self.dict_return

    def _service_check(self, service):
        remediation_use = None
        display_name = service['key']
        service_name = service['service']
        expected = service.get('expected', 'running')
        status, error, message = self._service_return(service_name)

        ok = status if expected == 'running' else not status

        s_message = f'Service: {display_name} '
        if ok:
            state_word = 'Running' if status else 'Stopped'
            s_message += f' - *{state_word}* ✅'
        else:
            if error and message:
                s_message += f'- *Error: {message}* '
            elif status:
                s_message += '- *Running (expected: Stopped)* '
            else:
                s_message += '- *Stop* '
            s_message += '⚠️'

        if self.check_status(ok, self.name_module, display_name):
            self.send_message(s_message, ok)
            if not ok and service['remediation']:
                self._service_remediation(service_name, expected)
                status, error, message = self._service_return(service_name)
                ok = status if expected == 'running' else not status

                s_message = f'*Recovery* Service: {display_name} '
                if ok:
                    remediation_use = True
                    s_message += ' - *OK* ✅'
                else:
                    remediation_use = False
                    if error and message:
                        s_message += f'- *Error: {message}* '
                    elif status:
                        s_message += '- *Running (expected: Stopped)* '
                    else:
                        s_message += '- *UNSUCCESSFUL* '
                    s_message += '⚠️'

                self.send_message(s_message, ok)

        other_data = {'error': error, 'status_detail': message, 'remediation': remediation_use}
        self.dict_return.set(display_name, ok, s_message, False, other_data)

    def _service_return(self, service_name):
        if self._PLATFORM == 'windows':
            return self._service_return_windows(service_name)
        return self._service_return_linux(service_name)

    def _service_return_linux(self, service_name):
        if self._INIT_SYSTEM == 'openrc':
            return self._service_return_openrc(service_name)
        if self._INIT_SYSTEM == 'sysv':
            return self._service_return_sysv(service_name)
        return self._service_return_systemd(service_name)

    def _service_return_systemd(self, service_name):
        cmd = f'{self.paths.find("systemctl")} status {service_name}'
        stdout, stderr = self._run_cmd(cmd, True)
        if not stdout:
            return False, True, (stderr[:-1] if stderr else '')

        for line in stdout.split('\n'):
            s_line = line.split()
            if not s_line:
                continue
            if str(s_line[0]) == 'Active:':
                if str(s_line[1]) == "active":
                    if str(s_line[2]) == "(running)":
                        return True, False, self._clear_str(s_line[2])
                    else:
                        return False, False, self._clear_str(s_line[2])
                elif str(s_line[1]) == "inactive":
                    if str(s_line[2]) == "(dead)":
                        return False, False, ''
                    else:
                        return False, False, self._clear_str(s_line[2])
                else:
                    return False, True, line

        return False, False, 'Not detect status in the data!!!'

    def _service_return_openrc(self, service_name):
        cmd = f'{self.paths.find("rc-service")} {service_name} status'
        stdout, stderr, exit_code = self._run_cmd(cmd, return_str_err=True, return_exit_code=True)
        if exit_code == 0:
            return True, False, 'running'
        combined = (stdout + stderr).strip()
        error = 'does not exist' in combined.lower()
        return False, error, combined if error else 'stopped'

    def _service_return_sysv(self, service_name):
        cmd = f'{self.paths.find("service")} {service_name} status'
        stdout, stderr, exit_code = self._run_cmd(cmd, return_str_err=True, return_exit_code=True)
        if exit_code == 0:
            return True, False, 'running'
        combined = (stdout + stderr).strip()
        error = not combined
        return False, error, combined if combined else f'{service_name}: service not found'

    def _service_return_windows(self, service_name):
        try:
            svc = psutil.win_service_get(service_name)
            st = svc.status()
            return st == 'running', False, st
        except Exception as exc:
            return False, True, str(exc)

    def _service_remediation(self, service_name, expected='running'):
        action = 'stop' if expected == 'stopped' else 'start'
        if self._PLATFORM == 'windows':
            cmd = f'{self.paths.find("sc")} {action} {service_name}'
        elif self._INIT_SYSTEM == 'openrc':
            cmd = f'{self.paths.find("rc-service")} {service_name} {action}'
        elif self._INIT_SYSTEM == 'sysv':
            cmd = f'{self.paths.find("service")} {service_name} {action}'
        else:  # systemd
            cmd = f'{self.paths.find("systemctl")} {action} {service_name}'
        self._run_cmd(cmd)

    @classmethod
    def discover(cls) -> list:
        """Return [{name, display_name, status}] for all system services."""
        if cls._PLATFORM == 'windows':
            return cls._discover_windows()
        if cls._INIT_SYSTEM == 'openrc':
            return cls._discover_openrc()
        if cls._INIT_SYSTEM == 'sysv':
            return cls._discover_sysv()
        return cls._discover_systemd()

    @staticmethod
    def _discover_systemd() -> list:
        try:
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--all',
                 '--no-pager', '--no-legend', '--plain'],
                capture_output=True, text=True, timeout=10,
            )
            services = []
            for line in result.stdout.split('\n'):
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
        except Exception:
            return []

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
