#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event subsystem (Flask-free, decoupled rule evaluation):

* ``manager`` — :class:`_EventsMixin`: rule matching, cooldown and the cursor-based
  worker; shared by the WebAdmin and the standalone services.
* ``service`` — :class:`EventService`: runs the worker as its own process/container.

Import the concrete symbols from their modules (``lib.services.events.manager`` /
``lib.services.events.service``) so importing one piece does not pull in the other.
"""

# Self-description for the web admin's Services tab (see
# lib.services.discover_embedded_services); the host wires the embedded
# status/control by convention (``_service_events_status`` / ``_control_events``).
EMBEDDED_SERVICE = {
    'key': 'events', 'label_key': 'svc_events', 'icon': 'bi-bell',
    'order': 30, 'controllable': True,
}

# Standalone launch (main.py --events) — see discover_standalone_services().
STANDALONE = {'key': 'events', 'dest': 'events_mode', 'banner': 'banner_events', 'order': 30}
