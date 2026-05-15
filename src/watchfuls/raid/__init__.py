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
"""Watchful to monitor RAID health (local mdstat and remote via SSH)."""

import concurrent.futures
import json
import os
import sys
from enum import IntEnum

from lib.debug import DebugLevel
from lib.linux import RaidMdstat
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class ConfigOptions(IntEnum):
    enabled  = 1
    host     = 100
    port     = 101
    user     = 102
    password = 103
    key_file = 104


class Watchful(ModuleBase):
    """Watchful module to monitor RAID health locally and on remote hosts via SSH."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
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
        if sys.platform != 'linux':
            return
        is_enable = self.get_conf("local", self._MODULE_DEFAULTS['local'])
        self._debug(f"Local - Enabled: {is_enable}", DebugLevel.info)
        if is_enable:
            list_md = RaidMdstat(self.paths.find('mdstat')).read_status()
            self._md_analyze(list_md)

    def _check_remote(self):
        list_remote = self._get_list_remote_enabled()
        if list_remote:
            self._check_remotes_run(list_remote)

    def _check_remotes_run(self, list_remote):
        threads = self.get_conf('threads', self._MODULE_DEFAULTS['threads'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            future_to_key = {
                executor.submit(self._check_remotes_process, key): key
                for key in list_remote
            }
            for future in concurrent.futures.as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    future.result()
                except Exception as exc: # pylint: disable=broad-except
                    label = self.get_label_by_id(key)
                    message = f'RAID: {label} - *Error: {exc}* 💥'
                    self.dict_return.set(key, False, message)
                    self._debug(f"{key}/{label} - Exception: {exc}", DebugLevel.error)

    def _check_remotes_process(self, key):
        host     = (self.get_conf_in_list("host",     key, '') or '').strip() or key
        port     = int(self.get_conf_in_list("port",     key, 0) or 22)
        user     = (self.get_conf_in_list("user",     key, '') or '').strip()
        password = (self.get_conf_in_list("password", key, '') or '').strip()
        key_file = (self.get_conf_in_list("key_file", key, '') or '').strip()
        timeout  = self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])

        list_md = RaidMdstat(host=host, port=port, user=user, password=password,
                             key_file=key_file, timeout=timeout).read_status()
        self._md_analyze(list_md, key)

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
                        other_data['finish']  = value.get("recovery", {}).get('finish',  -1)
                        other_data['speed']   = value.get("recovery", {}).get('speed',   -1)
                        message = (
                            f"*RAID {label}/{key} is degraded, recovery status "
                            f"{other_data['percent']}%, estimate time to finish "
                            f"{other_data['finish']}.* ⚠️"
                        )

                    case _:
                        message = f"*RAID {label}/{key} Unknown Error*. ⚠️"

                key_id = f"R_{remote_id}_{key}" if remote_id else f"L_{key}"
                self.dict_return.set(key_id, not is_warning, message, other_data=other_data)

    def _get_list_remote_enabled(self):
        result = []
        # Support old 'remote' key as fallback for existing configs
        items = self.get_conf('list', None)
        if items is None:
            items = self.get_conf('remote', {})
        for key, value in items.items():
            is_enabled = self._DEFAULTS['enabled']
            match value:
                case bool():
                    is_enabled = value
                case dict():
                    is_enabled = value.get('enabled', is_enabled)
                case _:
                    is_enabled = False
            self._debug(f"Remote/{key} - Enabled: {is_enabled}", DebugLevel.info)
            if is_enabled:
                result.append(key)
        return result

    def get_label_by_id(self, key) -> str:
        if key is None:
            return "Local"
        label = (self.get_conf_in_list("label", key, '') or '').strip()
        return label or key
