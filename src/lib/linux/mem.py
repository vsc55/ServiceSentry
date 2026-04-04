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
""" Memory information collection for Linux. """

from dataclasses import dataclass

__all__ = ['Mem']


@dataclass
class MemInfo:
    """ Memory information structure. """
    total: int = 0
    free: int = 0

    @property
    def used(self) -> int:
        """ Return the used memory. """
        return self.total - self.free

    @property
    def used_percent(self) -> float:
        """ Return the used memory percentage. """
        if self.total <= 0:
            return 0.0
        return (self.used / self.total) * 100.0


class Mem:
    """ Memory information collection for Linux. """

    @staticmethod
    def _read_meminfo() -> dict:
        """ Read the memory information from /proc/meminfo. """
        data = {}
        with open('/proc/meminfo', 'r', encoding='utf-8') as mem:
            for line in mem:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    data[key] = int(parts[1])
        return data

        # with open('/proc/meminfo', 'r') as mem:
        #     ret = {'ram': {}, 'swap': {}}
        #     for i in mem:
        #         s_line = i.split()
        #         if str(s_line[0]) == 'MemTotal:':
        #             ret['ram']['total'] = int(s_line[1])
        #         elif str(s_line[0]) == 'MemFree:':
        #             ret['ram']['free'] = int(s_line[1])
        #         elif str(s_line[0]) == 'Buffers:':
        #             ret['ram']['buffers'] = int(s_line[1])
        #         elif str(s_line[0]) == 'Cached:':
        #             ret['ram']['cached'] = int(s_line[1])
        #         elif str(s_line[0]) == 'SwapTotal:':
        #             ret['swap']['total'] = int(s_line[1])
        #         elif str(s_line[0]) == 'SwapFree:':
        #             ret['swap']['free'] = int(s_line[1])
        # return ret

    @property
    def ram(self) -> MemInfo:
        """ Return the RAM memory information. """
        mem_info = self._read_meminfo()

        total = mem_info.get('MemTotal', 0)

        if 'MemAvailable' in mem_info:
            free = mem_info['MemAvailable']
        else:
            free = (
                mem_info.get('MemFree', 0) +
                mem_info.get('Buffers', 0) +
                mem_info.get('Cached', 0)
            )
        return MemInfo(total=total, free=free)

    @property
    def swap(self) -> MemInfo:
        """Return the SWAP memory information."""
        mem_info = self._read_meminfo()

        return MemInfo(
            total=mem_info.get('SwapTotal', 0),
            free=mem_info.get('SwapFree', 0),
        )


if __name__ == "__main__":
    x = Mem()
    y = x.ram
    print(y.total, y.free, y.used)

    y = x.swap
    print(y.total, y.free, y.used)

    print(Mem().ram.total, Mem().ram.free, Mem().ram.used, Mem().ram.used_percent)
    print(Mem().swap.total, Mem().swap.free, Mem().swap.used, Mem().swap.used_percent)
