#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAML2 SSO provider.

``auth``  — Flask-free integration logic (settings, auth factory, role mapping,
            user sync).
``routes`` — the ``/auth/saml2/{login,acs,metadata}`` endpoints (register(app, wa)).
"""

from . import auth  # noqa: F401  (convenience: `from lib.providers.saml import auth`)
