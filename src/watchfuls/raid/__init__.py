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
import json
import os
from enum import IntEnum

from lib.debug import DebugLevel
from lib.linux import RaidMdstat
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class ConfigOptions(IntEnum):
    enabled = 1
    # alert = 2
    label = 3
    host = 100
    port = 101
    user = 102
    password = 103
    key_file = 104


class Watchful(ModuleBase):

    _DEFAULT_TIMEOUT = 30

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['remote'].items()
                 if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)
        self.paths.set('mdstat', '/proc/mdstat')

    def check(self):
        self._check_local()
        self._check_remote()
        super().check()
        return self.dict_return

    def _check_local(self):
        is_enable = self.get_conf("local", self._DEFAULTS['enabled'])
        self._debug(f"Local - Enabled: {is_enable}", DebugLevel.info)
        if is_enable:
            list_md = RaidMdstat(self.paths.find('mdstat')).read_status()
            self._md_analyze(list_md)

    def _check_remote(self):
        list_remote = self._get_list_remote_enable()
        if len(list_remote) > 0:
            self._check_remotes_run(list_remote)

    def _check_remotes_run(self, list_remote):
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.conf_threads) as executor:
            future_to_remote_id = {executor.submit(self._check_remotes_process, remote_id): remote_id for remote_id in list_remote}
            for future in concurrent.futures.as_completed(future_to_remote_id):
                remote_id = future_to_remote_id[future]
                try:
                    future.result()
                except Exception as exc:
                    tmp_label = self.get_label_by_id(remote_id)
                    message = f'RAID: {tmp_label} - *Error: {exc}* 💥'
                    self.dict_return.set(remote_id, False, message)
                    self._debug(f"{remote_id}/{tmp_label} - Exception: {exc}", DebugLevel.error)

    def _check_remotes_process(self, remote_id):
        tmp_host = self.get_conf_item(ConfigOptions.host, remote_id)
        tmp_port = self.get_conf_item(ConfigOptions.port, remote_id)
        tmp_user = self.get_conf_item(ConfigOptions.user, remote_id)
        tmp_pass = self.get_conf_item(ConfigOptions.password, remote_id)
        tmp_key = self.get_conf_item(ConfigOptions.key_file, remote_id)

        list_md = RaidMdstat(host=tmp_host, port=tmp_port, user=tmp_user, password=tmp_pass,
                             key_file=tmp_key, timeout=self.conf_timeout).read_status()
        self._md_analyze(list_md, remote_id)

    def _md_analyze(self, list_md, remote_id=None):

        label = self.get_label_by_id(remote_id)

        if len(list_md) == 0:
            message = f"[{label}] *No RAID's* in the system. ✅"
            key_id = f"R_{remote_id}" if remote_id else "L"
            self.dict_return.set(key_id, True, message)

        else:
            for (key, value) in list_md.items():
                other_data = {}
                is_warning = True
                match value.get("update", ''):
                    case RaidMdstat.UpdateStatus.ok:
                        is_warning = False
                        message = f"RAID *{label}/{key}* in good status. ✅"

                    case RaidMdstat.UpdateStatus.error:
                        message = f"*RAID {label}/{key} is degraded.* ⚠️"

                    case RaidMdstat.UpdateStatus.recovery:
                        other_data['percent'] = value.get("recovery", {}).get('percent', -1)
                        other_data['finish'] = value.get("recovery", {}).get('finish', -1)
                        other_data['speed'] = value.get("recovery", {}).get('speed', -1)

                        message = f"*RAID {label}/{key} is degraded, recovery status {other_data['percent']}%, estimate time to finish {other_data['finish']}.* ⚠️"

                    case _:
                        message = f"*RAID {label}/{key} Unknown Error*. ⚠️"

                if remote_id:
                    key_id = f"R_{remote_id}_{key}"
                else:
                    key_id = f"L_{key}"
                self.dict_return.set(key_id, not is_warning, message, other_data=other_data)

    def _get_list_remote_enable(self):
        return_list = []
        for (key, value) in self.get_conf('remote', {}).items():
            if not str(key).isnumeric():
                continue

            if isinstance(value, dict):
                is_enabled = self.get_conf_item(ConfigOptions.enabled, key)
            else:
                is_enabled = self._DEFAULTS['enabled']
            self._debug(f"Remote/{key} - Enabled: {is_enabled}", DebugLevel.info)
            if is_enabled:
                return_list.append(key)

        return return_list

    def get_conf_item(self, opt_find: IntEnum, dev_name: str, default_val=None):
        # Sec - Set Default Val
        if default_val is None:
            match opt_find:
                case ConfigOptions.port:
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS['port'])

                case (ConfigOptions.label | ConfigOptions.host
                      | ConfigOptions.user | ConfigOptions.password
                      | ConfigOptions.key_file):
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS.get(opt_find.name, ''))

                case ConfigOptions.enabled:
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS['enabled'])

                case None:
                    raise ValueError("opt_find it can not be None!")
                case _:
                    raise TypeError(f"{opt_find.name} is not valid option!")
        else:
            val_def = default_val

        # Sec - Get Data config
        value = self.get_conf_in_list(opt_find, dev_name, val_def, key_name_list="remote")

        # Sec - Format Return Data
        match opt_find:
            case ConfigOptions.port:
                return self._parse_conf_int(value, val_def)
            case ConfigOptions.enabled:
                return bool(value)
            case (ConfigOptions.label | ConfigOptions.host
                  | ConfigOptions.user | ConfigOptions.password
                  | ConfigOptions.key_file):
                return self._parse_conf_str(value, val_def)
            case _:
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
        return self.get_conf('timeout', self._DEFAULT_TIMEOUT)

    @property
    def conf_threads(self) -> int:
        return self.get_conf('threads', self._default_threads)
