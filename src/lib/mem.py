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
"""
Memory information collection (cross-platform).

Uses *psutil* to obtain RAM and SWAP metrics on Linux, Windows and macOS.
Values are expressed in **kB** for consistency with the MemInfo dataclass.
"""

import sys

import psutil

from lib.mem_info import MemInfo

__all__ = ['Mem']


class Mem:
    """Cross-platform memory information via *psutil*."""

    @property
    def ram(self) -> MemInfo:
        """Return RAM memory information."""
        vm = psutil.virtual_memory()
        return MemInfo(
            total=vm.total // 1024,
            free=vm.available // 1024,
        )

    @property
    def swap(self) -> MemInfo:
        """Return SWAP memory information."""
        sw = psutil.swap_memory()
        return MemInfo(
            total=sw.total // 1024,
            free=(sw.total - sw.used) // 1024,
        )


if __name__ == "__main__":
    m = Mem()
    print(f"Platform: {sys.platform}")
    print(
        f"RAM: \n "
        f" - total={m.ram.total} \n "
        f" - free={m.ram.free}  \n "
        f" - used={m.ram.used} \n "
        f" - used%={m.ram.used_percent:.1f}"
    )
    print(
        f"SWAP: \n "
        f" - total={m.swap.total}  \n "
        f" - free={m.swap.free}  \n "
        f" - used={m.swap.used}  \n "
        f" - used%={m.swap.used_percent:.1f}"
    )
