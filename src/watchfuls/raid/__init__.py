#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
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
"""Watchful to monitor RAID health on a host (local or remote over SSH).

Host-centric: each ``list`` item binds to a host (``host_uid``).  The Linux
``/proc/mdstat`` is read on that host via :meth:`ModuleBase.host_exec` — locally
for a *local* host, or over the host's SSH connection for a *remote* host — and
parsed with :meth:`lib.system.linux.RaidMdstat.parse_lines`.  To watch the monitor's
own machine, add a host of kind *local*.
"""

import json
import os
import shlex

from lib.debug import DebugLevel
from lib.system.linux import RaidMdstat
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class Watchful(ModuleBase):
    """Monitor RAID (mdstat) health per host, locally or over SSH."""

    ITEM_SCHEMA = _SCHEMA

    _DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['list'])

    _MODULE_DEFAULTS = ModuleBase._schema_defaults(_SCHEMA['__module__'])

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug('RAID: module disabled, skipping.', DebugLevel.info)
            return self.dict_return

        items = [(k, v) for k, v in self.get_conf('list', {}).items()
                 if isinstance(v, dict) and v.get('enabled', self._DEFAULTS['enabled'])]
        self.run_parallel(items, self._check_item, 'RAID')
        super().check()
        return self.dict_return

    def _check_item(self, key, raw):
        item = self.resolve_host(raw)
        # Bound host in maintenance → skip (resolve_host disables it).
        if item.get('_host_maintenance') or not item.get('enabled', True):
            return
        label = (item.get('label') or '').strip() or key
        os_ = self.host_os(item)
        if os_ != 'linux':
            self.dict_return.set(
                f'{key}', False,
                f'RAID: {label} - *mdstat only available on Linux (host OS: {os_})* ⚠️',
                name=label)
            return
        path = self.get_conf('mdstat_path', self._MODULE_DEFAULTS['mdstat_path']) or '/proc/mdstat'
        timeout = self.module_default('timeout', self._MODULE_DEFAULTS['timeout'])
        out, err, code = self.host_exec(item, f"cat {shlex.quote(path)}", timeout=timeout)
        if code != 0:
            raise OSError((err or '').strip() or f'cat {path} exited {code}')
        self._md_analyze(RaidMdstat.parse_lines(out), key, label)

    def _md_analyze(self, list_md, key, label):
        if not list_md:
            self.dict_return.set(f'{key}', True, f"[{label}] *No RAID's* in the system. ✅", name=label)
            return
        for (md, value) in list_md.items():
            other_data = {}
            is_warning = True
            match value.get("update", ''):
                case RaidMdstat.UpdateStatus.ok:
                    is_warning = False
                    message = f"RAID *{label}/{md}* in good status. ✅"

                case RaidMdstat.UpdateStatus.error:
                    message = f"*RAID {label}/{md} is degraded.* ⚠️"

                case RaidMdstat.UpdateStatus.recovery:
                    other_data['percent'] = value.get("recovery", {}).get('percent', -1)
                    other_data['finish']  = value.get("recovery", {}).get('finish',  -1)
                    other_data['speed']   = value.get("recovery", {}).get('speed',   -1)
                    message = (
                        f"*RAID {label}/{md} is degraded, recovery status "
                        f"{other_data['percent']}%, estimate time to finish "
                        f"{other_data['finish']}.* ⚠️"
                    )

                case _:
                    message = f"*RAID {label}/{md} Unknown Error*. ⚠️"

            self.dict_return.set(f'{key}_{md}', not is_warning, message, other_data=other_data, name=label)

    def _label(self, key) -> str:
        label = (self.get_conf_in_list("label", key, '') or '').strip()
        return label or key
