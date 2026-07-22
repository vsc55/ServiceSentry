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
