#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core runtime: the monitoring engine and its alerting client.

* :mod:`lib.core.monitor` — :class:`Monitor`, the engine that loads modules,
  runs their checks and tracks state;
* :mod:`lib.core.telegram` — :class:`Telegram`, the queued sender the monitor
  uses to push its own alerts.

Both stay re-exported from the package root :mod:`lib` (``Monitor``,
``Telegram``) so existing call-sites are unaffected.
"""
