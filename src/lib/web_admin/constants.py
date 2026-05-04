#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-level constants for the web administration server."""

from .i18n import DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS

__all__ = [
    'DEFAULT_LANG', 'SUPPORTED_LANGS', 'TRANSLATIONS',
    'ROLES', 'PERMISSIONS', 'PERMISSION_GROUPS',
    '_BUILTIN_GROUPS', 'BUILTIN_ROLE_PERMISSIONS',
]

# Valid user roles ordered by privilege (highest first).
ROLES = ('admin', 'editor', 'viewer')

# All available permission flags (granular, per-action).
PERMISSIONS = (
    'users_view',      # see the users list
    'users_add',       # create users
    'users_edit',      # edit user properties / role
    'users_delete',    # delete users
    'roles_view',      # see the roles list
    'roles_add',       # create custom roles
    'roles_edit',      # edit custom roles
    'roles_delete',    # delete custom roles
    'groups_view',     # see the groups list
    'groups_add',      # create groups
    'groups_edit',     # edit groups
    'groups_delete',   # delete groups
    'audit_view',      # read audit log
    'audit_delete',    # delete audit entries
    'modules_edit',    # write modules.json
    'config_edit',     # write config.json
    'sessions_view',   # view active sessions
    'sessions_revoke', # revoke sessions
    'checks_run',      # trigger module checks
)

# Permissions grouped for the role editor UI.
PERMISSION_GROUPS = [
    ('perm_group_users',    ['users_view', 'users_add', 'users_edit', 'users_delete']),
    ('perm_group_roles',    ['roles_view', 'roles_add', 'roles_edit', 'roles_delete']),
    ('perm_group_groups',   ['groups_view', 'groups_add', 'groups_edit', 'groups_delete']),
    ('perm_group_audit',    ['audit_view', 'audit_delete']),
    ('perm_group_modules',  ['modules_edit']),
    ('perm_group_config',   ['config_edit']),
    ('perm_group_sessions', ['sessions_view', 'sessions_revoke']),
    ('perm_group_checks',   ['checks_run']),
]

# Built-in groups (cannot be deleted or modified via API).
_BUILTIN_GROUPS: frozenset[str] = frozenset({'administrators'})

# Built-in role → permission mapping (immutable).
BUILTIN_ROLE_PERMISSIONS: dict[str, frozenset] = {
    'admin':  frozenset(PERMISSIONS),
    'editor': frozenset({
        'modules_edit', 'config_edit', 'checks_run', 'audit_view',
        'users_view', 'users_edit',
        'roles_view', 'roles_edit',
        'groups_view', 'groups_edit',
    }),
    'viewer': frozenset({
        'users_view', 'roles_view', 'groups_view',
        'audit_view', 'sessions_view',
    }),
}
