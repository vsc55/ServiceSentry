#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Users domain — the user accounts registry (see :mod:`lib.core`).

* ``store``       — :class:`~lib.core.users.store.UsersStore`
* ``mixin``       — ``_UsersMixin`` (WebAdmin glue)
* ``routes``      — ``register(app, wa)`` (the /api/v1/users endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (users_view / add / edit / delete)

Kept light (no import of ``mixin`` / ``store`` here) so permission discovery can
import ``permissions`` without dragging in the Flask glue.
"""
