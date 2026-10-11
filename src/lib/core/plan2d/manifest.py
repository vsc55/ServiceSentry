#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the 2D plan editor declares (see :mod:`lib.core.permissions`).

**No permission of its own.** Each screen that edits a plan says with which of ITS permissions
its catalogue is read and its objects are managed (`register_screen`): the inventory's are
`dcim_view` and `dcim_catalog_manage`. An editor that brought its own flag would let somebody
change what a screen can hold without being able to touch the screen.
"""

from lib.core.plan2d.store import SCHEMA as _KINDS

DB_TABLES = [_KINDS]

AUDIT_EVENTS = [
    # A new kind of object for everybody's palette, and one taken away. Who added «Palé» to the
    # inventory's plans is worth finding later; editing one is not.
    {'key': 'plan2d_kind_created', 'severity': 'info'},
    {'key': 'plan2d_kind_deleted', 'severity': 'info'},
]
