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

"""Watchful module to query UPS status via NUT (Network UPS Tools) TCP protocol."""

import concurrent.futures
import json
import os
import socket

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')


def _nut_query(host, port, ups_name, user, password, timeout):
    """Connect to NUT UPSD, authenticate if credentials given, query LIST VAR."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    f = sock.makefile('rw', encoding='utf-8', errors='replace')
    try:
        def _send(cmd):
            f.write(cmd + '\n')
            f.flush()

        def _recv():
            return f.readline().rstrip('\n')

        # Authenticate if credentials provided
        if user:
            _send(f'USERNAME {user}')
            r = _recv()
            if not r.startswith('OK'):
                raise ConnectionError(f'USERNAME rejected: {r}')
            _send(f'PASSWORD {password}')
            r = _recv()
            if not r.startswith('OK'):
                raise ConnectionError(f'PASSWORD rejected: {r}')

        _send(f'LIST VAR {ups_name}')
        variables = {}
        for line in f:
            line = line.rstrip('\n')
            if line.startswith(f'VAR {ups_name} '):
                # VAR upsname key "value"
                rest = line[len(f'VAR {ups_name} '):]
                key, _, val = rest.partition(' ')
                variables[key] = val.strip('"')
            elif line.startswith('END LIST VAR') or line.startswith('ERR'):
                if line.startswith('ERR'):
                    raise ConnectionError(f'NUT error: {line}')
                break

        _send('LOGOUT')
        return variables
    finally:
        try:
            f.close()
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            sock.close()
        except Exception:  # pylint: disable=broad-except
            pass


class Watchful(ModuleBase):
    """Watchful module to check UPS status via NUT UPSD TCP protocol."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("UPS: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, value) in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            host = (value.get('host', '') or '').strip()
            if not host:
                self._debug(f"UPS: {key} - host is empty, skipping.", DebugLevel.warning)
                continue
            port = int(value.get('port', 0) or 0) or 3493
            ups_name = (value.get('ups_name', '') or '').strip() or self._DEFAULTS['ups_name']
            user = (value.get('user', '') or '').strip()
            password = (value.get('password', '') or '').strip()
            timeout = int(value.get('timeout', 0) or 0) or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])
            self._debug(f"UPS: {key} - host={host}:{port} ups_name={ups_name}", DebugLevel.info)
            list_items.append({
                'key': key,
                'host': host,
                'port': port,
                'ups_name': ups_name,
                'user': user,
                'password': password,
                'timeout': timeout,
            })

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_item = {
                executor.submit(self._ups_check, item): item
                for item in list_items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"UPS: {item['key']} - Exception: {exc}", DebugLevel.error)
                    message = f'UPS: {item["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    def _ups_check(self, item):
        key = item['key']
        host = item['host']
        ups_name = item['ups_name']

        variables = _nut_query(
            host=host,
            port=item['port'],
            ups_name=ups_name,
            user=item['user'],
            password=item['password'],
            timeout=item['timeout'],
        )

        status = variables.get('ups.status', '')
        # "OL" = on-line, "OB" = on battery, "LB" = low battery
        ok = 'OL' in status and 'LB' not in status

        if ok:
            message = f'UPS: *{key}* - Online ({status}) ✅'
        elif 'LB' in status:
            message = f'UPS: *{key}* - LOW BATTERY ({status}) ⚠️'
        elif 'OB' in status:
            message = f'UPS: *{key}* - On battery ({status}) ⚠️'
        else:
            message = f'UPS: *{key}* - Status: {status or "unknown"} ⚠️'

        other_data = {
            'host': host,
            'ups_name': ups_name,
            'status': status,
            'battery_charge': variables.get('battery.charge'),
            'runtime': variables.get('battery.runtime'),
            'load': variables.get('ups.load'),
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)
