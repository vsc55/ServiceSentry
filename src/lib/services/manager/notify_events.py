#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events for operator service control (discovered by lib.core.notify.events).

When an operator starts/stops a background service from the Services tab, the hosting
instance emits ``service_started`` / ``service_stopped`` (the service name in the body).
These are the *intentional* lifecycle events — distinct from the health domain's crash
detection (``service_down`` / ``service_up``), which deliberately ignores a clean
operator start/stop.  They auto-route through the ``notifications|{channel}_on_{kind}``
matrix (dynamic keys, default off).

Monitoring keeps its own ``scheduler_started`` / ``scheduler_stopped`` events, so it does
NOT also emit these (see ``EmbeddedMonitor._LIFECYCLE_NOTIFY = False``).
"""

_SRC = 'service_control'
NOTIFY_EVENTS = [
    {'key': 'service_started', 'source': _SRC, 'label_key': 'notif_event_service_started',
     'matrix': True, 'order': 50},
    {'key': 'service_stopped', 'source': _SRC, 'label_key': 'notif_event_service_stopped',
     'matrix': True, 'order': 51},
]
