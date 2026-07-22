#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events the platform self-monitoring (core.health) publishes.

Emitted by the background evaluators in this package; they auto-route through the
``notifications|{channel}_on_{kind}`` matrix (dynamic keys, default off).
"""

NOTIFY_EVENTS = [
    {'key': 'service_down', 'source': 'services', 'label_key': 'notif_event_service_down',
     'matrix': True, 'order': 60},
    {'key': 'service_up',   'source': 'services', 'label_key': 'notif_event_service_up',
     'matrix': True, 'order': 61},
    {'key': 'cert_expiring', 'source': 'certs', 'label_key': 'notif_event_cert_expiring',
     'matrix': True, 'order': 70},
    {'key': 'secret_expiring', 'source': 'certs', 'label_key': 'notif_event_secret_expiring',
     'matrix': True, 'order': 71},
    {'key': 'secret_rotated', 'source': 'certs', 'label_key': 'notif_event_secret_rotated',
     'matrix': True, 'order': 72},
]
