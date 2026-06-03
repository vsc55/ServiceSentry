#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions resolution mixin for WebAdmin."""

import re

from flask import session

from ..constants import BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS, PERMISSIONS, is_module_perm

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


class _PermissionsMixin:
    """Resolve effective permissions for roles, groups and the active session."""

    # ── UID helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_uid(s: str) -> bool:
        return bool(_UUID_RE.match(str(s)))

    def _uid_to_role_name(self, uid: str) -> str | None:
        """Return the internal role key for a UID, or None.

        For built-in roles this is the key used in BUILTIN_ROLE_PERMISSIONS
        ('admin', 'editor', …).  For custom roles it returns the display name
        stored in _custom_roles.
        """
        for name, builtin_uid in BUILTIN_ROLE_UIDS.items():
            if builtin_uid == uid:
                return name
        custom = self._custom_roles.get(uid)
        return custom.get('name') if custom else None

    def _role_name_to_uid(self, name: str) -> str | None:
        """Return the UID for a role given its internal key or display name."""
        # Built-in by internal key ('admin', 'editor', …)
        if name in BUILTIN_ROLE_UIDS:
            return BUILTIN_ROLE_UIDS[name]
        # Custom role: _custom_roles is {uid: {uid, name, ...}}
        for uid, rdata in self._custom_roles.items():
            if rdata.get('name') == name:
                return uid
        return None

    def _uid_to_group_label(self, uid: str) -> str | None:
        """Return the display name for a group uid, or None."""
        gdata = self._groups.get(uid)
        return gdata.get('name') if gdata else None

    def _uid_to_group_name(self, uid: str) -> str | None:
        return self._uid_to_group_label(uid)

    def _group_label_to_uid(self, label: str) -> str | None:
        for gid, gdata in self._groups.items():
            if gdata.get('name') == label:
                return gid
        return None

    def _group_name_to_uid(self, name: str) -> str | None:
        if name in self._groups:
            return name
        return self._group_label_to_uid(name)

    # ── Permission resolution ────────────────────────────────────────────────

    def _get_role_permissions(self, role_ref: str) -> frozenset:
        """Return the set of permissions for a role UID or internal key.

        Accepts:
        - A built-in role UID (e.g. '00000000-0000-4000-8000-000000000001')
        - A built-in role internal key (e.g. 'admin') — for backward compat
        - A custom role UID

        Disabled custom roles grant no permissions.
        """
        # Built-in by UID
        for bname, buid in BUILTIN_ROLE_UIDS.items():
            if buid == role_ref:
                return BUILTIN_ROLE_PERMISSIONS.get(bname, frozenset())
        # Built-in by internal key (backward compat)
        if role_ref in BUILTIN_ROLE_PERMISSIONS:
            return BUILTIN_ROLE_PERMISSIONS[role_ref]
        # Custom role by UID
        custom = self._custom_roles.get(role_ref)
        if custom and custom.get('enabled', True):
            return frozenset(
                p for p in custom.get('permissions', [])
                if p in PERMISSIONS or is_module_perm(p)
            )
        return frozenset()

    def _get_effective_permissions(self, username: str, role_ref: str) -> frozenset:
        """Return merged permissions: role perms ∪ perms from all roles in user's groups."""
        perms = self._get_role_permissions(role_ref)
        user  = self._users.get(username, {})
        for g_ref in user.get('groups', []):
            g = self._groups.get(g_ref) if g_ref else None
            if g and g.get('enabled', True):
                for r_ref in g.get('roles', []):
                    perms = perms | self._get_role_permissions(r_ref)
        return perms

    def _get_session_permissions(self) -> frozenset:
        """Return the permissions for the currently logged-in user."""
        username = session.get('username', '')
        user     = self._users.get(username) or {}
        role_ref = user.get('role', BUILTIN_ROLE_UIDS.get('viewer', 'viewer'))
        return self._get_effective_permissions(username, role_ref)

    def _has_module_permission(self, module_name: str, action: str) -> bool:
        """Return True if the current user may perform *action* on *module_name*."""
        perms = self._get_session_permissions()
        _global = {'view': 'modules_view', 'add': 'modules_edit',
                   'edit': 'modules_edit', 'delete': 'modules_edit'}
        global_perm = _global.get(action)
        if global_perm and global_perm in perms:
            return True
        return f'module.{module_name}.{action}' in perms
