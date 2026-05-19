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
        return bool(_UUID_RE.match(s))

    def _uid_to_role_name(self, uid: str) -> str | None:
        for name, builtin_uid in BUILTIN_ROLE_UIDS.items():
            if builtin_uid == uid:
                return name
        for name, rdata in self._custom_roles.items():
            if rdata.get('uid') == uid:
                return name
        return None

    def _role_name_to_uid(self, name: str) -> str | None:
        if name in BUILTIN_ROLE_UIDS:
            return BUILTIN_ROLE_UIDS[name]
        rdata = self._custom_roles.get(name)
        return rdata.get('uid') if rdata else None

    def _uid_to_group_name(self, uid: str) -> str | None:
        for name, gdata in self._groups.items():
            if gdata.get('uid') == uid:
                return name
        return None

    def _group_name_to_uid(self, name: str) -> str | None:
        gdata = self._groups.get(name)
        return gdata.get('uid') if gdata else None

    # ── Permission resolution ────────────────────────────────────────────────

    def _get_role_permissions(self, role_name: str) -> frozenset:
        """Return the set of permissions for the given role name.

        Disabled custom roles grant no permissions. Built-in roles are
        always considered active regardless of any ``enabled`` field.
        """
        if role_name in BUILTIN_ROLE_PERMISSIONS:
            return BUILTIN_ROLE_PERMISSIONS[role_name]
        custom = self._custom_roles.get(role_name)
        if custom and custom.get('enabled', True):
            return frozenset(
                p for p in custom.get('permissions', [])
                if p in PERMISSIONS or is_module_perm(p)
            )
        return frozenset()

    def _get_effective_permissions(self, username: str, role_name: str) -> frozenset:
        """Return merged permissions: role perms ∪ perms from all roles in user's groups.

        Disabled groups are skipped entirely — their roles don't contribute.
        Supports both UID-based and name-based group/role references.
        """
        perms = self._get_role_permissions(role_name)
        user = self._users.get(username, {})
        for g_ref in user.get('groups', []):
            gname = self._uid_to_group_name(g_ref) if self._is_uid(g_ref) else g_ref
            g = self._groups.get(gname) if gname else None
            if g and g.get('enabled', True):
                for r_ref in g.get('roles', []):
                    rname = self._uid_to_role_name(r_ref) if self._is_uid(r_ref) else r_ref
                    if rname:
                        perms = perms | self._get_role_permissions(rname)
        return perms

    def _get_session_permissions(self) -> frozenset:
        """Return the set of permissions for the currently logged-in user.

        Always reads the current role from _users so that role changes take
        effect immediately without requiring a re-login.
        """
        username = session.get('username', '')
        user = self._users.get(username) or {}
        role_ref = user.get('role', 'viewer')
        role_name = self._uid_to_role_name(role_ref) if self._is_uid(role_ref) else role_ref
        if role_name is None:
            role_name = 'viewer'
        return self._get_effective_permissions(username, role_name)

    def _has_module_permission(self, module_name: str, action: str) -> bool:
        """Return True if the current user may perform *action* on *module_name*.

        Checks global module permissions first; falls back to per-module key
        ``module.{module_name}.{action}`` when the global grant is absent.
        Global mapping: view→modules_view, add/edit/delete→modules_edit.
        modules_add and modules_delete govern whole-module creation/removal,
        not item-level operations within a module.
        """
        perms = self._get_session_permissions()
        _global = {'view': 'modules_view', 'add': 'modules_edit',
                   'edit': 'modules_edit', 'delete': 'modules_edit'}
        global_perm = _global.get(action)
        if global_perm and global_perm in perms:
            return True
        return f'module.{module_name}.{action}' in perms
