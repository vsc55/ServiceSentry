#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synchronous Telegram sender for the notification dispatcher.

Mirrors email_notify / webhook_notify: a module-level ``_dispatch(cfg, **kwargs)``
that sends one message and returns ``(ok, message)``.  The dispatcher chooses
*whether* to call this (routing matrix or an event rule's channels); here we just
send.  (The monitor uses the queued ``lib.telegram.Telegram`` for its own runs;
this is the simple one-shot path for web-admin/event notifications.)
"""

from __future__ import annotations

import requests as req

_API = 'https://api.telegram.org/bot{token}/sendMessage'


def _format(kind: str, module: str, item: str, status: str,
            message: str, timestamp: str) -> str:
    head = f"[ServiceSentry] {kind.upper()}".strip()
    lines = [head]
    target = '/'.join(p for p in (module, item) if p)
    if target:
        lines.append(target)
    if status:
        lines.append(f"Status: {status}")
    if message:
        lines.append(message)
    if timestamp:
        lines.append(timestamp)
    return '\n'.join(lines)


def _dispatch(cfg: dict, *, kind: str = '', module: str = '', item: str = '',
              status: str = '', message: str = '', timestamp: str = '') -> tuple[bool, str]:
    cfg = cfg or {}
    token = str(cfg.get('token') or '').strip()
    chat_id = str(cfg.get('chat_id') or '').strip()
    if not token or not chat_id:
        return False, 'Telegram not configured (token/chat_id missing)'
    # Plain text (no parse_mode) so arbitrary message content can't break parsing.
    try:
        r = req.post(_API.format(token=token),
                     data={'chat_id': chat_id,
                           'text': _format(kind, module, item, status, message, timestamp)},
                     timeout=10)
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)
    if r.status_code == 200:
        return True, 'sent'
    try:
        desc = r.json().get('description', f'HTTP {r.status_code}')
    except Exception:  # pylint: disable=broad-except
        desc = f'HTTP {r.status_code}'
    return False, desc
