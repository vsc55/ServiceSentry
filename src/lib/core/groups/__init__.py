#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups domain — user groups + their role bindings (see :mod:`lib.core`).

* ``store``       — :class:`~lib.core.groups.store.GroupsStore`
* ``mixin``       — ``_GroupsMixin`` (WebAdmin glue)
* ``routes``      — ``register(app, wa)`` (the /api/v1/groups endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (groups_view / add / edit / delete)

Kept light (no import of ``mixin`` / ``store`` here) so permission discovery can
import ``permissions`` without dragging in the Flask glue.
"""
