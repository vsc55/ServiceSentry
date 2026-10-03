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
    # El cableado. Viven aquí y no en el paquete del inventario porque quien los emite es el
    # explorador de este paquete — la misma regla por la que `cert_expiring` no está en el de
    # los módulos que tienen certificados.
    {'key': 'cable_moved', 'source': 'dcim', 'label_key': 'notif_event_cable_moved',
     'matrix': True, 'order': 73},
    {'key': 'cable_undeclared', 'source': 'dcim',
     'label_key': 'notif_event_cable_undeclared', 'matrix': True, 'order': 74},
]

# Lo que este paquete despierta a hacer cada tanto, para la lista de temporizadores
# (lib/core/jobs). Cuatro hilos viven aquí y hasta ahora no aparecían en ninguna pantalla.
from .timers import live as BACKGROUND_TIMERS   # noqa: E402,F401  (a descriptor)
