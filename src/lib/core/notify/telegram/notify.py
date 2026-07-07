#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synchronous Telegram sender for the notification dispatcher.

Mirrors email_notify / webhook_notify: a module-level ``_dispatch(cfg, **kwargs)``
that sends one message and returns ``(ok, message)``.  The dispatcher chooses
*whether* to call this (routing matrix or an event rule's channels); here we just
send.  (The monitor uses the queued ``lib.providers.telegram.Telegram`` for its own runs;
this is the simple one-shot path for web-admin/event notifications.)
"""

from __future__ import annotations

from lib.providers.telegram import send_telegram


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
        ok, _status, info = send_telegram(
            token, chat_id, _format(kind, module, item, status, message, timestamp))
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)
    return ok, info
