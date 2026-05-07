#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions resolution mixin for WebAdmin."""

from flask import session

from ..constants import BUILTIN_ROLE_PERMISSIONS, PERMISSIONS


class _PermissionsMixin:
    """Resolve effective permissions for roles, groups and the active session."""

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
                p for p in custom.get('permissions', []) if p in PERMISSIONS
            )
        return frozenset()

    def _get_effective_permissions(self, username: str, role_name: str) -> frozenset:
        """Return merged permissions: role perms ∪ perms from all roles in user's groups.

        Disabled groups are skipped entirely — their roles don't contribute.
        """
        perms = self._get_role_permissions(role_name)
        user = self._users.get(username, {})
        for gname in user.get('groups', []):
            g = self._groups.get(gname)
            if g and g.get('enabled', True):
                for rname in g.get('roles', []):
                    perms = perms | self._get_role_permissions(rname)
        return perms

    def _get_session_permissions(self) -> frozenset:
        """Return the set of permissions for the currently logged-in user.

        Always reads the current role from _users so that role changes take
        effect immediately without requiring a re-login.
        """
        username = session.get('username', '')
        role_name = (self._users.get(username) or {}).get('role', 'viewer')
        return self._get_effective_permissions(username, role_name)
