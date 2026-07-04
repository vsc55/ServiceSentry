#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core shared primitives — the foundational pieces other subsystems build on.

* :mod:`lib.core.object_base` — :class:`ObjectBase`, the base class carrying the
  shared :class:`~lib.debug.Debug` instance every class uses.

Re-exported from the package root :mod:`lib` (``ObjectBase``) so existing
call-sites are unaffected.  The monitoring engine (:class:`Monitor`) lives in
:mod:`lib.services.monitoring.monitor`; the Telegram client (:class:`Telegram`)
lives in :mod:`lib.providers.telegram`.
"""
