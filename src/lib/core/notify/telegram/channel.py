#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram notification channel — self-registers with the core registry.

* ``send``  — one alert via :func:`lib.core.notify.telegram.notify._dispatch`.
* ``flush`` — a monitor cycle's alerts as emoji lines (grouped into Issues/Recovered
  sections when ``telegram|group_messages`` is on), batched under Telegram's size cap.

Telegram is sent WITHOUT parse_mode: module messages contain ``_``/``*`` (e.g.
``pch_cannonlake``, ``*PVE02*``) that break Markdown entity parsing — and when many are
concatenated into one grouped message the whole message is rejected.  Plain text is
robust; emojis still render and URLs auto-link.  :func:`plain` drops the module Markdown.
"""

from __future__ import annotations

import html

from lib.core.notify.formatting import ICON, notify_lang, plain
from lib.core.notify.registry import Channel, register_channel

_TG_LIMIT = 3800   # keep grouped messages under Telegram's 4096-char hard cap


def _esc(text) -> str:
    """HTML-escape a dynamic field for Telegram's HTML parse mode (& < > only)."""
    return html.escape(str(text or ''), quote=False)


def send(router, cfg, *, kind='', module='', item='', status='', message='',
         timestamp='', **_extra) -> tuple:
    from lib.core.notify.telegram import notify as telegram_notify  # noqa: PLC0415
    return telegram_notify._dispatch(cfg.get('telegram') or {}, kind=kind, module=module,
                                     item=item, status=status, message=message,
                                     timestamp=timestamp, lang=notify_lang(cfg), cfg_all=cfg)


# ── grouped monitor flush (HTML) ─────────────────────────────────────────────
def _tg_line(hostname: str, a: dict) -> str:
    return (f"{ICON.get(a['kind'], '❎')} 🖥 <b>{_esc(hostname)}</b>: "
            f"{_esc(plain(a['message']))}")


def _summary_line(hostname: str, n: int, public_url: str) -> str:
    s = f"ℹ️ <b>Summary</b> · <b>{_esc(hostname)}</b> · {n} new message(s)"
    if public_url:
        url = f"{public_url.rstrip('/')}/status"
        s += f'\n🔗 <a href="{_esc(url)}">{_esc(url)}</a>'
    return s


def _chunk(lines: list[str]):
    """Yield newline-joined chunks that each stay under Telegram's size cap."""
    buf: list[str] = []
    size = 0
    for ln in lines:
        if buf and size + len(ln) + 1 > _TG_LIMIT:
            yield '\n'.join(buf)
            buf, size = [], 0
        buf.append(ln)
        size += len(ln) + 1
    if buf:
        yield '\n'.join(buf)


def _tg_sections(cfg, alerts) -> list:
    """Group the alerts into Issues / Recovered sections, each sorted by item — the same
    grouping as the email digest, as Telegram lines (used when ``group_messages`` is on)."""
    from lib.core.notify.email.templates import get_strings  # noqa: PLC0415
    s = get_strings(notify_lang(cfg))

    def _key(a):
        return ((a['item'] or '').lower(), (a['module'] or '').lower())
    bad = sorted([a for a in alerts if a['kind'] in ('down', 'warn')], key=_key)
    good = sorted([a for a in alerts if a['kind'] == 'recovery'], key=_key)
    out = []
    for icon, title, rows in (('⚠️', s.get('summary_issues', 'Issues'), bad),
                              ('✅', s.get('summary_recovered', 'Recovered'), good)):
        if not rows:
            continue
        if out:
            out.append('')   # blank line separates the two sections
        out.append(f"{icon} <b>{_esc(title)} ({len(rows)})</b>")
        for a in rows:
            # One card per alert: a bold header (status icon + item) with the message on
            # the line below, wrapped in a quote block for breathing room — the whole card
            # is a single list entry (internal newline) so _chunk never splits it.
            head = a['item'] or a['module'] or ''
            head = f"{ICON.get(a['kind'], '❎')} <b>{_esc(head)}</b>" if head \
                else ICON.get(a['kind'], '❎')
            out.append('')   # blank line before each card
            out.append(f"<blockquote>{head}\n{_esc(plain(a['message']))}</blockquote>")
    return out


def flush(router, cfg, alerts, hostname, public_url) -> tuple:
    from lib.providers.telegram import send_telegram  # noqa: PLC0415
    tgc = cfg.get('telegram') or {}
    token = str(tgc.get('token') or '').strip()
    chat = str(tgc.get('chat_id') or '').strip()
    if not token or not chat:
        return (False, 'Telegram not configured (token/chat_id missing)')
    summary = _summary_line(hostname, len(alerts), public_url)
    if bool(tgc.get('group_messages')):
        # Grouped → Issues / Recovered sections sorted by item (like the email digest),
        # batched into as few messages as the size cap allows.
        payloads = list(_chunk(_tg_sections(cfg, alerts) + ['', summary]))
    else:
        # Ungrouped → one message per alert (arrival order), summary last.
        payloads = [_tg_line(hostname, a) for a in alerts] + [summary]
    ok_all, info = True, 'sent'
    for text in payloads:
        # HTML parse mode — every dynamic field is escaped by _esc, so module text with
        # _/*/<> renders safely; no tag spans a chunk boundary (each line is self-closed).
        ok, _code, info = send_telegram(token, chat, text, parse_mode='HTML')
        ok_all = ok_all and ok
    return (ok_all, info)


register_channel(Channel('telegram', send, flush))
