#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Lorenzo Carbonell (aka atareao)
# <lorenzo.carbonell.cerezo at gmail dot com>

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

from lib.debug import DebugLevel
from lib.mem import Mem
from lib.mem_info import MemInfo
from lib.modules import ModuleBase


class Watchful(ModuleBase):
    """ Watchful to check RAM and SWAP usage. """

    ITEM_SCHEMA = {
        'config': {
            'alert_ram': {'default': 60, 'type': 'int', 'min': 0, 'max': 100},
            'alert_swap': {'default': 60, 'type': 'int', 'min': 0, 'max': 100},
        },
    }

    _DEFAULTS = {k: v['default'] for k, v in ITEM_SCHEMA['config'].items()}

    def __init__(self, monitor):
        super().__init__(monitor, __name__)

    def _check_config(self, key_conf, default_val):
        val_conf = self.get_conf(key_conf, default_val)

        if isinstance(val_conf, str):
            val_conf = val_conf.strip()
            if not val_conf.isnumeric():
                self._debug(
                    f"Warning, config {key_conf} type incorrect!",
                    DebugLevel.warning
                )
                return default_val
            val_conf = int(val_conf)

        if not val_conf or not (0 <= val_conf <= 100):
            self._debug(
                f"Warning, config {key_conf} value not valid!",
                DebugLevel.warning
            )
            return default_val

        return val_conf

    def check(self):
        m = Mem()
        x = {
            'ram': {
                'caption': 'RAM',
                'alarm': self._check_config("alert_ram", self._DEFAULTS['alert_ram']),
                'used': m.ram.used_percent
            },
            'swap': {
                'caption': 'SWAP',
                'alarm': self._check_config("alert_swap", self._DEFAULTS['alert_swap']),
                'used': m.swap.used_percent
            }
        }

        for (key, value) in x.items():
            per = float(value['used'])
            alert = float(value['alarm'])
            if per < alert:
                is_warning = False
            else:
                is_warning = True

            message = f'{value["caption"]} used {per:.1f}%'
            if is_warning:
                message = f'Excessive {message} ⚠️'
            else:
                message = f'Normal {message} ✅'

            other_data = {
                'used': per,
                'alert': alert
            }
            self.dict_return.set(key, not is_warning, message, other_data=other_data)

        super().check()
        return self.dict_return
