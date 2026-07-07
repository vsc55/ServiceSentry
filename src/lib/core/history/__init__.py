#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History domain — time-series of check results (see :mod:`lib.core`).

* ``store``       — :class:`~lib.core.history.store.HistoryStore`
* ``routes``      — ``register(app, wa)`` (the /api/v1/history endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (history_view / history_delete)

The store is also imported by the standalone monitoring service (it writes check
history) — it reaches in from here, which is fine for a *core* domain.  Kept light (no
import of ``store`` here) so permission discovery can import ``permissions`` alone.
"""
