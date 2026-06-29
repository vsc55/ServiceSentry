#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitoring scheduler mixin — re-exported from the Flask-independent
:mod:`lib.monitor.manager` so both the WebAdmin (embedded scheduler) and the
standalone :class:`lib.monitor.service.MonitorService` (the ``--monitor`` process
/ Docker worker) can mix it in.

The WebAdmin gates the embedded scheduler at construction time (enabled +
``SS_MONITORING_EMBEDDED``) — see :meth:`lib.web_admin.app.WebAdmin.__init__`.
"""

from lib.monitor.manager import _MonitoringMixin

__all__ = ['_MonitoringMixin']
