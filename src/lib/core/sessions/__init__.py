#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sessions domain — the server-side session registry.

Self-contained module (see :mod:`lib.core`):

* ``store``       — :class:`~lib.core.sessions.store.SessionsStore`
* ``mixin``       — :class:`~lib.core.sessions.mixin._SessionsMixin` (WebAdmin glue)
* ``routes``      — ``register(app, wa)`` (the /api/v1/sessions endpoints)
* ``permissions`` — ``MODULE_PERMISSIONS`` (sessions_view / sessions_revoke)

Kept intentionally light (no import of ``mixin`` / ``store`` here) so permission
discovery can import ``permissions`` without dragging in the Flask glue.  The UI lives
in ``lib/web_admin/templates/partials`` and consumes these routes.
"""
