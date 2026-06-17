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
import time

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')


def _to_float(value):
    """Parse a NUT variable (string) to float, or None if not numeric."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


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
        # Use a wall-clock deadline so a slow NUT server that dribbles data
        # one byte at a time cannot extend the wait beyond the configured timeout.
        _deadline = time.monotonic() + timeout
        for line in f:
            if time.monotonic() > _deadline:
                raise TimeoutError('NUT response timeout waiting for END LIST VAR')
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
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'test_connection'})

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("UPS: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_items = []
        for (key, raw) in self.get_conf('list', {}).items():
            if not isinstance(raw, dict):
                continue
            # Host-centric: merge the bound host's address + NUT credentials.
            value = self.resolve_host(raw)
            if value.get('_host_maintenance'):
                continue
            enabled = str(value.get('enabled', True)).lower() in ('true', '1', 'yes', True, 'on', 'enable')
            if not enabled:
                continue
            host = (value.get('host', '') or '').strip()
            if not host:
                self._debug(f"UPS: {self.item_label(key)} - host is empty, skipping.", DebugLevel.warning)
                continue
            port = int(value.get('port', 0) or 0) or 3493
            ups_name = (value.get('ups_name', '') or '').strip() or self._DEFAULTS['ups_name']
            user = (value.get('user', '') or '').strip()
            password = (value.get('password', '') or '').strip()
            timeout = int(value.get('timeout', 0) or 0) or self.get_conf('timeout', self._MODULE_DEFAULTS['timeout'])
            self._debug(f"UPS: {self.item_label(key)} - host={host}:{port} ups_name={ups_name}", DebugLevel.info)

            def _alert(field):
                try:
                    return int(value.get(field, self._DEFAULTS[field]) or 0)
                except (TypeError, ValueError):
                    return int(self._DEFAULTS[field])

            list_items.append({
                'key': key,
                'label': (value.get('label', '') or '').strip(),
                'host': host,
                'port': port,
                'ups_name': ups_name,
                'user': user,
                'password': password,
                'timeout': timeout,
                'alert_on_battery': str(value.get('alert_on_battery',
                                        self._DEFAULTS['alert_on_battery'])).lower()
                                    in ('true', '1', 'yes', 'on', 'enable'),
                'alert_battery':  _alert('alert_battery'),
                'alert_runtime':  _alert('alert_runtime'),
                'alert_load':     _alert('alert_load'),
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
                    _nm = item.get('label') or item.get('ups_name') or item['key']
                    message = f'UPS: {_nm} - *Error: {exc}* 💥'
                    self.dict_return.set(item['key'], False, message,
                                         other_data={'name': _nm})

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

        # Friendly display name: the item label if set, else the device
        # make/model reported by NUT (e.g. "APC Back-UPS Pro 1600"), else the
        # NUT ups_name. The result key is an opaque UID, so this name is what
        # the messages, history, status page and "Latest data" show.
        _model = (variables.get('device.model') or variables.get('ups.model') or '').strip()
        _mfr   = (variables.get('device.mfr') or variables.get('ups.mfr') or '').strip()
        name = item.get('label') or (f'{_mfr} {_model}'.strip()) or ups_name or key

        status = variables.get('ups.status', '') or ''
        tokens = status.split()
        # "OL" = on-line, "OB" = on battery, "LB" = low battery
        online     = 'OL' in tokens
        on_battery = 'OB' in tokens
        low_batt   = 'LB' in tokens

        charge      = _to_float(variables.get('battery.charge'))     # %
        runtime_s   = _to_float(variables.get('battery.runtime'))    # seconds
        runtime_min = round(runtime_s / 60.0, 1) if runtime_s is not None else None
        load        = _to_float(variables.get('ups.load'))           # %

        # Evaluate the configured thresholds; collect every reason that trips.
        reasons = []
        if low_batt:
            reasons.append('LOW BATTERY')
        if on_battery and item['alert_on_battery']:
            reasons.append('on battery')
        if charge is not None and item['alert_battery'] > 0 and charge < item['alert_battery']:
            reasons.append(f'battery {charge:.0f}% < {item["alert_battery"]}%')
        if runtime_min is not None and item['alert_runtime'] > 0 and runtime_min < item['alert_runtime']:
            reasons.append(f'runtime {runtime_min:.0f}m < {item["alert_runtime"]}m')
        if load is not None and item['alert_load'] > 0 and load > item['alert_load']:
            reasons.append(f'load {load:.0f}% > {item["alert_load"]}%')
        if not online and not on_battery:
            reasons.append(f'status {status or "unknown"}')

        ok = not reasons
        if ok:
            extra = []
            if charge is not None:
                extra.append(f'{charge:.0f}%')
            if runtime_min is not None:
                extra.append(f'{runtime_min:.0f}m')
            detail = ' · '.join(extra)
            message = f'UPS: *{name}* - Online ({status}){f" — {detail}" if detail else ""} ✅'
        else:
            icon = '🔋' if (low_batt or on_battery) else '⚠️'
            message = f'UPS: *{name}* - {", ".join(reasons)} ({status}) {icon}'

        other_data = {
            'name': name,
            'host': host,
            'ups_name': ups_name,
            'status': status,
            'on_battery': on_battery,
            'low_battery': low_batt,
            # Numeric metrics for the history charts (battery %, autonomy, load).
            'battery_charge': charge,
            'runtime': runtime_min,           # minutes
            'load': load,
        }
        self.dict_return.set(key, ok, message, False, other_data)

        if self.check_status(ok, self.name_module, key):
            self.send_message(message, ok)

    # ── Web UI — test_connection ──────────────────────────────────────
    @classmethod
    def test_connection(cls, config: dict) -> dict:
        """Probe the NUT UPSD connection for one UPS item (web UI button).

        Host-centric: use the item's ``host`` field, falling back to the bound
        host's address injected as ``__host__`` by the route.  NUT is queried
        directly over TCP, so the test connects to ``host:port`` regardless of
        whether the host is reached locally or over SSH for other modules.
        """
        host = str(config.get('host') or '').strip()
        if not host:
            host = str((config.get('__host__') or {}).get('address') or '').strip()
        if not host:
            return {'ok': False, 'message': 'No host configured'}
        port     = int(config.get('port') or 0) or 3493
        ups_name = str(config.get('ups_name') or '').strip() or cls._DEFAULTS['ups_name']
        user     = str(config.get('user') or '').strip()
        password = str(config.get('password') or '')
        timeout  = int(config.get('timeout') or 0) or cls._MODULE_DEFAULTS['timeout']
        try:
            variables = _nut_query(host=host, port=port, ups_name=ups_name,
                                   user=user, password=password, timeout=timeout)
        except Exception as exc:  # pylint: disable=broad-except
            return {'ok': False, 'message': f'{host}:{port} - {exc}'}
        status = variables.get('ups.status', '') or 'unknown'
        # On success return EVERY NUT variable so the UI can show them in a modal.
        info = {k: variables[k] for k in sorted(variables)}
        return {'ok': True,
                'message': f'{host}:{port} - {ups_name} OK (status: {status})',
                'info': info}
