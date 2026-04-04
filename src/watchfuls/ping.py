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
import time
from enum import IntEnum

from lib.debug import DebugLevel
from lib.modules import ModuleBase


class ConfigOptions(IntEnum):
    enabled = 1
    # alert = 2
    label = 3
    timeout = 100
    attempt = 101


class Watchful(ModuleBase):

    _default_attempt = 3
    _default_timeout = 5
    _default_enabled = True

    def __init__(self, monitor):
        super().__init__(monitor, __name__)
        self.paths.set('ping', '/bin/ping')

    def check(self):
        list_host = self._check_get_list_hosts()
        self._check_run(list_host)
        super().check()
        return self.dict_return

    def _check_get_list_hosts(self):
        return_list = []
        for (key, value) in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                is_enabled = value
            elif isinstance(value, dict):
                is_enabled = self._get_conf(ConfigOptions.enabled, key)
            else:
                is_enabled = self._default_enabled

            self._debug(f"Ping: {key} - Enabled: {is_enabled}", DebugLevel.info)

            if is_enabled:
                return_list.append(key)

        return return_list

    def _check_run(self, list_host):
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_ping = {executor.submit(self._ping_check, host): host for host in list_host}
            for future in concurrent.futures.as_completed(future_to_ping):
                host = future_to_ping[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'Ping: {host} - *Error: {exc}* {u"\U0001F4A5"}'
                    self.dict_return.set(host, False, message)

    def _ping_check(self, host):
        # TODO: Pendiente poder configurar número de intentos y timeout para cada IP

        tmp_host_name = self._get_conf(ConfigOptions.label, host, host)
        tmp_timeout = self._get_conf(ConfigOptions.timeout, host)
        tmp_attempt = self._get_conf(ConfigOptions.attempt, host)

        status = self._ping_return(host, tmp_timeout, tmp_attempt)

        s_message = f'Ping: *{tmp_host_name}* '
        if status:
            s_message += u'\U0001F53C'
        else:
            s_message += u'\U0001F53D'

        self.dict_return.set(host, status, s_message, False)

        if self.check_status(status, self.name_module, host):
            self.send_message(s_message, status)

    def _ping_return(self, host, timeout, attempt):
        counter = 0
        while counter < attempt:
            cmd = f'{self.paths.find("ping")} -c 1 -W {timeout} {host}'
            _, r_code = self._run_cmd(cmd, return_exit_code=True)
            if r_code == 0:
                return True
            time.sleep(1)
            counter += 1
        return False

    def _get_conf(self, opt_find: IntEnum, dev_name: str, default_val=None):
        # Sec - Get Default Val
        if default_val is None:
            match opt_find:
                case ConfigOptions.attempt:
                    val_def = self.get_conf(opt_find.name, self._default_attempt)

                case ConfigOptions.timeout:
                    val_def = self.get_conf(opt_find.name, self._default_timeout)

                case ConfigOptions.enabled:
                    val_def = self.get_conf(opt_find.name, self._default_enabled)

                case None:
                    raise ValueError("opt_find it can not be None!")
                case _:
                    raise TypeError(f"{opt_find.name} is not valid option!")
        else:
            val_def = default_val

        # Sec - Get Data
        value = self.get_conf_in_list(opt_find, dev_name, val_def)

        # Sec - Format Return Data
        match opt_find:
            case ConfigOptions.attempt | ConfigOptions.timeout:
                return self._parse_conf_int(value, val_def)
            case ConfigOptions.enabled:
                return bool(value)
            case ConfigOptions.label:
                return self._parse_conf_str(value, val_def)
            case _:
                return value
