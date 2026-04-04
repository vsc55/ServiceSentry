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
""" Class to check the return of the modules. """

__all__ = ['ReturnModuleCheck']


class ReturnModuleCheck:

    """ Main Class. """

    def __init__(self):
        """ Inicializa Objeto. """
        self._dict_return = {}

    @property
    def list(self) -> dict:
        """ Return the list of returns. """
        return self._dict_return or {}

    @property
    def count(self) -> int:
        """
        Return the number of returns that contains the object.

        :return: Number of returns.
        """
        return len(self.list)

    def items(self):
        """
        Return the list of items in the return dictionary.

        :return: List of items.
        """
        return self.list.items()

    def keys(self):
        """
        Return the list of keys in the return dictionary.

        :return: List of keys.
        """
        return self.list.keys()

    def is_exist(self, key: str) -> bool:
        """ Check if the key exist in the return list."""
        return key in self.list

    def set(
            self, key: str,
            status: bool = True,
            message='',
            send_msg: bool = True,
            other_data: dict = None
        ) -> bool:
        """
        Create a new return and update it if it already exists.

        :param key: Key of the return
        :param status: True if the status is OK, False if the status is Error/Warning/Etc.. 
                       anything that is not OK.
        :param message: Message to be sent via telegram.
        :param send_msg: True if the message should be sent, False if the message should not
                         be sent.
        :param other_data: Dictionary with other data.
        :return: True if saved successfully, False if something went wrong.
        """
        if key:
            if other_data is None:
                other_data = {}
            self._dict_return[key] = {}
            self._dict_return[key]['status'] = status
            self._dict_return[key]['message'] = message
            self._dict_return[key]['send'] = send_msg
            self._dict_return[key]['other_data'] = other_data
            return self.is_exist(key)
        return False

    def update(self, key: str, option: str, value) -> bool:
        """
        Update one of the properties of an existing return.

        :param key: Key of the return
        :param option: Name of the option.
        :param value: New value.
        :return: True if everything went well, False if something went wrong.
        """

        if key:
            if isinstance(option, str) and option.lower() in {
                "status",
                "message",
                "send",
                "other_data"
                }:
                if self.is_exist(key):
                    self._dict_return[key][option] = value
                    return True

        return False

    def remove(self, key: str) -> bool:
        """
        Remove the specified key from the return list.

        :param key: Key to remove.
        :return: True if removed successfully, False if something went wrong.
        """
        if self.is_exist(key):
            del self._dict_return[key]
            return True
        return False

    def get(self, key: str) -> dict:
        """
        Get the dictionary of the key we are looking for.

        :param key: Key we are looking for.
        :return: Dictionary with the data of the key we are looking for, and if the 
                 key does not exist, returns an empty dictionary.
        """
        if self.is_exist(key):
            return self.list[key]
        return {}

    def get_status(self, key: str) -> bool:
        """ Get the status of the specified key. """
        return self.get(key).get('status', False)

    def get_message(self, key: str) -> str:
        """ Get the message of the specified key. """
        return self.get(key).get('message', '')

    def get_send(self, key: str) -> bool:
        """ Get the send status of the specified key. """
        return self.get(key).get('send', True)

    def get_other_data(self, key: str) -> dict:
        """ Get the other_data of the specified key. """
        return self.get(key).get('other_data', {})
