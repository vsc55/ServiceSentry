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


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import services_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {
        'id':        'services',
        'icon':      'bi-hdd-rack',
        'label_key': 'overview_services',
        'cols':      2, 'h': 'auto', 'has_h': False,
        'order':     25,
        'perms':     {'any': ['services_view']},
        'nav':       {'tab': '#tab-services'},
        # Data-driven render: generic stat card from its AJAX-fetched content.
        'stat':      services_stat,
        'view':      {'kind': 'stat', 'icon': 'bi-hdd-rack',
                      'label_key': 'overview_services', 'accent': 'green',
                      'data_url': '/api/v1/overview/widget/services'},
    },
]
