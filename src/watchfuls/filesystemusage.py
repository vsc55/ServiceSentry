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

from lib.modules import ModuleBase


class Watchful(ModuleBase):
    """ Watchful to check filesystem usage (cross-platform via psutil). """

    # Default alert percentage for filesystem usage if not configured or invalid.
    _DEFAULT_ALERT = 85

    # Filesystem types to ignore (virtual / pseudo filesystems).
    _IGNORED_FSTYPES = frozenset({
        'squashfs', 'tmpfs', 'devtmpfs', 'overlay', 'proc', 'sysfs',
        'devfs', 'cgroup', 'cgroup2', 'autofs', 'binfmt_misc',
    })

    ITEM_SCHEMA = {
        'list': {
            'alert': 85,
        },
    }

    def __init__(self, monitor):
        super().__init__(monitor, __name__)

    def check(self):
        list_partition = self.get_conf('list', {})

        usage_alert = self.get_conf("alert", self._DEFAULT_ALERT)
        if isinstance(usage_alert, str):
            usage_alert = usage_alert.strip()

        if not usage_alert or usage_alert < 0 or usage_alert > 100:
            usage_alert = self._DEFAULT_ALERT

        for part in psutil.disk_partitions():
            if part.fstype in self._IGNORED_FSTYPES:
                continue

            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue

            mount_point = part.mountpoint
            used_percent = usage.percent

            if mount_point in list_partition:
                for_usage_alert = list_partition[mount_point]
            else:
                for_usage_alert = usage_alert

            if used_percent > float(for_usage_alert):
                tmp_status = False
                tmp_message = f'Warning partition {part.device} ({mount_point}) used {used_percent}% ⚠️'
            else:
                tmp_status = True
                tmp_message = f'Normal partition {part.device} ({mount_point}) used {used_percent}% ✅'

            other_data = {'used': used_percent, 'mount': mount_point, 'alert': for_usage_alert}
            self.dict_return.set(mount_point, tmp_status, tmp_message, other_data=other_data)

        super().check()
        return self.dict_return
