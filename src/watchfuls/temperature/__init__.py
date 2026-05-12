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

import json
import os

import psutil

from lib.modules import EnumConfigOptions as ConfigOptions
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class Watchful(ModuleBase):

    ITEM_SCHEMA = _SCHEMA
    SUPPORTED_PLATFORMS = ('linux', 'darwin')

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            return self.dict_return

        for chip, readings in self._read_sensors().items():
            for idx, reading in enumerate(readings):
                dev_name = f"{chip}_{idx}"

                if not self._get_conf(ConfigOptions.enabled, dev_name):
                    continue

                default_label = reading.label.strip() if reading.label and reading.label.strip() else chip
                type_label = self._get_conf(ConfigOptions.label, dev_name, default_label)
                temp = reading.current
                temp_alert = self._get_conf(ConfigOptions.alert, dev_name)

                is_warning = temp > temp_alert

                message = f"Sensor *{type_label}*, "
                if is_warning:
                    message += f'*over temperature Warning {temp:.1f} ºC* 🔥'
                else:
                    message += f'temperature Ok *{temp:.1f} ºC* ✅'

                other_data = {'type': chip, 'temp': temp, 'alert': temp_alert}
                self.dict_return.set(dev_name, not is_warning, message, other_data=other_data)

        super().check()
        return self.dict_return

    @classmethod
    def discover(cls) -> list:
        """Return [{name, display_name, status}] for all available temperature sensors."""
        result = []
        for chip, readings in cls._read_sensors().items():
            for idx, reading in enumerate(readings):
                label = reading.label.strip() if reading.label and reading.label.strip() else ''
                display = chip + (f' — {label}' if label else f' [{idx}]')
                try:
                    status = f'{reading.current:.1f}°C'
                except Exception:
                    status = '?'
                result.append({
                    'name': f'{chip}_{idx}',
                    'display_name': display,
                    'status': status,
                })
        return result

    @classmethod
    def _read_sensors(cls) -> dict:
        """Return {chip: [readings]} via psutil (Linux / macOS only)."""
        if not hasattr(psutil, 'sensors_temperatures'):
            return {}
        try:
            return psutil.sensors_temperatures() or {}
        except Exception:
            return {}

    def _get_conf(self, opt_find, dev_name: str, default_val=None):
        if default_val is None:
            match opt_find:
                case ConfigOptions.alert:
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS['alert'])
                case ConfigOptions.enabled:
                    val_def = self.get_conf(opt_find.name, self._DEFAULTS['enabled'])
                case None:
                    raise ValueError("opt_find it can not be None!")
                case _:
                    raise TypeError(f"{opt_find.name} is not valid option!")
        else:
            val_def = default_val

        value = self.get_conf_in_list(opt_find, dev_name, val_def)

        match opt_find:
            case ConfigOptions.alert:
                return self._parse_conf_float(value, val_def)
            case ConfigOptions.enabled:
                return bool(value)
            case _:
                return self._parse_conf_str(value, val_def)
