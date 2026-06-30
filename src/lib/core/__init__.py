#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core shared primitives — the foundational pieces other subsystems build on.

* :mod:`lib.core.object_base` — :class:`ObjectBase`, the base class carrying the
  shared :class:`~lib.debug.Debug` instance every class uses.
* :mod:`lib.core.telegram` — :class:`Telegram`, the queued sender used both by the
  monitoring engine (for its own run alerts) and by the notification subsystem
  (:mod:`lib.notify`).

Both are re-exported from the package root :mod:`lib` (``ObjectBase`` /
``Telegram``) so existing call-sites are unaffected.  The monitoring engine
(:class:`Monitor`) lives in :mod:`lib.services.monitoring.monitor`.
"""
