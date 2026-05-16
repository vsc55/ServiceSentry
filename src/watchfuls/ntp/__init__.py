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

"""Watchful module to check NTP time offset using raw UDP (no external libs)."""

import concurrent.futures
import json
import os
import socket
import struct
import time

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')

# Seconds between 1900-01-01 (NTP epoch) and 1970-01-01 (Unix epoch).
NTP_DELTA = 2208988800


def _ntp_query(server: str, timeout: float, port: int = 123) -> tuple:
    """Return (abs_offset_seconds, delay_seconds). Raises on error."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        packet = b'\x1b' + 47 * b'\x00'  # LI=0, VN=3, Mode=3 (client)
        t1 = time.time()
        sock.sendto(packet, (server, port))
        data, _ = sock.recvfrom(1024)
        t4 = time.time()
        if len(data) < 48:
            raise ValueError(f"NTP response too short ({len(data)} bytes)")
        # Receive timestamp T2 (bytes 32-39), Transmit timestamp T3 (bytes 40-47)
        t2_s, t2_f = struct.unpack('!II', data[32:40])
        t3_s, t3_f = struct.unpack('!II', data[40:48])
        t2 = (t2_s - NTP_DELTA) + t2_f / 2**32
        t3 = (t3_s - NTP_DELTA) + t3_f / 2**32
        offset = abs(((t2 - t1) + (t3 - t4)) / 2)
        delay = (t4 - t1) - (t3 - t2)
        return offset, delay
    finally:
        sock.close()


class Watchful(ModuleBase):
    """Watchful module to check NTP time offset via raw UDP."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("NTP: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, value) in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            server = (value.get('server', '') or '').strip() or self._DEFAULTS['server']
            port = int(value.get('port', 0) or 0) or 123
            max_offset = float(value.get('max_offset', 0) or 0) or self.get_conf('max_offset', self._MODULE_DEFAULTS['max_offset'])
            timeout = int(value.get('timeout', 0) or 0) or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])
            self._debug(f"NTP: {key} - server={server}:{port} max_offset={max_offset}", DebugLevel.info)
            list_items.append({
                'key': key,
                'server': server,
                'port': port,
                'max_offset': max_offset,
                'timeout': timeout,
            })

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_item = {
                executor.submit(self._ntp_check, item): item
                for item in list_items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"NTP: {item['key']} - Exception: {exc}", DebugLevel.error)
                    message = f'NTP: {item["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    def _ntp_check(self, item):
        key = item['key']
        server = item['server']
        max_offset = item['max_offset']
        timeout = item['timeout']

        offset, delay = _ntp_query(server, timeout, item['port'])
        ok = offset < max_offset

        if ok:
            message = f'NTP: *{key}* - offset {offset:.3f}s (max {max_offset}s) ✅'
        else:
            message = f'NTP: *{key}* - offset {offset:.3f}s exceeds {max_offset}s ⚠️'

        other_data = {
            'server': server,
            'port': item['port'],
            'offset_seconds': round(offset, 3),
            'delay_seconds': round(delay, 3),
            'max_offset': max_offset,
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)
