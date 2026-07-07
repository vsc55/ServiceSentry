#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LDAP / Active Directory authentication provider.

``auth``  — Flask-free integration logic (bind/search/verify, role mapping,
            user sync). Depends only on ``lib.config`` + the optional ``ldap3``.
``routes`` — the ``/api/v1/auth/ldap/*`` config/test endpoints (register(app, wa)).

The interactive login flow lives in ``web_admin.routes.auth`` and calls
``auth.authenticate`` / ``auth.sync_user`` directly.
"""

from . import auth  # noqa: F401  (convenience: `from lib.providers.ldap import auth`)
