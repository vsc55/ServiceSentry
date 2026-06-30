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
from lib.core.object_base import ObjectBase

__all__ = ['Telegram', 'send_telegram']

_API_SEND = 'https://api.telegram.org/bot{token}/sendMessage'


def send_telegram(token, chat_id, text, *, parse_mode=None, timeout=10):
    """Low-level one-shot POST to the Telegram *sendMessage* API.

    Shared by the queued :class:`Telegram` client (used by the monitor) and the
    one-shot :mod:`lib.notify.telegram_notify` sender (used by the dispatcher),
    so the raw API call lives in a single place.  *token* / *chat_id* are
    assumed non-empty — callers validate as they see fit.

    Returns ``(ok, status_code, info)``: ``ok`` is ``True`` only on HTTP 200;
    ``info`` is ``'sent'`` or an error description (Telegram's ``description``
    field, or ``HTTP <code>``).  Propagates :class:`requests.RequestException`
    so each caller keeps its own error handling.
    """
    data = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        data['parse_mode'] = parse_mode
    result = requests.post(_API_SEND.format(token=token), data=data, timeout=timeout)
    if result.status_code == 200:
        return True, 200, 'sent'
    try:
        desc = result.json().get('description', f'HTTP {result.status_code}')
    except Exception:  # pylint: disable=broad-except
        desc = f'HTTP {result.status_code}'
    return False, result.status_code, desc


class Telegram(ObjectBase):
    """ Class To Send Messages To Api Telegram. """

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        # Set values
        self.group_messages = False
        self.count_msg = 0
        self.count_msg_send = 0
        self._count_lock = threading.Lock()
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
        with self._count_lock:
            self.count_msg += 1

    def send_message_end(self, hostname, public_url='', timeout=30):
        """ Add a summary message and wait up to *timeout* seconds for the queue to drain. """
        if self.count_msg > 0:
            s_message = f"ℹ️ Summary *{hostname}*, get *{self.count_msg}* new Message. ☝️☝️☝️"
            if public_url:
                s_message += f"\n🔗 [Status Page]({public_url}/status)"
            self.queue_msg.put(s_message)
            with self._count_lock:
                self.count_msg += 1

        join_thread = threading.Thread(target=self.queue_msg.join, daemon=True)
        join_thread.start()
        join_thread.join(timeout=timeout)
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
                        with self._count_lock:
                            self.count_msg_send += 1

                    msg_group.clear()
                continue

            # modo NO agrupado → envío inmediato
            if not self.group_messages:
                self.debug.print(f"Telegram > Send >> Msg: {msg}")
                self.api_send_message(msg)
                with self._count_lock:
                    self.count_msg_send += 1
                self.queue_msg.task_done()

        # Flush de mensajes agrupados pendientes al cerrar
        if self.group_messages and msg_group:
            full_msg = "\n".join(msg_group)
            self.api_send_message(full_msg)
            for _ in msg_group:
                self.queue_msg.task_done()
                with self._count_lock:
                    self.count_msg_send += 1
            msg_group.clear()

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
            ok, code_return, _info = send_telegram(
                self.token, self.chat_id, message, parse_mode='Markdown')
            return ok, code_return

        except requests.RequestException as e:
            self.debug.exception(e)
            return False, -10
