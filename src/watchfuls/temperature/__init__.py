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

# Reads every thermal zone: prints "<type>|<millidegrees>" per zone.
_THERMAL_CMD = (
    'for z in /sys/class/thermal/thermal_zone*; do '
    'printf "%s|%s\\n" "$(cat "$z/type" 2>/dev/null)" "$(cat "$z/temp" 2>/dev/null)"; done'
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
            item, _THERMAL_CMD, timeout=self.get_conf('timeout', self._MODULE_DEFAULTS['timeout']))
        if code != 0 and not out:
            raise OSError((err or '').strip() or f'sensor read exited {code}')
        temps = dict(self._parse_thermal(out))
        if sensor not in temps:
            raise ValueError(f'sensor "{sensor}" not found')

        temp = temps[sensor]
        alert = float(item.get('alert', 0) or self._DEFAULTS['alert'])
        warning = temp > alert
        msg = f'Sensor *{label}*, '
        msg += (f'*over temperature Warning {temp:.1f} ºC* 🔥' if warning
                else f'temperature Ok *{temp:.1f} ºC* ✅')
        self.dict_return.set(key, not warning, msg,
                             other_data={'type': sensor, 'temp': temp, 'alert': alert})

    @staticmethod
    def _parse_thermal(out):
        """Lines "<type>|<millidegrees>" → [(name, celsius)] (dedup type → type_N)."""
        seen, result = {}, []
        for line in (out or '').splitlines():
            if '|' not in line:
                continue
            typ, _, val = line.partition('|')
            typ, val = typ.strip(), val.strip()
            if not typ or not val.lstrip('-').isdigit():
                continue
            n = seen.get(typ, 0)
            seen[typ] = n + 1
            name = typ if n == 0 else f'{typ}_{n}'
            result.append((name, int(val) / 1000.0))
        return result

    @classmethod
    def discover(cls, config=None) -> list:
        """Temperature sensors on the host (Linux thermal zones)."""
        from lib import host_runner  # noqa: PLC0415
        host = (config or {}).get('__host__') if isinstance(config, dict) else None
        out, _err, code = host_runner.run(host, _THERMAL_CMD, timeout=15)
        if code != 0 and not out:
            return []
        return [{'name': name, 'display_name': name, 'status': f'{c:.1f}°C'}
                for name, c in cls._parse_thermal(out)]
