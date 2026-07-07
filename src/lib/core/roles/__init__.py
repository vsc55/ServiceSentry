#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Roles domain — custom roles + their permission sets (see :mod:`lib.core`).

* ``store``       — :class:`~lib.core.roles.store.RolesStore`
* ``mixin``       — ``_RolesMixin`` (WebAdmin glue)
* ``routes``      — ``register(app, wa)`` (the /api/v1/roles endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (roles_view / add / edit / delete)

Kept light (no import of ``mixin`` / ``store`` here) so permission discovery can
import ``permissions`` without dragging in the Flask glue.
"""
