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

"""Watchful module to check DNS resolution for any record type."""

import concurrent.futures
import json
import os
import socket

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')

try:
    import dns.resolver
    _HAS_DNSPYTHON = True
except ImportError:
    _HAS_DNSPYTHON = False

_SOCKET_TYPES = frozenset({'A', 'AAAA'})


def _resolve_socket(host: str, record_type: str, timeout: float) -> list:
    """Resolve A or AAAA records using stdlib socket (no extra deps)."""
    family = socket.AF_INET if record_type == 'A' else socket.AF_INET6
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(socket.getaddrinfo, host, None, family)
        try:
            results = future.result(timeout=timeout)
        except (concurrent.futures.TimeoutError, OSError, socket.gaierror):
            return []
    return list(dict.fromkeys(r[4][0] for r in results))


def _resolve_dns(host: str, record_type: str, timeout: float) -> list:
    """Resolve any DNS record type using dnspython. Returns list of string representations."""
    if not _HAS_DNSPYTHON:
        raise ImportError(
            f"dnspython not installed — cannot query {record_type} records. "
            "Install it with: pip install dnspython"
        )
    resolver = dns.resolver.Resolver()
    resolver.lifetime = float(timeout)
    try:
        answers = resolver.resolve(host, record_type)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []

    result = []
    for rdata in answers:
        rt = record_type.upper()
        if rt in ('A', 'AAAA'):
            result.append(str(rdata))
        elif rt == 'CNAME':
            result.append(str(rdata.target).rstrip('.'))
        elif rt == 'MX':
            result.append(f'{rdata.preference} {str(rdata.exchange).rstrip(".")}')
        elif rt == 'TXT':
            result.append(b''.join(rdata.strings).decode('utf-8', errors='replace'))
        elif rt in ('NS', 'PTR'):
            result.append(str(rdata.target).rstrip('.'))
        elif rt == 'SOA':
            result.append(f'{str(rdata.mname).rstrip(".")} serial={rdata.serial}')
        else:
            result.append(str(rdata))
    return result


class Watchful(ModuleBase):
    """Watchful module to check DNS resolution for any record type."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    _MODULE_DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                        if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("DNS: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, value) in self.get_conf('list', {}).items():
            if not isinstance(value, dict):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            host = (value.get('host', '') or '').strip() or key
            record_type = (value.get('record_type', '') or '').strip().upper() or 'A'
            expected = (value.get('expected', '') or '').strip()
            timeout = int(value.get('timeout', 0) or 0) or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])
            self._debug(f"DNS: {key} - host={host} type={record_type} expected={expected!r}", DebugLevel.info)
            list_items.append({
                'key': key,
                'host': host,
                'record_type': record_type,
                'expected': expected,
                'timeout': timeout,
            })

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_item = {
                executor.submit(self._dns_check, item): item
                for item in list_items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    self._debug(f"DNS: {item['key']} - Exception: {exc}", DebugLevel.error)
                    message = f'DNS: {item["key"]} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message)

        super().check()
        return self.dict_return

    def _dns_check(self, item):
        key = item['key']
        host = item['host']
        record_type = item['record_type']
        expected = item['expected']
        timeout = item['timeout']

        error = None
        if record_type in _SOCKET_TYPES:
            resolved = _resolve_socket(host, record_type, timeout)
        else:
            try:
                resolved = _resolve_dns(host, record_type, timeout)
            except ImportError as exc:
                resolved = []
                error = str(exc)
            except Exception as exc:  # pylint: disable=broad-except
                resolved = []
                error = str(exc)

        ok = bool(resolved)
        if ok and expected:
            ok = any(expected.lower() in r.lower() for r in resolved)

        short = ', '.join(resolved[:3]) + ('…' if len(resolved) > 3 else '')

        if error:
            message = f'DNS: *{key}* - {record_type} {host}: {error} ⚠️'
            ok = False
        elif ok:
            message = f'DNS: *{key}* - {record_type} {host} → {short} ✅'
        elif not resolved:
            message = f'DNS: *{key}* - {record_type} {host}: no results ⚠️'
        else:
            message = f'DNS: *{key}* - {record_type} {host}: expected "{expected}" not in [{short}] ⚠️'

        other_data = {
            'host': host,
            'record_type': record_type,
            'resolved': resolved,
            'expected': expected,
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)
