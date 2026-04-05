#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
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

from lib.debug import DebugLevel
from lib.modules import ModuleBase


class Watchful(ModuleBase):

    ITEM_SCHEMA = {
        'list': {
            'enabled': True,
            'remediation': False,
        },
    }

    def __init__(self, monitor):
        super().__init__(monitor, __name__)
        self.paths.set('systemctl', '/bin/systemctl')

    def check(self):
        list_service = []
        for (key, value) in self.get_conf('list', {}).items():
            enabled = str(value.get('enabled', '')).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            remediation = str(value.get('remediation', '')).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            self._debug(f"Service: {key} - Enabled: {enabled} - Remediation: {remediation}", DebugLevel.info)
            if enabled:
                list_service.append({"service": key, "remediation": remediation})

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_service = {executor.submit(self._service_check, service): service for service in list_service}
            for future in concurrent.futures.as_completed(future_to_service):
                service = future_to_service[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'Service: {service} - *Error: {exc}* {u"\U0001F4A5"}'
                    self.dict_return.set(service, False, message)

        super().check()
        return self.dict_return

    def _service_check(self, service):
        remediation_use = None
        service_name = service['service']
        status, error, message = self._service_return(service_name)

        s_message = f'Service: {service_name} '
        if status:
            s_message += ' - *Running* ' + u'\U00002705'
        else:
            if message:
                s_message += f'- *Error: {message}* '
            else:
                s_message += '- *Stop* '
            s_message += u'\U000026A0'

        # Solo se ejecuta la primera vez, cuando cambia de estado.
        if self.check_status(status, self.name_module, service_name):
            self.send_message(s_message, status)
            if not status and service['remediation']:
                self._service_remediation(service_name)
                status, error, message = self._service_return(service_name)

                s_message = f'*Recovery* Service: {service_name} '
                if status:
                    remediation_use = True
                    s_message += ' - *OK* ' + u'\U00002705'
                else:
                    remediation_use = False
                    if message:
                        s_message += f'- *Error: {message}* '
                    else:
                        s_message += '- *UNSUCCESSFUL* '
                    s_message += u'\U000026A0'

                self.send_message(s_message, status)

        other_data = {'error': error, 'status_detail': message, 'remediation': remediation_use}
        self.dict_return.set(service_name, status, s_message, False, other_data)

    def _service_remediation(self, service_name):
        cmd = f'{self.paths.find("systemctl")} start {service_name}'
        self._run_cmd(cmd)

    def _service_return(self, service_name):
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
                    #    Active: active (running) since Mon 2019-05-27 11:28:46 CEST; 1min 48s ago
                    if str(s_line[2]) == "(running)":
                        return True, False, self._clear_str(s_line[2])
                    else:
                        return False, False, self._clear_str(s_line[2])
                elif str(s_line[1]) == "inactive":
                    #    Active: inactive (dead) since Mon 2019-05-27 11:30:51 CEST; 1s ago
                    if str(s_line[2]) == "(dead)":
                        return False, False, ''
                    else:
                        return False, False, self._clear_str(s_line[2])
                else:
                    return False, True, line

        return False, False, 'Not detect status in the data!!!'

    @staticmethod
    def _clear_str(text: str) -> str:
        if text:
            return str(text).strip().replace("(", "").replace(")", "")
        return ''
