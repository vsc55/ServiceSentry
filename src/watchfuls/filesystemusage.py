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

import psutil

from lib.debug import DebugLevel
from lib.modules import ModuleBase


class Watchful(ModuleBase):
    """ Watchful to check filesystem usage (cross-platform via psutil). """

    # Filesystem types to ignore (virtual / pseudo filesystems).
    _IGNORED_FSTYPES = frozenset({
        'squashfs', 'tmpfs', 'devtmpfs', 'overlay', 'proc', 'sysfs',
        'devfs', 'cgroup', 'cgroup2', 'autofs', 'binfmt_misc',
    })

    ITEM_SCHEMA = {
        'list': {
            'enabled': {
                'default': True,
                'type': 'bool'
            },
            'alert': {
                'default': 85,
                'type': 'int',
                'min': 0,
                'max': 100
            },
            'partition': {
                'default': '',
                'type': 'str'
            },
            'label': {
                'default': '',
                'type': 'str'
            },
        },
    }

    # Default values are derived from ITEM_SCHEMA so there is a single
    # source of truth that the web UI can also consume.
    _DEFAULTS = {k: v['default'] for k, v in ITEM_SCHEMA['list'].items()}

    def __init__(self, monitor):
        super().__init__(monitor, __name__)

    def check(self):
        if not self.is_enabled:
            self._debug("FilesystemUsage: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_partition: list = []

        for (key, value) in self.get_conf('list', {}).items():
            is_enabled = self._DEFAULTS['enabled']
            match value:
                case int():
                    # Legacy support: if the value is an int, treat it as the alert threshold for
                    # the partition identified by the key.
                    is_enabled = True
                    part = key
                    self._debug(
                        f"[Deprecate] Check: {part} - Alert: {value}. Please update format.",
                        DebugLevel.warning
                    )

                case dict():
                    # New format: value is a dict with possible 'enabled' and 'partition' keys.
                    # If 'enabled' is not specified, default to the module's default enabled state.
                    # If 'partition' is not specified, default to the key.
                    is_enabled = value.get("enabled", is_enabled)
                    part = (value.get('partition', '') or '').strip() or key
                    self._debug(f"Check: {part} - Enabled: {is_enabled}", DebugLevel.info)

                case _:
                    is_enabled = False
                    self._debug(
                        f"Check: {key} - Invalid configuration format. Treating as disabled.",
                        DebugLevel.warning
                    )

            if is_enabled:
                list_partition.append(part)

        for part in psutil.disk_partitions():
            if part.fstype in self._IGNORED_FSTYPES:
                continue

            mount_point = part.mountpoint
            if not mount_point in list_partition:
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
            for_usage_alert = self.get_conf_in_list("alert", mount_point, self._DEFAULTS['alert'])

            if used_percent > float(for_usage_alert):
                status = False
                s_msg = "Warning"
                icon = '⚠️'
            else:
                status = True
                s_msg = "Normal"
                icon = '✅'

            # s_msg = f'{s_msg} partition {part.device} ({mount_point}) used {used_percent}% {icon}'
            s_msg = f'{s_msg} partition {part.device} used {used_percent}% {icon}'

            other_data = {
                'used': used_percent,
                'mount': mount_point,
                'alert': for_usage_alert
            }
            self.dict_return.set(mount_point, status, s_msg, other_data=other_data)

        super().check()
        return self.dict_return
