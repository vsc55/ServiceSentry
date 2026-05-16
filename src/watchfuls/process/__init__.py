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

"""Watchful module to check if processes are running by name."""

import concurrent.futures
import json
import os

import psutil

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')


class Watchful(ModuleBase):

    WATCHFUL_ACTIONS: frozenset = frozenset({'discover'})
    """Watchful module to check if processes are running by name via psutil."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("Process: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, value) in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            process = (value.get('process', '') or '').strip() or key
            module_min_count = int(self.get_conf('min_count', self._MODULE_DEFAULTS.get('min_count', 1)) or 1)
            min_count = int(value.get('min_count', 0) or 0) or module_min_count
            self._debug(f"Process: {key} - process={process} min_count={min_count}", DebugLevel.info)
            list_items.append({
                'key': key,
                'process': process,
                'min_count': min_count,
            })

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_item = {
                executor.submit(self._process_check, item): item
                for item in list_items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"Process: {item['key']} - Exception: {exc}", DebugLevel.error)
                    message = f'Process: {item["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    @classmethod
    def discover(cls) -> list:
        """Return running processes sorted by name with instance counts."""
        try:
            counts: dict[str, int] = {}
            for p in psutil.process_iter(['name']):
                name = (p.info.get('name') or '').strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
            return sorted(
                [{'name': n, 'display_name': n, 'status': f'×{c}'} for n, c in counts.items()],
                key=lambda x: x['name'].lower()
            )
        except Exception:  # pylint: disable=broad-except
            return []

    def _process_check(self, item):
        key = item['key']
        process_name = item['process']
        min_count = item['min_count']

        count = sum(
            1 for p in psutil.process_iter(['name'])
            if (p.info.get('name') or '').lower() == process_name.lower()
        )
        ok = count >= min_count

        if ok:
            message = f'Process: *{key}* - {count} instance(s) running ✅'
        else:
            message = f'Process: *{key}* - found {count}/{min_count} instance(s) ⚠️'

        other_data = {
            'process': process_name,
            'count': count,
            'min_count': min_count,
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)
