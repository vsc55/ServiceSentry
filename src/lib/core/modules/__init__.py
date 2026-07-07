#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modules domain — watchful module/item configuration (see :mod:`lib.core`).

* ``store``  — :class:`~lib.core.modules.store.ModulesStore` (tables module_config[_items])
* ``facade`` — :class:`~lib.core.modules.facade.DbBackedModules` (ConfigControl over the store)
* ``routes`` — ``register(app, wa)`` (the /api/v1/modules endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (modules_view / add / edit / delete)

The store/facade are also imported by the standalone monitoring service (core layer).
Kept light (no import of ``store`` here) so permission discovery stays cheap.
"""

from .store import ModulesStore, create  # noqa: E402,F401
from .facade import DbBackedModules       # noqa: E402,F401
