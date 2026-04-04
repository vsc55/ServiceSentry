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
""" Thermal information collection for Linux. """

__all__ = ['ThermalInfoCollection']

import glob
import os

from lib.linux.thermal_base import ThermalBase
from lib.linux.thermal_node import ThermalNode


class ThermalInfoCollection (ThermalBase):
    """ Thermal information collection for Linux. """

    def __init__(self, autodetect: bool = False):
        self.nodes: list[ThermalNode] = []
        if autodetect:
            self.detect()

    def clear(self):
        """ Clear the thermal nodes list. """
        self.nodes.clear()

    @property
    def count(self) -> int:
        """ Return the number of thermal nodes. """
        return len(self.nodes)

    def detect(self):
        """ Detect the thermal nodes and populate the nodes list. """
        self.clear()

        pattern = os.path.join(self.PATH_THERMAL, 'thermal_zone*')
        for dev_path in glob.glob(pattern):
            dev_name = os.path.basename(dev_path)
            self._add_sensor(dev_name)

    def _add_sensor(self, dev: str):
        if not dev or not dev.strip():
            return False

        self.nodes.append(ThermalNode(dev))
        return True


if __name__ == "__main__":

    x = ThermalInfoCollection()
    x.detect()

    for item in x.nodes:
        print("Dev:", item.dev, "- Type:", item.type, "- Temp:", item.temp)
        print("")
