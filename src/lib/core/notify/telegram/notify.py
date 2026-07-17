#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synchronous Telegram sender for the notification dispatcher.

Mirrors email_notify / webhook_notify: a module-level ``_dispatch(cfg, **kwargs)``
that sends one message and returns ``(ok, message)``.  The dispatcher chooses
*whether* to call this (routing matrix or an event rule's channels); here we just
send.  (The monitor sends through the same synchronous ``send_telegram`` at cycle-flush
time via its ``MonitorNotifier``; this is the one-shot path for web-admin/event
notifications — there is no queued/background Telegram client.)
"""

from __future__ import annotations

import html

from lib.core.notify.formatting import event_icon, event_title
from lib.i18n import translate
from lib.providers.telegram import send_telegram


def _esc(text) -> str:
    """HTML-escape a dynamic field for Telegram's HTML parse mode (& < > only)."""
    return html.escape(str(text or ''), quote=False)


def _format(kind: str, module: str, item: str, status: str,
            message: str, timestamp: str, lang: str = '', cfg: dict = None) -> str:
    """Build a Telegram *HTML* message: an icon + bold event title (in the system notification
    ``lang``, admin override honoured via *cfg*), the target as inline code, the body as a quote
    block and a dimmed timestamp.  HTML is robust (only ``& < >`` need escaping — done per field),
    unlike Markdown which the module text (``pch_cannonlake``, ``*PVE02*``) routinely breaks."""
    lines = [f"{event_icon(kind)} <b>{_esc(event_title(kind, lang, cfg))}</b>"]
    target = '/'.join(p for p in (module, item) if p)
    if target:
        lines.append(f"🖥 <code>{_esc(target)}</code>")
    if status:
        lines.append(f"🏷 {_esc(status)}")
    if message:
        lines.append(f"<blockquote>{_esc(message)}</blockquote>")
    if timestamp:
        lines.append(f"🕒 <i>{_esc(timestamp)}</i>")
    return '\n'.join(lines)


def _dispatch(cfg: dict, *, kind: str = '', module: str = '', item: str = '',
              status: str = '', message: str = '', timestamp: str = '',
              lang: str = '', cfg_all: dict = None) -> tuple[bool, str]:
    cfg = cfg or {}
    token = str(cfg.get('token') or '').strip()
    chat_id = str(cfg.get('chat_id') or '').strip()
    if not token or not chat_id:
        return False, translate(lang, 'telegram_not_configured')
    # HTML parse mode — every dynamic field is escaped in _format, so arbitrary
    # message content renders safely (and *_/underscores no longer break parsing).
    try:
        ok, _status, info = send_telegram(
            token, chat_id,
            _format(kind, module, item, status, message, timestamp, lang, cfg_all),
            parse_mode='HTML')
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)
    return ok, info
