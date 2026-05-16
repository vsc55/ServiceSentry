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

import json
import os

import psutil

from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))

SUPPORTED_PLATFORMS = ('linux', 'darwin', 'win32')


class Watchful(ModuleBase):
    """Watchful module to check total CPU usage via psutil."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['__module__'].items()
                 if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            return self.dict_return

        alert = float(self.get_conf('alert', self._DEFAULTS['alert']))
        interval = float(self.get_conf('interval', self._DEFAULTS['interval']))

        usage = psutil.cpu_percent(interval=interval)
        ok = usage < alert

        message = f'CPU used {usage:.1f}%'
        if ok:
            message = f'Normal {message} ✅'
        else:
            message = f'Excessive {message} ⚠️'

        other_data = {
            'used': usage,
            'alert': alert,
        }
        self.dict_return.set('cpu', ok, message, other_data=other_data)

        super().check()
        return self.dict_return
