#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events the event-rules subsystem publishes (discovered by lib.core.notify.events).

An event rule dispatches ``kind='event'`` to the channels **the rule itself picks**, so
this source does NOT auto-route through the ``{channel}_on_{kind}`` matrix (``matrix=False``);
it is registered so the routing UI can still list it as a known notification source.
"""

NOTIFY_EVENTS = [
    {'key': 'event', 'source': 'events', 'label_key': 'notif_event',
     'matrix': False, 'order': 30},
]
