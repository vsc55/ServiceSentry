#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Groups mixin for WebAdmin.

After the Propuesta-A refactor the ``_groups`` dict is keyed by **uid**
(not by name).  The ``label`` field carries the human-readable group name.
"""

from datetime import datetime, timezone

from lib.core.entity_sync import diff_entities, snapshot
from lib.core.constants import BUILTIN_GROUP_UIDS, BUILTIN_ROLE_UIDS, SYSTEM_USER


class _GroupsMixin:
    """Persistence and lookup for user groups (DB table ``groups``)."""

    #: The rows as last read from — or written to — the database (see _persist_groups).
    _groups_snapshot: dict = None

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
        self._groups_snapshot = snapshot(data)
        dirty = False

        # Ensure every group has its uid embedded in the dict value.
        for gid, gdata in self._groups.items():
            if not gdata.get('uid'):
                gdata['uid'] = gid
                dirty = True

        if dirty:
            self._persist_groups()

    def _reload_groups_if_stale(self) -> bool:
        """Re-read the groups table when another writer has touched it (see
        :class:`lib.web_admin.mixins.freshness._FreshnessMixin`).  The CLI writes groups,
        so this process is looking at a snapshot somebody else can move.

        A group's roles are part of a user's effective permissions, so a group going stale
        has the same consequence as a role going stale.
        """
        return self._reload_if_stale('groups', getattr(self, '_groups_store', None),
                                     self._load_groups)

    def _persist_groups(self) -> bool:
        """Write the groups this process changed — not the whole table.

        Replacing every row would delete a group created elsewhere while this copy was
        being edited. :mod:`lib.core.entity_sync` has the rule.
        """
        writes, deletes = diff_entities(self._groups_snapshot, self._groups)
        if not writes and not deletes:
            return True
        ok = self._groups_store.apply(writes, deletes)
        if ok:
            self._groups_snapshot = snapshot(self._groups)
            self._mark_fresh('groups', self._groups_store)
        return ok
