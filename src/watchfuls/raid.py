#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Javier Pastor (aka vsc55)
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
from lib import Switch
from lib.debug import DebugLevel
from lib.modules import ModuleBase
from lib.linux import RaidMdstat
from enum import Enum


class ConfigOptions(Enum):
    enabled = 1
    # alert = 2
    label = 3
    host = 100
    port = 101
    user = 102
    password = 103


class Watchful(ModuleBase):

    __default_enabled = True
    __default_port = 22
    __default_timeout = 30

    def __init__(self, monitor):
        super().__init__(monitor, __name__)
        self.paths.set('mdstat', '/proc/mdstat')

    def check(self):
        self.__check_local()
        self.__check_remote()
        super().check()
        return self.dict_return

    def __check_local(self):
        is_enable = self.get_conf("local", self.__default_enabled)
        self._debug(f"Local - Enabled: {is_enable}", DebugLevel.info)
        if is_enable:
            list_md = RaidMdstat(self.paths.find('mdstat')).read_status()
            self.__md_analyze(list_md)

    def __check_remote(self):
        list_remote = self.__get_list_remote_enable()
        if len(list_remote) > 0:
            self.__check_remotes_run(list_remote)

    def __check_remotes_run(self, list_remote):
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.conf_threads) as executor:
            future_to_remote_id = {executor.submit(self.__check_remotes_process, remote_id): remote_id for remote_id in list_remote}
            for future in concurrent.futures.as_completed(future_to_remote_id):
                remote_id = future_to_remote_id[future]
                try:
                    future.result()
                except Exception as exc:
                    tmp_label = self.get_label_by_id(remote_id)
                    message = f'RAID: {tmp_label} - *Error: {exc}* {u"\U0001F4A5"}'
                    self.dict_return.set(remote_id, False, message)
                    self._debug(f"{remote_id}/{tmp_label} - Exception: {exc}", DebugLevel.error)
                    # self.debug.exception(exc)

    def __check_remotes_process(self, remote_id):
        tmp_host = self.get_conf_item(ConfigOptions.host, remote_id)
        tmp_port = self.get_conf_item(ConfigOptions.port, remote_id)
        tmp_user = self.get_conf_item(ConfigOptions.user, remote_id)
        tmp_pass = self.get_conf_item(ConfigOptions.password, remote_id)

        list_md = RaidMdstat(host=tmp_host, port=tmp_port, user=tmp_user, password=tmp_pass,
                             timeout=self.conf_timeout).read_status()
        self.__md_analyze(list_md, remote_id)

    def __md_analyze(self, list_md, remote_id=None):

        label = self.get_label_by_id(remote_id)

        if len(list_md) == 0:
            message = f"[{label}] *No RAID's* in the system. {u'\U00002705'}"
            key_id = f"R_{remote_id}" if remote_id else "L"
            self.dict_return.set(key_id, True, message)

        else:
            for (key, value) in list_md.items():
                # print("key:", key, " - Val:", value)

                other_data = {}
                is_warning = True
                with Switch(value.get("update", '')) as case:
                    if case(RaidMdstat.UpdateStatus.ok):
                        is_warning = False
                        message = f"RAID *{label}/{key}* in good status. {u'\U00002705'}"

                    elif case(RaidMdstat.UpdateStatus.error):
                        message = f"*RAID {label}/{key} is degraded.* {u'\U000026A0'}"

                    elif case(RaidMdstat.UpdateStatus.recovery):
                        other_data['percent'] = value.get("recovery", {}).get('percent', -1)
                        other_data['finish'] = value.get("recovery", {}).get('finish', -1)
                        other_data['speed'] = value.get("recovery", {}).get('speed', -1)

                        message = f"*RAID {label}/{key} is degraded, recovery status {other_data['percent']}%, estimate time to finish {other_data['finish']}.* {u'\U000026A0'}"

                    else:
                        message = f"*RAID {label}/{key} Unknown Error*. {u'\U000026A0'}"

                if remote_id:
                    key_id = f"R_{remote_id}_{key}"
                else:
                    key_id = f"L_{key}"
                self.dict_return.set(key_id, not is_warning, message, other_data=other_data)

    def __get_list_remote_enable(self):
        return_list = []
        for (key, value) in self.get_conf('remote', {}).items():
            if not str(key).isnumeric():
                continue

            if isinstance(value, dict):
                is_enabled = self.get_conf_item(ConfigOptions.enabled, key)
            else:
                is_enabled = self.__default_enabled

            self._debug(f"Remote/{key} - Enabled: {is_enabled}", DebugLevel.info)
            if is_enabled:
                return_list.append(key)

        return return_list

    def get_conf_item(self, opt_find: Enum, dev_name: str, default_val=None):
        # Sec - Set Default Val
        if default_val is None:
            with Switch(opt_find) as case:
                if case(ConfigOptions.port):
                    val_def = self.get_conf(opt_find.name, self.__default_port)

                elif case(ConfigOptions.label,
                          ConfigOptions.host,
                          ConfigOptions.user,
                          ConfigOptions.password):
                    val_def = self.get_conf(opt_find.name, "")

                elif case(ConfigOptions.enabled):
                    val_def = self.get_conf(opt_find.name, self.__default_enabled)

                else:
                    if opt_find is None:
                        raise ValueError("opt_find it can not be None!")
                    else:
                        raise TypeError(f"{opt_find.name} is not valid option!")
        else:
            val_def = default_val

        # Sec - Get Data config
        value = self.get_conf_in_list(opt_find, dev_name, val_def, key_name_list="remote")

        # Sec - Format Return Data
        with Switch(opt_find) as case:
            if case(ConfigOptions.port):
                return self._parse_conf_int(value, val_def)
            elif case(ConfigOptions.enabled):
                return bool(value)
            elif case(ConfigOptions.label,
                      ConfigOptions.host,
                      ConfigOptions.user,
                      ConfigOptions.password):
                return self._parse_conf_str(value, val_def)
            else:
                return value

    def get_label_by_id(self, remote_id) -> str:
        label = ""
        if remote_id:
            label = self.get_conf_item(ConfigOptions.label, remote_id)
            if not label:
                label = f"Remote{remote_id}"
        else:
            label = "Local"
        return label

    @property
    def conf_timeout(self) -> float:
        return self.get_conf('timeout', self.__default_timeout)

    @property
    def conf_threads(self) -> int:
        return self.get_conf('threads', self._default_threads)
