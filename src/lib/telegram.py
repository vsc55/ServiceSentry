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
# https://apps.timwhitlock.info/emoji/tables/unicode
""" Class to send messages to Telegram. """

import queue
import threading

import requests

from lib.debug import DebugLevel
from lib.object_base import ObjectBase

__all__ = ['Telegram']


class Telegram(ObjectBase):
    """ Class To Send Messages To Api Telegram. """

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        # Set values
        self.group_messages = False
        self.count_msg = 0
        self.count_msg_send = 0
        self.stop = False
        self.queue_msg = queue.Queue()
        self.pool_send_msg = None
        self._init_pool()

    def _init_pool(self):
        self.stop = False
        self.pool_send_msg = threading.Thread(target=self.pool_run, daemon=True)
        self.pool_send_msg.start()

    def clear(self):
        """ Clear the message list and reset the count. """
        self.count_msg = 0
        self.count_msg_send = 0

    def reset_count(self):
        """ Reset the message count. """
        self.count_msg = 0
        self.count_msg_send = 0

    def send_message(self, message):
        """ Add a message to the list. """
        self.queue_msg.put(message)
        self.count_msg += 1

    def send_message_end(self, hostname):
        """ Add a message to the list and wait for the list to be empty. """
        if self.count_msg > 0:
            s_message = f"ℹ️ Summary *{hostname}*, get *{self.count_msg}* new Message. ☝️☝️☝️"
            self.queue_msg.put(s_message)
            self.count_msg += 1

        self.queue_msg.join()
        self.reset_count()

    @property
    def is_queue_empty(self) -> bool:
        """ Return True if the message queue is empty, False otherwise. """
        return self.queue_msg.empty()

    def close(self):
        """ Stop the pool and wait for it to finish. """
        self.stop = True
        if self.pool_send_msg:
            self.pool_send_msg.join(timeout=1)

    def pool_run(self):
        """ Pool to send messages to Telegram. """
        msg_group = []

        while not self.stop:
            try:
                msg = self.queue_msg.get(timeout=0.1)
                msg_group.append(msg)
            except queue.Empty:
                if self.group_messages and msg_group:
                    full_msg = "\n".join(msg_group)
                    self.api_send_message(full_msg)

                    # marcar todos como procesados
                    for _ in msg_group:
                        self.queue_msg.task_done()
                        self.count_msg_send += 1

                    msg_group.clear()
                continue

            # modo NO agrupado → envío inmediato
            if not self.group_messages:
                self.debug.print(f"Telegram > Send >> Msg: {msg}")
                self.api_send_message(msg)
                self.count_msg_send += 1
                self.queue_msg.task_done()

    def api_send_message(self, message):
        """
        Send a message to Telegram using the API.

        Return codes:
        # >0 = HTTP Status_Code
        # -1 = Token is Null
        # -2 = Chat Id is Null
        # -3 = Token And Chat Id is Null
        # -10 = Exception in Request
        """
        code_return = 0

        if not message or not self.token or not self.chat_id:
            if not self.token:
                self.debug.print(
                    "Telegram >> API >> Error: Telegram Token is Null", DebugLevel.error
                )
                code_return -= 1
            if not self.chat_id:
                self.debug.print(
                    "Telegram >> API >> Error: Telegram Chat ID is Null", DebugLevel.error
                )
                code_return -= 2
            return False, code_return

        try:
            result = requests.post(
                f'https://api.telegram.org/bot{self.token}/sendMessage',
                data={
                    'chat_id': self.chat_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                },
                timeout=10
            )
            code_return = result.status_code
            return code_return == 200, code_return

        except requests.RequestException as e:
            self.debug.exception(e)
            return False, -10
