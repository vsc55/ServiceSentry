#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cycle-scoped notifier for the monitor.

The monitor collects a cycle's check-state changes and flushes them **grouped per
channel** at the end of the cycle, routed by the notifications matrix
(``{channel}_on_{kind}`` for kinds ``down`` / ``recovery`` / ``warn``):

* **Telegram** — emoji-formatted lines batched into one message (or one per alert when
  ``telegram|group_messages`` is off), with a summary line appended.
* **Email** — a single digest email (``render_summary``) listing every alert + a summary.
* **Webhook** — one call per alert (discrete events, the norm for integrations).

This replaces the monitor's old direct, threaded ``lib.providers.telegram.Telegram``
client — there is no background sender thread; sending happens once, at flush time.
"""

from __future__ import annotations

import socket
import time

from lib.debug import DebugLevel

# Kinds the routing matrix understands (mirrors lib/config/spec.py).
KINDS = ('down', 'recovery', 'warn')
_ICON = {'down': '❎', 'recovery': '✅', 'warn': '⚠️'}
_TG_LIMIT = 3800   # keep grouped messages under Telegram's 4096-char hard cap


def _plain(text: str) -> str:
    """Strip Telegram Markdown decoration so a module message reads cleanly in email /
    webhook payloads (watchful modules format their messages for Telegram: *bold*, \\[ )."""
    return (text or '').replace('\\[', '[').replace('\\]', ']').replace('*', '')


class MonitorNotifier:
    """Accumulates a monitoring cycle's alerts and flushes them grouped per channel.

    ``wa`` is any object exposing the dispatcher's contract
    (``_read_config_file`` / ``_CONFIG_FILE`` / ``_dbg`` / ``_load_webhooks`` /
    ``_config_section``) — in practice the monitoring mixin / service.
    """

    def __init__(self, wa):
        self._wa = wa
        self._alerts: list[dict] = []

    def add(self, kind: str, module: str, item: str, message: str) -> None:
        """Buffer one alert. ``kind`` ∈ {down, recovery, warn}."""
        if kind and message:
            self._alerts.append({'kind': kind, 'module': module or '',
                                 'item': item or '', 'message': message})

    def has_pending(self) -> bool:
        return bool(self._alerts)

    def flush(self, *, public_url: str = '') -> dict:
        """Send the buffered alerts grouped per enabled channel, then clear the buffer.

        Returns ``{channel: (ok, info)}`` for each channel attempted (empty when there
        was nothing to send)."""
        alerts, self._alerts = self._alerts, []
        if not alerts:
            return {}
        wa = self._wa
        try:
            cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        except Exception as exc:  # pylint: disable=broad-except
            wa._dbg(f"> Notify >> config read failed: {exc}", DebugLevel.error)
            return {}
        notif = cfg.get('notifications') or {}
        hostname = socket.gethostname()
        results: dict[str, tuple] = {}

        for channel, flush_fn in (('telegram', self._flush_telegram),
                                  ('email', self._flush_email),
                                  ('webhook', self._flush_webhook)):
            picked = [a for a in alerts if notif.get(f'{channel}_on_{a["kind"]}', False)]
            if not picked:
                continue
            try:
                results[channel] = flush_fn(cfg, picked, hostname, public_url)
            except Exception as exc:  # pylint: disable=broad-except
                results[channel] = (False, str(exc))
                wa._dbg(f"> Notify > {channel} >> {type(exc).__name__}: {exc}", DebugLevel.error)
        wa._dbg(f"> Notify >> flushed {len(alerts)} alert(s): "
                f"{ {k: v[0] for k, v in results.items()} }", DebugLevel.info)
        return results

    # ── telegram: plain text + emoji (NOT Markdown) ──────────────────────────────
    # Telegram is sent WITHOUT parse_mode: module messages contain '_' and '*' (e.g.
    # 'pch_cannonlake', '*PVE02*') that break Markdown entity parsing — and when many are
    # concatenated into one grouped message the whole message is rejected. Plain text is
    # robust; emojis still render and URLs auto-link. _plain() drops the module Markdown.
    @staticmethod
    def _tg_line(hostname: str, a: dict) -> str:
        return f"{_ICON.get(a['kind'], '❎')} 💻 [{hostname}]: {_plain(a['message'])}"

    @staticmethod
    def _summary_line(hostname: str, n: int, public_url: str) -> str:
        s = f"ℹ️ Summary {hostname}, {n} new message(s)"
        if public_url:
            s += f"\n🔗 {public_url.rstrip('/')}/status"
        return s

    @staticmethod
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

    @staticmethod
    def _tg_sections(cfg, alerts) -> list:
        """Group the alerts into Issues / Recovered sections, each sorted by item — the
        same grouping as the email digest, as Telegram Markdown lines (used when
        ``group_messages`` is on)."""
        from lib.core.notify.email.templates import get_strings  # noqa: PLC0415
        lang = (cfg.get('email') or {}).get('lang') or (cfg.get('web_admin') or {}).get('lang') or ''
        s = get_strings(lang)

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
            out.append(f"{icon} {title} ({len(rows)})")
            for a in rows:
                prefix = f"[{a['item']}] " if a['item'] else ''
                out.append(f"  {_ICON.get(a['kind'], '❎')} {prefix}{_plain(a['message'])}")
        return out

    def _flush_telegram(self, cfg, alerts, hostname, public_url):
        from lib.providers.telegram import send_telegram  # noqa: PLC0415
        tgc = cfg.get('telegram') or {}
        token = str(tgc.get('token') or '').strip()
        chat = str(tgc.get('chat_id') or '').strip()
        if not token or not chat:
            return (False, 'Telegram not configured (token/chat_id missing)')
        summary = self._summary_line(hostname, len(alerts), public_url)
        if bool(tgc.get('group_messages')):
            # Grouped → Issues / Recovered sections sorted by item (like the email
            # digest), batched into as few messages as the size cap allows.
            payloads = list(self._chunk(self._tg_sections(cfg, alerts) + ['', summary]))
        else:
            # Ungrouped → one message per alert (arrival order), summary last.
            payloads = [self._tg_line(hostname, a) for a in alerts] + [summary]
        ok_all, info = True, 'sent'
        for text in payloads:
            ok, _code, info = send_telegram(token, chat, text)   # plain text (no parse_mode)
            ok_all = ok_all and ok
        return (ok_all, info)

    # ── email: one digest listing every alert + summary ────────────────────────
    def _flush_email(self, cfg, alerts, hostname, public_url):
        from lib.core.notify.email import notify as email_notify, templates as email_templates  # noqa: PLC0415
        email_cfg = cfg.get('email') or {}
        lang = email_cfg.get('lang') or ''
        lang_key = lang or 'en_EN'
        strings = email_templates.get_strings(
            lang, overrides=(cfg.get('notif_templates') or {}).get(lang_key) or None)
        html_override = (cfg.get('notif_html_templates') or {}).get('summary', {}).get(lang_key) or None
        items = [{'module': a['module'], 'item': a['item'],
                  'status': a['kind'], 'message': _plain(a['message'])} for a in alerts]
        body_html = email_templates.render_summary(
            items=items, timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
            public_url=public_url, lang=lang, strings=strings, html_override=html_override)
        prefix = email_cfg.get('subject_prefix') or '[ServiceSentry]'
        subject = f'{prefix} {hostname}: {len(alerts)} alert(s)'
        return email_notify._dispatch(email_cfg, subject=subject,
                                      body_html=body_html, recipients=None)

    # ── webhook: one call per alert (discrete events) ──────────────────────────
    def _flush_webhook(self, cfg, alerts, hostname, public_url):
        from lib.core.notify.webhook import notify as webhook_notify  # noqa: PLC0415
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        ok_all, infos = True, []
        for a in alerts:
            ok, msg = webhook_notify.send_all(
                self._wa, kind=a['kind'], module=a['module'], item=a['item'] or hostname,
                status=a['kind'], message=_plain(a['message']), timestamp=ts, cfg=cfg)
            ok_all = ok_all and ok
            infos.append(msg)
        return (ok_all, '; '.join(infos))
