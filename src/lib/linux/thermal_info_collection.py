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


class _ThermalBase:
    PATH_THERMAL = '/sys/class/thermal'

class ThermalNode(_ThermalBase):
    """ Thermal node information. """

    def __init__(self, dev: str):
        if not dev or not dev.strip():
            raise ValueError("dev cannot be empty")
        self._dev = dev.strip()

    @property
    def dev(self) -> str:
        """ Return the device name. """
        return self._dev

    @property
    def type(self) -> str:
        """ Return the type of the thermal node. """
        value = self._read_file(self._path_type)
        return value.strip() if value is not None else "Unknown"

    @property
    def temp(self) -> float:
        """ Return the temperature of the thermal node in Celsius. """
        value = self._read_file(self._path_temp)
        if value is None:
            return 0.0

        try:
            return float(value.strip()) / 1000.0
        except ValueError:
            return 0.0

    def _read_file(self, path_file: str, default=None):
        """
        Read the content of a file. Returns the content as a string, 
        or default if the file does not exist.
        """
        try:
            with open(path_file, 'r', encoding='utf-8') as f:
                return f.read()
        except OSError:
            return default

    @property
    def _path_dev(self) -> str:
        """ Return the path of the thermal node device. """
        return os.path.join(self.PATH_THERMAL, self.dev)

    @property
    def _path_temp(self) -> str:
        """ Return the path of the temperature file of the thermal node. """
        return os.path.join(self._path_dev, 'temp')

    @property
    def _path_type(self) -> str:
        """ Return the path of the type file of the thermal node. """
        return os.path.join(self._path_dev, 'type')

    def _is_exist_file(self, path_check) -> bool:
        """ Check if the file exist. """
        return bool(str(path_check).strip() and os.path.isfile(path_check))


class ThermalInfoCollection (_ThermalBase):
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
