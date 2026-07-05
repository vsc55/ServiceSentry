#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCIM 2.0 provisioning provider.

The domain logic behind the ``/scim/v2/*`` endpoints — mapping the SCIM
protocol to the ServiceSentry user/group model (create / update / deactivate /
soft-delete + reactivate), independent of Flask.  The web layer
(``routes/scim.py``) stays thin: it owns the bearer-auth gate + rate limiting and
delegates every operation to :class:`ScimService`.
"""

from lib.providers.scim.service import (
    ScimService, bearer_token_ok, parse_filter_eq,
    USER_SCHEMA, GROUP_SCHEMA, LIST_SCHEMA, ERR_SCHEMA, PATCH_SCHEMA,
)

__all__ = [
    'ScimService', 'bearer_token_ok', 'parse_filter_eq',
    'USER_SCHEMA', 'GROUP_SCHEMA', 'LIST_SCHEMA', 'ERR_SCHEMA', 'PATCH_SCHEMA',
]
