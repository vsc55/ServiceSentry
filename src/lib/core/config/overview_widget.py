#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widget for outgoing webhooks (config domain; see lib.core.overview.discovery)."""


def webhooks_stat(wa) -> dict:
    """Stat content for the ``webhooks`` card: configured total + an enabled badge."""
    total = enabled = 0
    try:
        from lib.core.notify.webhook import channel as _wh_channel  # noqa: PLC0415
        wh = _wh_channel.load(wa._notify)
        if isinstance(wh, list):
            total = len(wh)
            enabled = sum(1 for w in wh if isinstance(w, dict) and w.get('enabled', True))
    except Exception:  # pylint: disable=broad-except
        pass
    badges = ([{'style': 'ok', 'icon': 'bi-check-circle', 'count': enabled,
                'key': 'overview_enabled'}] if total else [])
    return {'value': total, 'badges': badges}
