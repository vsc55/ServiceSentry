#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
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
"""
Class to manage a dictionary of files and paths.

Example:
    >>> t = DictFilesPath()
    >>> t.set("test.tmp", "/tmp/test.tmp")
    True
    >>> print(t.files)
    {'test.tmp': '/tmp/test.tmp'}

    >>> t.set("test.tmp", "/tmp/test_dir/test.tmp")
    True
    >>> print(t.files)
    {'test.tmp': '/tmp/test_dir/test.tmp'}

    >>> t.set("test2.tmp", "/tmp/test2.tmp")
    True
    >>> print(t.files)
    {'test.tmp': '/tmp/test_dir/test.tmp', 'test2.tmp': '/tmp/test2.tmp'}

    >>> t.remove("test2.tmp")
    True
    >>> print(t.files)
    {'test.tmp': '/tmp/test_dir/test.tmp'}

    >>> print(t.find("test.tmp", "/dev/null"))
    /tmp/test_dir/test.tmp

    >>> print(t.find("test00.tmp", "/dev/null"))
    /dev/null

    >>> t.clear()
    >>> print(t.files)
    {}

    >>> t.set("a", "/tmp/a")
    True
    >>> if "a" in t:
    ...     print(t["a"])
    /tmp/a

    >>> del t["a"]
    >>> print(t.files)
    {}

    >>> t.set("a", "/tmp/a")
    True
    >>> t.set("b", "/tmp/b")
    True
    >>> print(t.files)
    {'a': '/tmp/a', 'b': '/tmp/b'}
    >>> print("a" in t)
    True
    >>> print("b" in t)
    True
    >>> print("c" in t)
    False
"""

from typing import Iterator

__author__ = "Javier Pastor"
__copyright__ = "Copyright © 2019, Javier Pastor"
__credits__ = "Javier Pastor"
__license__ = "GPL"
__version__ = "0.1.0"
__maintainer__ = 'Javier Pastor'
__email__ = "python[at]cerebelum[dot]net"
__status__ = "Development"

__all__ = ['DictFilesPath']


class DictFilesPath:

    """ Class to manage a dictionary of files and paths. """

    def __init__(self):
        """ Initializes the object. """
        self._files = {}

    def clear(self):
        """ Clear the files dictionary. """
        self._files.clear()


    def __contains__(self, key: str) -> bool:
        """ Return if the specified key exists in the files dictionary. """
        return key in self._files

    def __getitem__(self, key: str) -> str:
        """ Return the value associated with the specified key in the files dictionary. """
        return self._files[key]

    def __setitem__(self, key: str, value: str):
        """ Set the value associated with the specified key in the files dictionary. """
        self._files[key] = value

    def __delitem__(self, key: str):
        """ Remove the specified key from the files dictionary. """
        del self._files[key]

    def __iter__(self) -> Iterator[str]:
        """ Return an iterator over the keys in the files dictionary. """
        return iter(self._files)

    def __len__(self) -> int:
        """ Return the number of items in the files dictionary. """
        return len(self._files)

    def find(self, file_find: str, default_value: str = '') -> str:
        """
        Searches for the file in the list and returns the associated path. 
        If not found, returns the specified default value.
        """
        return self._files.get(file_find, default_value)

    @property
    def files(self) -> dict:
        """ Return the dictionary of files. """
        return self._files

    def set(self, file_name: str, file_path: str) -> bool:
        """ Adds or updates the specified file and path in the list. """
        if not file_name:
            return False
        self[file_name] = file_path
        return True

    def remove(self, file_find: str) -> bool:
        """ Removes the specified file from the list. """
        try:
            del self[file_find]
            return True
        except KeyError:
            return False

    def copy(self):
        """ Return a copy of the files dictionary. """
        return self._files.copy()

    def is_exist(self, file_find: str) -> bool:
        """ Checks if the specified file is in the list or not. """
        return file_find in self._files
