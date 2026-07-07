#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups mixin for WebAdmin.

After the Propuesta-A refactor the ``_groups`` dict is keyed by **uid**
(not by name).  The ``label`` field carries the human-readable group name.
"""

from datetime import datetime, timezone

from lib.core.permissions import BUILTIN_GROUP_UIDS, BUILTIN_ROLE_UIDS
from lib.core.constants import SYSTEM_USER


class _GroupsMixin:
    """Persistence and lookup for user groups (DB table ``groups``)."""

    def _load_groups(self) -> None:
        """Load groups from the DB.  Creates the default Administrators group on first run."""
        data = self._groups_store.load()
        if not data:
            admin_uid = BUILTIN_GROUP_UIDS['administrators']
            _now = datetime.now(timezone.utc).isoformat()
            self._groups = {
                admin_uid: {
                    'uid':         admin_uid,
                    'name':        'Administrators',
                    'description': 'Default administrators group.',
                    'roles':       [BUILTIN_ROLE_UIDS['admin']],
                    'enabled':     True,
                    'created_at':  _now,
                    'updated_at':  _now,
                    'updated_by':  SYSTEM_USER,
                },
            }
            self._persist_groups()
            return

        self._groups = data
        dirty = False

        # Ensure every group has its uid embedded in the dict value.
        for gid, gdata in self._groups.items():
            if not gdata.get('uid'):
                gdata['uid'] = gid
                dirty = True

        if dirty:
            self._persist_groups()

    def _persist_groups(self) -> bool:
        """Write groups to the DB."""
        return self._groups_store.save_all(self._groups)
