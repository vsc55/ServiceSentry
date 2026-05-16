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

"""Watchful module to check SSL/TLS certificate expiry."""

import concurrent.futures
import json
import os
import socket
import ssl
import time

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')


class Watchful(ModuleBase):
    """Watchful module to check SSL/TLS certificate expiry."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("SSL Cert: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, value) in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            host = (value.get('host', '') or '').strip() or key
            port = int(value.get('port', 0) or 0) or 443
            warning_days = int(value.get('warning_days', 0) or 0) or self.get_conf('warning_days', self._MODULE_DEFAULTS['warning_days'])
            timeout = int(value.get('timeout', 0) or 0) or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])
            self._debug(f"SSL Cert: {key} - host={host}:{port} warning_days={warning_days}", DebugLevel.info)
            list_items.append({
                'key': key,
                'host': host,
                'port': port,
                'warning_days': warning_days,
                'timeout': timeout,
            })

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_item = {
                executor.submit(self._ssl_check, item): item
                for item in list_items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"SSL Cert: {item['key']} - Exception: {exc}", DebugLevel.error)
                    message = f'SSL Cert: {item["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    def _ssl_check(self, item):
        key = item['key']
        host = item['host']
        port = item['port']
        warning_days = item['warning_days']
        timeout = item['timeout']

        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()

        expiry_ts = ssl.cert_time_to_seconds(cert['notAfter'])
        days_left = (expiry_ts - time.time()) / 86400
        ok = days_left > warning_days

        if ok:
            message = f'SSL Cert: *{key}* - expires in {days_left:.1f} days ✅'
        elif days_left <= 0:
            message = f'SSL Cert: *{key}* - EXPIRED ({abs(days_left):.1f} days ago) ⚠️'
        else:
            message = f'SSL Cert: *{key}* - expires in {days_left:.1f} days (warning threshold: {warning_days}d) ⚠️'

        other_data = {
            'host': host,
            'port': port,
            'days_left': round(days_left, 2),
            'expires': cert['notAfter'],
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)
