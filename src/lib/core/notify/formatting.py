#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared formatting helpers for notification channels (icons + plain-text de-markup)."""

from __future__ import annotations

# Status icons shared by channels that render per-alert lines.
ICON = {'down': '❎', 'recovery': '✅', 'warn': '⚠️'}

# Icon per notification *event kind* for single-event messages (Telegram/cards).
EVENT_ICON = {
    'down': '🔴', 'recovery': '🟢', 'warn': '🟠',
    'manual_run': '▶️',
    'scheduler_started': '🟢', 'scheduler_stopped': '🛑',
    'auth_login': '🔓', 'auth_login_failed': '🚫', 'auth_account_locked': '🔒',
    'ipban_banned': '⛔', 'ipban_unbanned': '🔓',
    'service_started': '▶️', 'service_stopped': '⏹️',
    'service_down': '💥', 'service_up': '💚',
    'cert_expiring': '📜',
    'syslog': '📄', 'event': '🔔',
}

# i18n label key per event kind — the human title lives in the lang files (en_EN/es_ES…),
# the SAME keys the routing-matrix UI shows, so a message title and its grid row never drift.
EVENT_LABEL_KEY = {
    'down': 'notif_event_down', 'recovery': 'notif_event_recovery', 'warn': 'notif_event_warn',
    'manual_run': 'notif_event_manual_run',
    'scheduler_started': 'notif_event_scheduler_started',
    'scheduler_stopped': 'notif_event_scheduler_stopped',
    'auth_login': 'notif_event_auth_login', 'auth_login_failed': 'notif_event_auth_login_failed',
    'auth_account_locked': 'notif_event_auth_locked',
    'ipban_banned': 'notif_event_ipban_banned', 'ipban_unbanned': 'notif_event_ipban_unbanned',
    'service_started': 'notif_event_service_started', 'service_stopped': 'notif_event_service_stopped',
    'service_down': 'notif_event_service_down', 'service_up': 'notif_event_service_up',
    'cert_expiring': 'notif_event_cert_expiring',
    'syslog': 'notif_event_syslog', 'event': 'notif_event',
}


def event_icon(kind: str) -> str:
    """Icon for a notification event kind (bell if unknown)."""
    return EVENT_ICON.get(kind or '', '🔔')


def event_title(kind: str, lang: str = '', cfg: dict = None) -> str:
    """Localised human title for an event kind, in the system notification *lang* (an admin
    override wins, else i18n, else a prettified key).  A notification has no user context but a
    system one — the panel/notifications language — so titles are translated, not English-only."""
    key = EVENT_LABEL_KEY.get(kind or '')
    if key:
        txt = notify_text(cfg, lang, key)
        if txt and txt != key:
            return txt
    return (kind or 'Notification').replace('_', ' ').capitalize()


def notify_lang(cfg: dict) -> str:
    """Effective notification language for the system: the global ``notifications|lang``,
    falling back to the panel language, then ''."""
    cfg = cfg or {}
    return ((cfg.get('notifications') or {}).get('lang')
            or (cfg.get('web_admin') or {}).get('lang') or '')


# ── Admin text-override layer (custom notification text on top of i18n) ────────
# cfg['notif_text_overrides'] = { <lang>: { '<scoped_key>': '<text>' } }
#   scoped_key: 'core:<i18n_key>'  |  'mod:<module>:<msg_key>'
def text_override(cfg: dict, lang: str, scoped_key: str) -> str:
    """Return the admin custom text for *scoped_key* in *lang*, or '' if none."""
    ov = (((cfg or {}).get('notif_text_overrides') or {}).get(lang or '', {}) or {}).get(scoped_key)
    return ov if isinstance(ov, str) and ov else ''


def _fill(text: str, args) -> str:
    """Fill placeholders with *args*.  Supports ``{}`` (sequential — each consumes the next arg)
    AND indexed ``{0}``/``{1}``… (by position) — so a custom text can **reorder** the inserted
    values (e.g. write ``{2}`` before ``{0}``), which plain ``{}`` can't express."""
    import re  # noqa: PLC0415
    args = list(args)
    if not args:
        return text
    # Indexed first: {N} → args[N] (out-of-range left untouched).
    text = re.sub(r'\{(\d+)\}',
                  lambda m: str(args[int(m.group(1))]) if int(m.group(1)) < len(args) else m.group(0),
                  text)
    # Then sequential {}: each takes the next arg in order.
    parts = text.split('{}')
    out = parts[0]
    for k, seg in enumerate(parts[1:]):
        out += (str(args[k]) if k < len(args) else '{}') + seg
    return out


def notify_text(cfg: dict, lang: str, key: str, *args) -> str:
    """Notification text for a core i18n *key* in *lang*: an admin override
    (``notif_text_overrides[lang]['core:'+key]``) if set, else the i18n string (which itself
    falls back to the default language, then the key).  ``{}`` placeholders filled by *args*."""
    from lib.i18n import translate  # noqa: PLC0415
    return _fill(text_override(cfg, lang, 'core:' + key) or translate(lang or '', key), args)


def plain(text: str) -> str:
    """Strip Telegram Markdown decoration so a module message reads cleanly in email /
    webhook / card payloads (watchful modules format for Telegram: *bold*, \\[ )."""
    return (text or '').replace('\\[', '[').replace('\\]', ']').replace('*', '')
