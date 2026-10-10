#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the brand domain declares (see :mod:`lib.core.permissions`).

**No permission of its own.** The name is a config field and the pictures are part of how the
panel is set up, so ``config_view`` reads them and ``config_edit`` changes them — the same
people who can rename the email sender already decide what the panel calls itself.
"""

from lib.core.brand.store import BRAND_ASSET_SCHEMA

DB_TABLES = [BRAND_ASSET_SCHEMA]

AUDIT_EVENTS = [
    # What the sign-in page shows to everybody: who changed it is worth finding later.
    {'key': 'brand_asset_set', 'severity': 'info'},
    {'key': 'brand_asset_reset', 'severity': 'info'},
]
