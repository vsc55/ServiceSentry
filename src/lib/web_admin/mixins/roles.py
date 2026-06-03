#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom roles mixin for WebAdmin."""

from ..constants import BUILTIN_ROLE_UIDS


class _RolesMixin:
    """Persistence and lookup for custom roles (DB table ``roles``)."""

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
        # Convenience: {key → display name} for routes that need it
        self._builtin_role_names = {
            key: self._builtin_role_overrides[uid]['name']
            for key, uid in BUILTIN_ROLE_UIDS.items()
            if uid in self._builtin_role_overrides and self._builtin_role_overrides[uid].get('name')
        }

    def _persist_roles(self) -> bool:
        """Write all custom roles + built-in overrides to the roles table."""
        to_save = dict(self._custom_roles)
        to_save.update(self._builtin_role_overrides)
        return self._roles_store.save_all(to_save)
