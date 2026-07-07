#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OIDC / OAuth2 SSO provider.

``auth``  — Flask-free integration logic (OAuth client, role mapping, user sync).
``routes`` — the ``/auth/oidc/{login,callback}`` endpoints (register(app, wa)).
"""

from . import auth  # noqa: F401  (convenience: `from lib.providers.oidc import auth`)
