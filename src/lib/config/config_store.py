#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Lorenzo Carbonell (aka atareao)
# <lorenzo.carbonell.cerezo at gmail dot com>
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
""" Store configuration in a file. """

import json
import os

from lib import ObjectBase
from lib.debug import DebugLevel

__all__ = ['ConfigStore']

class ConfigStore(ObjectBase):
    """ Object to store configuration in a file. """

    def __init__(self, file):
        self.file = file

    @property
    def is_exist_file(self) -> bool:
        """ Check if the file exist. """
        return bool(self.file and os.path.isfile(self.file))

    @property
    def is_writable_file(self) -> bool:
        """ Check if the file is writable. """
        if not self.file:
            return False

        if self.is_exist_file:
            return os.access(self.file, os.W_OK)

        parent = os.path.dirname(self.file) or '.'
        return os.access(parent, os.W_OK)

    @property
    def file(self) -> str:
        """ Get the file path. """
        return self._file

    @file.setter
    def file(self, val: str):
        """ Set the file path. """
        self._file: str = val

    def read(self, def_return = None):
        """ Read the configuration from the file. """
        return_date = def_return

        if self.is_exist_file:
            try:
                with open(self.file, 'r', encoding='utf-8') as f:
                    return_date = json.load(f)

            except json.JSONDecodeError:
                self.debug.print(
                    f"Config >> Warning: File ({self.file}) is not a valid JSON file!!!",
                    DebugLevel.warning
                )

            except OSError as e:
                self.debug.exception(e)

            except Exception as e:
                self.debug.exception(e)

        else:
            self.debug.print(
                f"Config >> Warning: File ({self.file}) not exist!!!",
                DebugLevel.warning
            )

        return return_date

    def save(self, data) -> bool:
        """ Save the configuration to the file. """
        if not self.file:
            self.debug.print(
                "Config >> Warning: File path is empty",
                DebugLevel.error
            )
            return False

        if not self.is_writable_file:
            self.debug.print(
                f"Config >> Warning: File ({self.file}) is not writable!!!",
                DebugLevel.error
            )
            return False

        try:
            with open(self.file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

        except TypeError as e:
            self.debug.print(
                f"Config >> Warning: Data is not JSON serializable ({e})",
                DebugLevel.warning
            )
            return False

        except OSError as e:
            self.debug.print(
                f"Config >> Warning: Cannot write file ({self.file}) ({e})",
                DebugLevel.error
            )
            return False

        except Exception as e:
            self.debug.exception(e)
            return False

        return True
