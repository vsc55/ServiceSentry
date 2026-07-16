#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions resolution mixin for WebAdmin."""

import re

from flask import session

from lib.core.permissions import (
    BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS, PERMISSIONS,
    is_module_perm, is_server_perm, is_cluster_perm,
)

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

# Precomputed reverse maps for built-in roles (built once at import) so the
# per-request permission resolution does O(1) dict lookups instead of scanning
# BUILTIN_ROLE_UIDS on every call.
_BUILTIN_UID_TO_KEY: dict[str, str] = {
    uid: key for key, uid in BUILTIN_ROLE_UIDS.items()
}
_BUILTIN_UID_TO_PERMS: dict[str, frozenset] = {
    uid: BUILTIN_ROLE_PERMISSIONS[key]
    for key, uid in BUILTIN_ROLE_UIDS.items()
    if key in BUILTIN_ROLE_PERMISSIONS
}


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
        name = _BUILTIN_UID_TO_KEY.get(uid)
        if name is not None:
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

    def _is_admin_requester(self) -> bool:
        """True if the logged-in user is an admin — directly (role stored as the
        admin UID or the legacy 'admin' name) or via membership in an enabled
        group mapped to the admin role.

        Single source for the admin check; previously each route group defined
        its own variant and they had diverged (some missed the group-derived or
        legacy-name cases).
        """
        user = self._users.get(session.get('username', '')) or {}
        role = user.get('role', '')
        admin_uid = self._role_name_to_uid('admin')
        if role == admin_uid or self._uid_to_role_name(role) == 'admin':
            return True
        for g_ref in user.get('groups', []):
            g = self._groups.get(g_ref)
            if g and g.get('enabled', True) and admin_uid in (g.get('roles') or []):
                return True
        return False

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
        # Built-in by UID (O(1) lookup)
        builtin = _BUILTIN_UID_TO_PERMS.get(role_ref)
        if builtin is not None:
            return builtin
        # Built-in by internal key (backward compat)
        if role_ref in BUILTIN_ROLE_PERMISSIONS:
            return BUILTIN_ROLE_PERMISSIONS[role_ref]
        # Custom role by UID
        custom = self._custom_roles.get(role_ref)
        if custom and custom.get('enabled', True):
            return frozenset(
                p for p in custom.get('permissions', [])
                if p in PERMISSIONS or is_module_perm(p) or is_server_perm(p) or is_cluster_perm(p)
            )
        return frozenset()

    def _role_grantable(self, role_ref: str) -> bool:
        """Requester-context guard: may the current requester assign role *role_ref*?

        - An admin may grant anything.
        - The built-in ``admin`` role is never grantable by a non-admin.
        - The other built-in roles (``editor``/``viewer``) ARE grantable — delegated user
          management legitimately assigns the standard roles even though the actor may not
          personally hold every ``*_view`` permission they carry.
        - A **custom** role is grantable only if its permissions are a subset of the
          requester's own effective permissions (blocks assigning a custom role that carries
          a permission the requester lacks — i.e. self-/other-escalation).

        *role_ref* is a role UID (as stored) or a built-in key."""
        if self._is_admin_requester():
            return True
        if role_ref == BUILTIN_ROLE_UIDS.get('admin') or role_ref == 'admin':
            return False
        if role_ref in set(BUILTIN_ROLE_UIDS.values()) or role_ref in BUILTIN_ROLE_PERMISSIONS:
            return True   # built-in editor/viewer — delegatable
        return self._get_role_permissions(role_ref) <= self._get_session_permissions()

    def _groups_grantable(self, group_uids) -> bool:
        """Requester-context guard for assigning group MEMBERSHIP: a non-admin may only add a
        user to a group whose roles they could themselves grant (via :meth:`_role_grantable`).

        Membership matters because a group's roles are merged into the member's effective
        permissions — so adding a user to the built-in *Administrators* group (or any group
        carrying a higher-privilege role) is an escalation just like assigning the role
        directly. Admins may assign anything."""
        if self._is_admin_requester():
            return True
        for g_uid in group_uids or []:
            g = self._groups.get(g_uid)
            if not isinstance(g, dict):
                continue
            for r in g.get('roles', []) or []:
                if not self._role_grantable(r):
                    return False
        return True

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
        _global = {'view': 'modules_view', 'add': 'modules_add',
                   'edit': 'modules_edit', 'delete': 'modules_delete'}
        global_perm = _global.get(action)
        if global_perm and global_perm in perms:
            return True
        return f'module.{module_name}.{action}' in perms

    def _has_server_permission(self, host_uid: str, action: str) -> bool:
        """Return True if the current user may perform *action* (view/edit/delete)
        on server *host_uid* — via the global ``servers_*`` permission or a
        per-server ``server.{uid}.{action}`` override."""
        perms = self._get_session_permissions()
        _global = {'view': 'servers_view', 'add': 'servers_add',
                   'edit': 'servers_edit', 'delete': 'servers_delete'}
        global_perm = _global.get(action)
        if global_perm and global_perm in perms:
            return True
        return bool(host_uid) and f'server.{host_uid}.{action}' in perms
