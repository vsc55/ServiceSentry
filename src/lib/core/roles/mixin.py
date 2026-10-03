#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom roles mixin for WebAdmin."""

from lib.core.constants import BUILTIN_ROLE_UIDS
from lib.core.entity_sync import diff_entities, snapshot

# Legacy permission-flag renames applied to stored custom roles on load (one-off, then
# persisted). Repairs any DB that briefly carried the singular ``cluster_*`` flags back to
# the canonical plural ``clusters_*`` (matching the other domains).
_LEGACY_PERM_RENAME = {
    'cluster_view':   'clusters_view',
    'cluster_add':    'clusters_add',
    'cluster_edit':   'clusters_edit',
    'cluster_delete': 'clusters_delete',

    # Companies left the inventory for the core: the same company that pays for the cabinet
    # has users in the directory and licences in Microsoft 365, and two flags named after one
    # section could not say that. A role that held the old ones keeps what it was granted.
    'dcim_all_view':  'orgs_all_view',
    'dcim_org_edit':  'orgs_edit',
}


class _RolesMixin:
    """Persistence and lookup for custom roles (DB table ``roles``)."""

    #: The rows as last read from — or written to — the database. A save writes the
    #: difference against this, so it touches only what this process changed.
    _roles_snapshot: dict = None

    def _reload_roles_if_stale(self) -> bool:
        """Re-read the roles table when another writer has touched it (see
        :class:`lib.web_admin.mixins.freshness._FreshnessMixin`).  A second web replica is
        the writer that makes this necessary: without it, this process keeps granting the
        permissions a role had when it started."""
        return self._reload_if_stale('roles', getattr(self, '_roles_store', None),
                                     self._load_roles)

    def _load_roles(self) -> None:
        """Load roles from the columnar roles table.

        ``_custom_roles`` — keyed by UID — holds only **custom** roles:
        ``{uid: {uid, name, description, permissions, enabled, created_at,
        updated_at, updated_by}}``.

        ``_builtin_role_overrides`` — keyed by built-in UID — stores optional
        name/description overrides for the four built-in roles.  Permissions
        for built-ins are always taken from code (``BUILTIN_ROLE_PERMISSIONS``).
        """
        all_stored = self._roles_store.load_roles()
        builtin_uids = set(BUILTIN_ROLE_UIDS.values())
        self._custom_roles          = {uid: d for uid, d in all_stored.items()
                                        if uid not in builtin_uids}
        self._builtin_role_overrides = {uid: d for uid, d in all_stored.items()
                                         if uid in builtin_uids}
        # Taken here, before the migration below may persist: what is on disk right now is
        # what the next save must diff against, so that save writes only the rows it fixed.
        self._roles_snapshot = snapshot(all_stored)
        # One-off migration of renamed permission flags in stored custom roles, so
        # existing grants survive a flag rename (persisted once when anything changes).
        migrated = False
        for d in self._custom_roles.values():
            perms = d.get('permissions')
            if isinstance(perms, list):
                new = [_LEGACY_PERM_RENAME.get(p, p) for p in perms]
                if new != perms:
                    d['permissions'] = new
                    migrated = True
        if migrated:
            self._persist_roles()
        # Convenience: {key → display name} for routes that need it
        self._builtin_role_names = {
            key: self._builtin_role_overrides[uid]['name']
            for key, uid in BUILTIN_ROLE_UIDS.items()
            if uid in self._builtin_role_overrides and self._builtin_role_overrides[uid].get('name')
        }

    def _persist_roles(self) -> bool:
        """Write the roles this process changed — not the whole table.

        Replacing every row would delete a role another replica created while this one was
        being edited, silently and with nothing failing. :mod:`lib.core.entity_sync` spells
        out the rule; the short version is that a row we never saw is not ours to remove.
        """
        to_save = dict(self._custom_roles)
        to_save.update(self._builtin_role_overrides)
        writes, deletes = diff_entities(self._roles_snapshot, to_save)
        if not writes and not deletes:
            return True                      # nothing to say to the database
        ok = self._roles_store.apply(writes, deletes)
        if ok:
            self._roles_snapshot = snapshot(to_save)
            self._mark_fresh('roles', self._roles_store)
        return ok
