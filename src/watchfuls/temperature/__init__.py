#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Lorenzo Carbonell (aka atareao)
# <lorenzo.carbonell.cerezo at gmail dot com>
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
"""Watchful to check temperature sensors on the bound host (local or over SSH).

Host-centric: each check binds to a host (``host_uid``) and a sensor.  Sensor
temperatures are read on that host from Linux ``/sys/class/thermal`` via
:meth:`ModuleBase.host_exec` and compared with a per-check threshold.
"""

import json
import os

from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

# Reads every thermal zone with a single fixed ``grep`` (no remote shell loop,
# so the command fits a strict SSH allowlist); ``grep -H .`` emits one
# "<path>:<value>" line per file and the type↔temp correlation is done in
# Python by :meth:`_parse_thermal`.
_THERMAL_CMD = (
    'grep -H . /sys/class/thermal/thermal_zone*/type '
    '/sys/class/thermal/thermal_zone*/temp'
)


class Watchful(ModuleBase):
    """Check temperature sensors per host against a threshold (Linux)."""

    ITEM_SCHEMA = _SCHEMA
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'discover'})

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])
    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            return self.dict_return
        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._temp_check, 'Temp')
        super().check()
        return self.dict_return

    def _temp_check(self, key, raw):
        item = self.resolve_host(raw)
        if item.get('_host_maintenance') or not item.get('enabled', True):
            return
        os_ = self.host_os(item)
        if os_ != 'linux':
            self.dict_return.set(key, False,
                                 f'Temp: {key} - *only available on Linux (host OS: {os_})* ⚠️')
            return
        sensor = (item.get('sensor', '') or '').strip() or key
        label = (item.get('label', '') or '').strip() or sensor
        out, err, code = self.host_exec(
            item, _THERMAL_CMD, timeout=self.module_default('timeout', self._MODULE_DEFAULTS['timeout']))
        if code != 0 and not out:
            raise OSError((err or '').strip() or f'sensor read exited {code}')
        temps = dict(self._parse_thermal(out))
        if sensor not in temps:
            raise ValueError(f'sensor "{sensor}" not found')

        temp = temps[sensor]
        # Blank/0/absent inherits the module-level Threshold (Configuration >
        # Modules), then the module schema default — never the item default (0).
        # get_conf (not module_default) preserves the float threshold.
        alert = float(item.get('alert', 0)
                      or self.get_conf('alert', None)
                      or self._MODULE_DEFAULTS['alert'])
        warning = temp > alert
        msg = f'Sensor *{label}*, '
        msg += (f'*over temperature Warning {temp:.1f} ºC* 🔥' if warning
                else f'temperature Ok *{temp:.1f} ºC* ✅')
        self.dict_return.set(key, not warning, msg,
                             other_data={'type': sensor, 'temp': temp, 'alert': alert},
                             name=label)

    @staticmethod
    def _parse_thermal(out):
        """Parse ``grep -H .`` output over /sys/class/thermal/*/{type,temp}.

        Each line is ``<path>:<value>``; ``type`` and ``temp`` are correlated
        per thermal-zone directory.  Returns ``[(name, celsius)]`` in zone
        order (duplicate type → type_N)."""
        zones: dict = {}
        for line in (out or '').splitlines():
            path, sep, val = line.partition(':')
            if not sep:
                continue
            zone, _, leaf = path.rpartition('/')
            val = val.strip()
            if leaf == 'type' and val:
                zones.setdefault(zone, {})['type'] = val
            elif leaf == 'temp' and val.lstrip('-').isdigit():
                zones.setdefault(zone, {})['temp'] = int(val)
        seen, result = {}, []
        for zone in sorted(zones):
            typ = zones[zone].get('type')
            temp = zones[zone].get('temp')
            if not typ or temp is None:
                continue
            n = seen.get(typ, 0)
            seen[typ] = n + 1
            name = typ if n == 0 else f'{typ}_{n}'
            result.append((name, temp / 1000.0))
        return result

    @classmethod
    def discover(cls, config=None) -> list:
        """Temperature sensors on the host (Linux thermal zones)."""
        from lib.core.hosts import runner as host_runner  # noqa: PLC0415
        host = (config or {}).get('__host__') if isinstance(config, dict) else None
        out, _err, code = host_runner.run(host, _THERMAL_CMD, timeout=15)
        if code != 0 and not out:
            return []
        return [{'name': name, 'display_name': name, 'status': f'{c:.1f}°C'}
                for name, c in cls._parse_thermal(out)]
