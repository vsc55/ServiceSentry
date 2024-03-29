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
#
# http://www.forosdelweb.com/f130/resuelto-problema-con-hilos-malditos-hilos-python-xd-831605/


import threading
import requests
from lib.debug import DebugLevel
from lib import ObjectBase
from time import sleep

__all__ = ['Telegram']


class Telegram(ObjectBase):

    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        # Set values
        self.list_msg = None
        self.count_msg = None
        self.count_msg_send = None
        self.group_messages = None
        self.stop = None
        self.__default()
        self.__init_pool()

    def __init_pool(self):
        self.stop = False
        self.pool_send_msg = threading.Thread(target=self.pool_run, daemon=True)
        self.pool_send_msg.start()

    @property
    def group_messages(self) -> bool:
        return self.__group_messages

    @group_messages.setter
    def group_messages(self, val: bool):
        self.__group_messages = val

    def __default(self):
        self.group_messages = False
        self.clear()

    def clear(self):
        self.list_msg = []
        self.reset_count()

    def reset_count(self):
        self.count_msg = 0
        self.count_msg_send = 0

    def send_message(self, message):
        self.add_list(message)

    def send_message_end(self, hostname):
        if self.count_msg > 0:
            s_message = "Summary *{0}*, get *{1}* new Message.".format(hostname, self.count_msg)
            s_message = "{0} {1} {2}{2}{2}".format(u'\U00002139', s_message, u'\U0000261D')
            self.add_list(s_message)
            # Sleep para asegurarnos de que el mensaje anterior esta en la lista antes de iniciar el siguiente While.
            sleep(1)

        # Esperamos a que la lista de mensajes esta vacía.
        while True:
            if self.is_entry_list:
                break

        self.reset_count()

    @property
    def is_entry_list(self) -> bool:
        if self.list_msg and len(self.list_msg) > 0:
            return False
        return True

    def add_list(self, message):
        # Efectuamos insert para mantener el orden.
        if self.list_msg is None:
            self.clear()
        self.list_msg.append(message)
        self.count_msg += 1

    def pool_run(self):
        self.stop = False
        msg_group = ''
        while_run = True
        while while_run:
            if not self.is_entry_list:
                msg = self.list_msg.pop(0)
                self.debug.print("Telegram > Send >> Msg: {0}".format(msg))
                if self.group_messages:
                    msg_group += msg + "\n"
                else:
                    # TODO: Pendiente que hacer cuando falle el envío.
                    self.api_send_message(msg)
                self.count_msg_send += 1
            else:
                if self.group_messages:
                    if msg_group:
                        self.api_send_message(msg_group)
                        msg_group = ''
                else:
                    if self.stop:
                        while_run = False
        return

    def api_send_message(self, message):
        code_return = 0
        if message and self.token and self.chat_id:
            result = requests.post('https://api.telegram.org/bot{0}/sendMessage'.format(self.token),
                                   data={'chat_id': self.chat_id, 'text': message, 'parse_mode': 'Markdown'})
            code_return = result.status_code
        else:
            if not self.token:
                self.debug.print("Telegram >> API >> Error: Telegram Token is Null", DebugLevel.error)
                code_return -= 1
            if not self.chat_id:
                self.debug.print("Telegram >> API >> Error: Telegram Chat ID is Null", DebugLevel.error)
                code_return -= 2

        # >0 = HTTP Status_Code
        # -1 = Token is Null
        # -2 = Chat Id is Null
        # -3 = Token And Chat Id is Null
        return True if code_return == 200 else False, code_return

# https://apps.timwhitlock.info/emoji/tables/unicode
