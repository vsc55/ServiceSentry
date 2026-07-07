#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widget the events service owns (see lib.core.overview.discovery)."""


def events_stat(wa) -> dict:
    """Stat content for the ``events`` card: rule total + enabled/disabled breakdown +
    a notifications-sent badge."""
    total, enabled, notif = 0, 0, 0
    try:
        erstore = getattr(wa, '_event_rules_store', None)
        if erstore is not None:
            rules = erstore.list()
            total = len(rules)
            enabled = sum(1 for r in rules if r.get('enabled'))
        nlstore = getattr(wa, '_notification_log_store', None)
        if nlstore is not None:
            notif = nlstore.count()
    except Exception:  # pylint: disable=broad-except
        total, enabled, notif = 0, 0, 0
    disabled = total - enabled
    badges = []
    if enabled:
        badges.append({'style': 'ok', 'icon': 'bi-check-circle', 'count': enabled,
                       'key': 'overview_enabled'})
    if disabled:
        badges.append({'style': 'muted', 'count': disabled, 'key': 'overview_disabled'})
    if notif:
        badges.append({'style': 'warn', 'icon': 'bi-send',
                       'key': 'overview_events_notifications', 'args': [notif]})
    return {'value': total, 'badges': badges}


OVERVIEW_WIDGETS = [
    {'id': 'events', 'icon': 'bi-bell', 'label_key': 'overview_events',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 120,
     'perms': {'any': ['events_view']}, 'nav': {'tab': '#tab-events'},
     'stat': events_stat,
     'view': {'kind': 'stat', 'icon': 'bi-bell-fill', 'label_key': 'overview_events',
              'accent': 'pink', 'data_url': '/api/v1/overview/widget/events'}},
]
