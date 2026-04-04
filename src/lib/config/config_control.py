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

"""Configuration module"""

import collections
import datetime

from lib.config.config_store import ConfigStore
from lib.config.config_type_return import ConfigTypeReturn

__all__ = ['ConfigControl']


class ConfigControl(ConfigStore):

    """Class to Storage and processing of configuration parameters."""

    def __init__(self, file, init_data: dict = None):
        """ Init object. """
        self._load = None
        self._update = None
        super().__init__(file)
        self.data = init_data

    @property
    def data(self) -> dict:
        """
        Return the configuration data.
        If the data is None, it will return an empty dictionary.
        """
        if self._data is None:
            return {}
        return self._data

    @data.setter
    def data(self, val: dict | None = None):
        """ Set the configuration data. """
        self._update = datetime.datetime.now()
        self._data = val

    @property
    def is_data(self) -> bool:
        """ Return True if the configuration data is not None, False otherwise. """
        return self._data is not None

    @property
    def is_changed(self) -> bool:
        """
        Return True if the configuration data has been changed since the last load,
        False otherwise.
        """
        if not self._update:
            return False

        if not self._load:
            # Data inserted manually, no file has been read.
            return True

        return self._update > self._load

    @property
    def is_load(self) -> bool:
        """
        Return True if the configuration data has been loaded from the file,
        False otherwise.
        """
        return self._load is not None

    def read(self, return_data=True, def_return=None) -> dict | None: # pylint: disable=arguments-renamed
        """ Read the configuration from the file. """
        self.data = super().read(def_return)

        time_read = datetime.datetime.now() if self.is_data else None

        self._load = time_read
        self._update = time_read

        if return_data:
            return self.data

    def save(self, data=None) -> bool:
        """ Save the configuration to the file. """
        if data is None:
            data = self.data

        if super().save(data):
            time_save = datetime.datetime.now()
            self._load = time_save
            self._update = time_save
            return True
        return False

    @staticmethod
    def convert_find_key_to_list(find_key, str_split: str = None) -> list:
        """ Convert the find_key to a list. """
        list_return = []
        if isinstance(find_key, str):
            if str_split is None:
                list_return = find_key.split()
            else:
                list_return = find_key.split(str_split)

        elif isinstance(find_key, list):
            list_return = find_key.copy()

        elif isinstance(find_key, tuple):
            list_return = list(find_key)

        else:
            raise TypeError(
                f'Invalid type: find_key must be a string, list or tuple, not {type(find_key)}.'
            )

        return list_return

    def _convert_list_to_dict(self, list_items, val) -> dict:
        """ Convert a list to a dictionary with the last element as the value. """
        dict_return: dict = {}
        if isinstance(list_items, list):
            target = list_items.pop(0)
            if list_items:
                dict_return[target] = self._convert_list_to_dict(list_items, val)
            else:
                dict_return[target] = val
        else:
            dict_return[list_items] = val
        return dict_return

    def _update_value_find_key(self, source, overrides) -> dict:
        """ Update the value of a nested dictionary of varying depth. """
        # https://stackoverflow.com/questions/3232943/update-value-of-a-nested-dictionary-of-varying-depth
        for key, val in overrides.items():
            if isinstance(source, collections.abc.Mapping):
                if isinstance(val, collections.abc.Mapping):
                    source[key] = self._update_value_find_key(source.get(key, {}), val)
                else:
                    source[key] = val
            else:
                source: dict = {key: overrides[key]}
        return source

    def get_conf(
            self,
            find_key,
            def_val=None,
            str_split: str = None,
            data_dict: dict = None,
            r_type: ConfigTypeReturn = ConfigTypeReturn.STR
        ) -> dict | list | tuple | int | bool | str:
        """ Return value of the key that we are looking for and if this key does not exist, it
        will return def_val. If def_val is None it will return an object (empty) of the type
        that is defined in r_type.

        :param find_key: the target keys structure, which should be present. Support type [string | tuple | list].
        :param def_val: It is the value that returns if the key we are looking for is not found.
        :param str_split: character that will be used to separate find_key if it is string type in the list conversion.
        :param data_dict: the dictionary to be searched in. By default the self.data will be used.
        :param r_type: It is the type of object (empty), which will return if def_val is not defined or def_val is None and the key we are looking for was not found. For example, if we specify r_type = list, it returns [].
        :raises TypeError: if find_key is not a string, tuple or list or if r_type is not a string, list, dict, tuple, int or bool.

        Note:
            Parameter 'find_key' is not support type 'dict'.
            https://docs.python.org/3/library/collections.html#collections.OrderedDict

            Ordered dictionaries are just like regular dictionaries but have some
            extra capabilities relating to ordering operations. They have become less
            important now that the built-in dict class gained the ability to remember
            insertion order (this new behavior became guaranteed in Python 3.7).

        Example:
            >>> x = ConfigControl(None)
            >>> x.data = { 'level1': { 'level2': 'OK' } }
            >>> x.get_conf(['level1', 'level2'], 'Not Exist!')
            'OK'
            >>> x.get_conf(('level1', 'level2'), 'Not Exist!')
            'OK'
            >>> x.get_conf(('level1', 'level2', 'level3'), 'Not Exist!')
            'Not Exist!'
            >>> x.get_conf('level1', 'Not Exist!')
            {'level2': 'OK'}
            >>> x.get_conf('level2', r_type=ConfigTypeReturn.LIST)
            []
        """

        if data_dict is None:
            data_dict = self.data

        data_return = None
        if data_dict:
            keys = self.convert_find_key_to_list(find_key, str_split)

            work_dict = data_dict
            while keys:
                target = keys.pop(0)
                if isinstance(work_dict, dict):
                    if target in work_dict:
                        if not keys:
                            # this is the last element in the find_key, and it is in the data_dict
                            data_return = work_dict[target]
                            break

                        # not the last element of find_key, change the temp var
                        work_dict = work_dict[target]
                    else:
                        continue
                else:
                    continue

        if data_return is not None:
            return data_return

        if def_val is None:
            match r_type:
                case ConfigTypeReturn.LIST:
                    return []
                case ConfigTypeReturn.DICT:
                    return {}
                case ConfigTypeReturn.TUPLE:
                    return ()
                case ConfigTypeReturn.INT:
                    return 0
                case ConfigTypeReturn.BOOL:
                    return False
                case ConfigTypeReturn.STR:
                    return ''
                case _:
                    raise TypeError(f'Invalid type: r_type must be a string, list, dict, tuple, int or bool, not supported type ({type(r_type)}).')
        return def_val

    def is_exist_conf(self, find_key, str_split: str = None, data_dict: dict = None) -> bool:
        """ Return True if the given find_key is present within the structure of the source dictionary, False otherwise.

        The find_key format is list, tuple, or string in which the str_split parameter is used as the deleting character.

        :param find_key: the target keys structure, which should be present. Support type [string | tuple | list].
        :param str_split: character that will be used to separate find_key if it is string type in the list conversion.
        :param data_dict: the dictionary to be searched in.
        :returns Boolean: is the find_key structure present in data.
        :raises TypeError: if find_key is not a string, tuple or list

        Note:
            Parameter 'find_key' is not support type 'dict'.
            https://docs.python.org/3/library/collections.html#collections.OrderedDict

            Ordered dictionaries are just like regular dictionaries but have some
            extra capabilities relating to ordering operations. They have become less
            important now that the built-in dict class gained the ability to remember
            insertion order (this new behavior became guaranteed in Python 3.7).

        Example:
            >>> x = ConfigControl(None)
            >>> x.data = { 'level1': { 'level2': 'OK' } }
            >>> x.is_exist_conf(['level1', 'level2'])
            True
            >>> x.is_exist_conf(('level1', 'level2'))
            True
            >>> x.is_exist_conf(('level1', 'level2','level3'))
            False
            >>> x.is_exist_conf('level1')
            True
            >>> x.is_exist_conf('level1:level2', ':')
            True
            >>> x.is_exist_conf('level2:level1', ':', { 'level2': { 'level1': 'OK' } })
            True
            >>> x.is_exist_conf('level2:level1', ':', { 'level3': { 'level1': 'OK' } })
            False

        """

        if data_dict is None:
            data_dict = self.data

        if find_key and data_dict:
            keys = self.convert_find_key_to_list(find_key, str_split)
            work_dict = data_dict
            while keys:
                target = keys.pop(0)
                if isinstance(work_dict, dict):
                    if target in work_dict:
                        if not keys:
                            # this is the last element in the find_key, and it is in the data_dict
                            return True

                        # not the last element of find_key, change the temp var
                        work_dict = work_dict[target]
                    else:
                        return False
                else:
                    return False
        return False

    def set_conf(self, find_key, val, str_split: str = None, data_dict: dict = None):
        """ Return true if the process was successful, False otherwise.

        The find_key format is list, tuple, or string in which the str_split parameter is used as the deleting character.

        :param find_key: the target keys structure, which should be present. Support type [string | tuple | list].
        :param val: new value
        :param str_split: character that will be used to separate find_key if it is string type in the list conversion.
        :param data_dict: the dictionary to be searched in. By default the self.data will be used.
        :returns Boolean: if it has been processed correctly.
        :returns Dict: if it has been processed correctly and data_dict is a dict.
        :raises TypeError: if find_key is not a string, tuple or list

        Note:
            Parameter 'find_key' is not support type 'dict'.
            https://docs.python.org/3/library/collections.html#collections.OrderedDict

            Ordered dictionaries are just like regular dictionaries but have some
            extra capabilities relating to ordering operations. They have become less
            important now that the built-in dict class gained the ability to remember
            insertion order (this new behavior became guaranteed in Python 3.7).

        Example:
            >>> x = ConfigControl(None)
            >>> x.set_conf('level1', 'OK')
            True
            >>> x.data
            {'level1': 'OK'}
            >>> x.set_conf(['level1','level2'], 'OK')
            True
            >>> x.data
            {'level1': {'level2': 'OK'}}
            >>> x.set_conf('level1:level2:level3', 'OK',':')
            True
            >>> x.data
            {'level1': {'level2': {'level3': 'OK'}}}
            >>> x.set_conf('level0', 'OK', data_dict = {'level1': 'OK'})
            {'level1': 'OK', 'level0': 'OK'}

        """

        if find_key:
            keys = self.convert_find_key_to_list(find_key, str_split)
            if data_dict is not None:
                work_dict = data_dict
            elif self.data is not None:
                work_dict = self.data
            else:
                work_dict = {}

            key_update = self._convert_list_to_dict(keys, val)
            work_dict = self._update_value_find_key(work_dict, key_update)

            if data_dict is not None:
                return work_dict

            self.data = work_dict
            return True
        return False
