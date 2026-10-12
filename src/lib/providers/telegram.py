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
"""Low-level Telegram *sendMessage* helper.

A single one-shot sender shared by every Telegram consumer: the notification
dispatcher (:mod:`lib.core.notify.telegram`), the monitor's cycle notifier
(:class:`lib.core.notify.monitor_notifier.MonitorNotifier`) and the test-message
route.  There is no background/queued client — sending is synchronous.
"""

import time

import requests

__all__ = ['send_telegram']

_API_SEND = 'https://api.telegram.org/bot{token}/sendMessage'
#: The longest a 429 is waited out (s) — Telegram's ``retry_after`` is honoured up to it.
_RETRY_AFTER_MAX = 30
#: How many times a 429 is retried before it is returned as the failure it is.
_RETRY_429 = 2


def redact(text: str, token: str) -> str:
    """*text* with the bot *token* replaced by ``***``."""
    text = str(text)
    return text.replace(token, '***') if token else text


def _retry_after(result) -> float:
    """Seconds Telegram asked to wait in a 429 (``parameters.retry_after``), capped."""
    try:
        wait = float(((result.json() or {}).get('parameters') or {}).get('retry_after') or 1)
    except Exception:  # pylint: disable=broad-except
        wait = 1.0
    return max(0.0, min(float(_RETRY_AFTER_MAX), wait))


def send_telegram(token, chat_id, text, *, parse_mode=None, timeout=10):
    """Low-level one-shot POST to the Telegram *sendMessage* API.

    *token* / *chat_id* are assumed non-empty — callers validate as they see fit.

    Returns ``(ok, status_code, info)``: ``ok`` is ``True`` only on HTTP 200;
    ``info`` is ``'sent'`` or an error description (Telegram's ``description``
    field, or ``HTTP <code>``).  Propagates :class:`requests.RequestException`
    so each caller keeps its own error handling.
    """
    data = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        data['parse_mode'] = parse_mode
    attempt = 0
    while True:
        try:
            result = requests.post(_API_SEND.format(token=token), data=data, timeout=timeout)
        except requests.RequestException as exc:
            # Raised again with the token cut out: the bot token is in the URL, and the
            # driver's message quotes the URL («Max retries exceeded with url:
            # /bot123:ABC/sendMessage») — which went to the debug log and, for event rules,
            # into the notification log shown in the panel.
            raise type(exc)(redact(str(exc), token)) from None
        # 429 is Telegram saying "not now, in N seconds" — a flood of alerts in one cycle
        # (an outage) is exactly when it says it. Taken as a failure, the rest of the
        # outage's messages were lost; it is waited out (capped) and the message re-sent.
        if result.status_code != 429 or attempt >= _RETRY_429:
            break
        attempt += 1
        time.sleep(_retry_after(result))
    if result.status_code == 200:
        return True, 200, 'sent'
    try:
        desc = result.json().get('description', f'HTTP {result.status_code}')
    except Exception:  # pylint: disable=broad-except
        desc = f'HTTP {result.status_code}'
    return False, result.status_code, desc
