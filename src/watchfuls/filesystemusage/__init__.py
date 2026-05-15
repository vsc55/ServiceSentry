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
""" Watchful to check filesystem usage (cross-platform via psutil). """

import json
import os

import psutil

from lib.debug import DebugLevel
from lib.modules import ModuleBase

_SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), 'schema.json'), encoding='utf-8'))


class Watchful(ModuleBase):
    """ Watchful to check filesystem usage (cross-platform via psutil). """

    # Filesystem types to ignore (virtual / pseudo filesystems).
    _IGNORED_FSTYPES = frozenset({
        'squashfs', 'tmpfs', 'devtmpfs', 'overlay', 'proc', 'sysfs',
        'devfs', 'cgroup', 'cgroup2', 'autofs', 'binfmt_misc',
    })

    ITEM_SCHEMA = _SCHEMA
    WATCHFUL_ACTIONS: frozenset[str] = frozenset({'discover'})

    # Default values are derived from schema.json so there is a single
    # source of truth that the web UI can also consume.
    _DEFAULTS = {k: v['default'] for k, v in _SCHEMA['list'].items()
                 if isinstance(v, dict) and 'default' in v}

    def __init__(self, monitor):
        super().__init__(monitor, __package__)

    def check(self):
        if not self.is_enabled:
            self._debug("FilesystemUsage: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        # Build per-partition config from the list section.
        # Maps mountpoint → per-partition config dict (may include 'alert').
        partition_configs: dict = {}
        raw_list = self.get_conf('list', {})
        has_explicit_list = bool(raw_list)

        for (key, value) in raw_list.items():
            match value:
                case int():
                    # Legacy format: int value is the alert threshold for this partition.
                    partition_configs[key] = {'alert': value}
                    self._debug(
                        f"[Deprecate] Check: {key} - Alert: {value}. Please update format.",
                        DebugLevel.warning
                    )

                case dict():
                    is_enabled = value.get("enabled", self._DEFAULTS['enabled'])
                    if is_enabled:
                        part = (value.get('partition', '') or '').strip() or key
                        partition_configs[part] = value
                        self._debug(f"Check: {part} - Enabled: True", DebugLevel.info)

                case _:
                    self._debug(
                        f"Check: {key} - Invalid configuration format. Treating as disabled.",
                        DebugLevel.warning
                    )

        # Module-level alert threshold (fallback when partition has no specific config).
        module_alert = self.get_conf('alert', self._DEFAULTS['alert'])

        for part in psutil.disk_partitions():
            if part.fstype in self._IGNORED_FSTYPES:
                continue

            mount_point = part.mountpoint

            # When an explicit list is provided, only check configured partitions.
            if has_explicit_list and mount_point not in partition_configs:
                continue

            try:
                usage = psutil.disk_usage(mount_point)
            except (PermissionError, OSError):
                self._debug(
                    f"FilesystemUsage: Permission denied for {mount_point}, skipping.",
                    DebugLevel.warning
                )
                continue

            used_percent = usage.percent
            cfg = partition_configs.get(mount_point, {})
            for_usage_alert = cfg.get('alert') or module_alert

            if used_percent > float(for_usage_alert):
                status = False
                s_msg = "Warning"
                icon = '⚠️'
            else:
                status = True
                s_msg = "Normal"
                icon = '✅'

            s_msg = f'{s_msg} partition {part.device} used {used_percent}% {icon}'

            other_data = {
                'used': used_percent,
                'mount': mount_point,
                'alert': for_usage_alert
            }
            self.dict_return.set(mount_point, status, s_msg, other_data=other_data)

        super().check()
        return self.dict_return

    @classmethod
    def discover(cls) -> list:
        """Return [{name, display_name, device, fstype, status}] for all mounted partitions."""
        try:
            partitions = []
            for p in psutil.disk_partitions():
                if p.fstype in cls._IGNORED_FSTYPES:
                    continue
                try:
                    pct = f'{psutil.disk_usage(p.mountpoint).percent:.0f}%'
                except (PermissionError, OSError):
                    pct = '?'
                display = p.device + (f' ({p.fstype})' if p.fstype else '')
                partitions.append({
                    'name': p.mountpoint,
                    'display_name': display,
                    'device': p.device,
                    'fstype': p.fstype,
                    'status': pct,
                })
            return sorted(partitions, key=lambda x: x['name'].lower())
        except Exception:
            return []
