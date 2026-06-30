#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitor subsystem (the service scheduler, Flask-free):

* ``manager`` — :class:`_MonitoringMixin`: the background check scheduler (a single
  persistent :class:`lib.Monitor`, change-detection continuity, history pruning);
  shared by the WebAdmin (embedded) and the standalone service.
* ``service`` — :class:`MonitorService`: runs the scheduler as its own
  process/container, sharing the database with the rest of ServiceSentry.

Import the concrete symbols from their modules (``lib.services.monitoring.manager`` /
``lib.services.monitoring.service``) so importing one piece does not pull in the other.
"""

# Self-description for the web admin's Services tab.  The registry discovers this
# (see lib.services.discover_embedded_services); the host wires the embedded
# status/control by convention (``_service_monitoring_status`` / ``_control_monitoring``).
EMBEDDED_SERVICE = {
    'key': 'monitoring', 'label_key': 'svc_monitor', 'icon': 'bi-arrow-repeat',
    'order': 10, 'controllable': True,
}

# Standalone launch (main.py --monitor): discover_standalone_services() maps the CLI
# mode flag to ``service.run_standalone``; ``order`` resolves a tie if two were set.
STANDALONE = {'key': 'monitoring', 'dest': 'monitor_mode', 'banner': 'banner_monitor', 'order': 10}
