#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modules domain — watchful module/item configuration (see :mod:`lib.core`).

* ``store``  — :class:`~lib.core.modules.store.ModulesStore` (tables module_config[_items])
* ``facade`` — :class:`~lib.core.modules.facade.DbBackedModules` (ConfigControl over the store)
* ``routes`` — ``register(app, wa)`` (the /api/v1/modules endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (modules_view / add / edit / delete)

What the routes call is Flask-free and split by concept:

* ``service`` — the config DOCUMENT: what may be seen of it, whether it is well formed, the
  spellings it is normalised to, and what the UI is built from.
* ``items`` — an item's identity: its uid, its name, its schema, and keeping them in step
  (rekeying, duplicates, the clone mark, where a row came from).
* ``authz`` — may this save touch this item. The module save crosses domains — a check
  belongs to a module and is bound to a host or a cluster — so it is its own file.
* ``provisioning`` — credentials kept out of the payload, and the hosts a module declares.
* ``actions`` — the config a watchful ACTION runs with, resolved the way a scheduled check
  would: bound host, restored secrets, referenced credential.

The store/facade are also imported by the standalone monitoring service (core layer).
Kept light (no import of ``store`` here) so permission discovery stays cheap.
"""

from .store import ModulesStore, create  # noqa: E402,F401
from .facade import DbBackedModules       # noqa: E402,F401
