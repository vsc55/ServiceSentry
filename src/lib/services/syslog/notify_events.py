#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events the syslog receiver publishes (discovered by lib.core.notify.events).

``syslog`` is the built-in syslog-receiver alert kind that auto-routes through the
``notifications|{channel}_on_syslog`` matrix.  (Rule-driven syslog alerting goes through
the events domain's ``event`` kind instead — see ``lib/services/events/notify_events.py``.)
"""

NOTIFY_EVENTS = [
    # matrix=True keeps the notifications|{channel}_on_syslog config keys (no migration);
    # ui=False hides the row in the routing grid — the built-in syslog alert was replaced by
    # Event rules, so kind='syslog' has no active dispatcher (a live control would mislead).
    {'key': 'syslog', 'source': 'syslog', 'label_key': 'notif_event_syslog',
     'matrix': True, 'ui': False, 'order': 20},
]
