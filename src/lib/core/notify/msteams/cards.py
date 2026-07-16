#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Payload builders for Microsoft Teams notifications.

* :func:`message_card` — a legacy *MessageCard* (the format Incoming Webhook
  connectors accept universally), colour-coded by event kind.
* :func:`plain_text` — a compact one-line summary used for the Graph activity-feed
  preview text and the Bot Framework fallback text.
"""

from __future__ import annotations

# Theme colours (hex, no '#') by event kind — matches the app's alert palette.
_COLOURS = {
    'down':     'D13438',   # red
    'warn':     'F7B500',   # amber
    'recovery': '2E7D32',   # green
    'syslog':   '5B5FC7',   # teams purple
    'test':     '5B5FC7',
    'info':     '5B5FC7',
}


def _colour(kind: str) -> str:
    return _COLOURS.get((kind or '').lower(), _COLOURS['info'])


def _title(kind: str, item: str) -> str:
    label = {'down': 'DOWN', 'warn': 'WARNING', 'recovery': 'RECOVERED',
             'syslog': 'SYSLOG', 'test': 'TEST'}.get((kind or '').lower(), (kind or 'INFO').upper())
    return f'[{label}] {item}' if item else f'[{label}] ServiceSentry'


def message_card(*, kind: str = 'info', module: str = '', item: str = '',
                 status: str = '', message: str = '', timestamp: str = '') -> dict:
    """A MessageCard for a Teams Incoming Webhook connector."""
    facts = []
    if module:    facts.append({'name': 'Module', 'value': module})
    if item:      facts.append({'name': 'Item', 'value': item})
    if status:    facts.append({'name': 'Status', 'value': status})
    if timestamp: facts.append({'name': 'Time', 'value': timestamp})
    return {
        '@type': 'MessageCard',
        '@context': 'https://schema.org/extensions',
        'themeColor': _colour(kind),
        'summary': _title(kind, item),
        'sections': [{
            'activityTitle': _title(kind, item),
            'activitySubtitle': 'ServiceSentry',
            'text': message or '',
            'facts': facts,
            'markdown': True,
        }],
    }


def plain_text(*, kind: str = 'info', module: str = '', item: str = '',
               message: str = '', timestamp: str = '') -> str:
    """A compact one-line summary (activity-feed preview / bot fallback text)."""
    head = _title(kind, item)
    bits = [b for b in (module, message) if b]
    tail = ' — '.join(bits)
    out = f'{head}: {tail}' if tail else head
    return out[:250]
