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
import json
import os
import socket

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class Watchful(ModuleBase):

    _DEFAULT_ALERT = 50
    _DEFAULT_TIMEOUT = 5

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: (list(v['default']) if isinstance(v['default'], list) else v['default'])
                 for k, v in _SCHEMA['list'].items()}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        list_hosts = self._check_get_list_hosts()
        self._check_run(list_hosts)
        super().check()
        return self.dict_return

    def _check_get_list_hosts(self):
        return_list = []
        for (key, value) in self.get_conf('list', {}).items():
            is_enabled = self._DEFAULTS['enabled']
            match value:
                case bool():
                    is_enabled = value
                case dict():
                    is_enabled = value.get("enabled", is_enabled)

            self._debug(f"{key} - Enabled: {is_enabled}", DebugLevel.info)
            if is_enabled:
                if not isinstance(value, dict) or not value.get("host", None):
                    self._debug(f"{key} - Host is not defined!", DebugLevel.warning)
                else:
                    new_hddtemp = self.Hddtemp_Info(key)
                    new_hddtemp.host = value.get("host")
                    new_hddtemp.port = value.get("port", self._DEFAULTS['port'])
                    new_hddtemp.alert = self.get_conf('alert', self._DEFAULT_ALERT)
                    new_hddtemp.exclude = value.get("exclude", [])
                    return_list.append(new_hddtemp)

        return return_list

    def _check_run(self, list_hosts):
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_hddtemp = {executor.submit(self._hddtemp_check, hddtemp): hddtemp for hddtemp in list_hosts}
            for future in concurrent.futures.as_completed(future_to_hddtemp):
                hddtemp = future_to_hddtemp[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'HDD: {hddtemp.label} - *Error: {exc}* 💥'
                    self.dict_return.set(hddtemp.label, False, message)

    def _hddtemp_check(self, hddtemp):
        if self._hddtemp_return(hddtemp):
            for (key, value) in hddtemp.list_hdd.items():
                if key not in hddtemp.exclude:
                    hdd_name = hddtemp.label + '_' + key
                    hdd_dev = key
                    hdd_alert = value['ALERT']
                    hdd_temp = value['TEMP']
                    hdd_unit = value['TEMP_UNIT']

                    if isinstance(hdd_temp, int):
                        status = hdd_alert >= hdd_temp
                        s_message = f'({hddtemp.label}): *{hdd_dev}* *({hdd_temp}º{hdd_unit})*'
                        if status:
                            s_message += '🔼'
                        else:
                            s_message += '🔽'
                    else:
                        status = False
                        s_message = f'({hddtemp.label}): *{hdd_dev}* *({hdd_temp})* 🔥🔥'

                    other_data = value
                    self.dict_return.set(hdd_name, status, s_message, False, other_data)

                    if self.check_status(status, self.name_module, hdd_name):
                        self.send_message(s_message, status)

        else:
            self._debug(f"{hddtemp.label} >> Exception: {hddtemp.error}", DebugLevel.warning)
            s_message = f'HddTemp: {hddtemp.label} - *Error:* *{hddtemp.error}*'
            s_message += '🔽'

            other_data = {'message': str(hddtemp.error)}
            self.dict_return.set(hddtemp.label, False, s_message, False, other_data)

            if self.check_status_custom(False, hddtemp.label, hddtemp.error):
                self.send_message(s_message, False)

    def _hddtemp_return(self, hddtemp):
        timeout = self.get_conf('timeout', self._DEFAULT_TIMEOUT)
        try:
            with socket.create_connection(
                (hddtemp.host, hddtemp.port),
                timeout=timeout if timeout > 0 else None
            ) as sock:
                data = b''
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            read_all = data.decode('ascii')

        except Exception as exc:
            hddtemp.error = exc
            return False

        list_hdd = read_all.split("||")
        for value in list_hdd:
            item_hdd = str(value).split("|")
            # Remove items None.
            item_hdd = list(filter(None, item_hdd))
            if len(item_hdd) < 4:
                continue

            new_hdd = {
                'DEV': str(item_hdd[0]).strip(),
                'MODEL': str(item_hdd[1]).strip(),
                'TEMP': int(item_hdd[2]) if item_hdd[2].lstrip('-').isnumeric() else str(item_hdd[2]).strip(),
                'TEMP_UNIT': str(item_hdd[3]).strip(),
                'ALERT': int(hddtemp.alert)
            }
            hddtemp.list_hdd[new_hdd['DEV']] = new_hdd
        return True

    class Hddtemp_Info:

        def __init__(self, label):
            self.label = label
            self.host = ""
            self.port = 0
            self.alert = 0
            self.exclude = []
            self.list_hdd = {}
            self.error = ""
