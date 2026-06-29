#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-level constants for the web administration server."""

import re

from lib.i18n import DEFAULT_LANG, SUPPORTED_LANGS, TRANSLATIONS, coerce_lang

__all__ = [
    'DEFAULT_LANG', 'SUPPORTED_LANGS', 'TRANSLATIONS', 'coerce_lang',
    'ROLES', 'PERMISSIONS', 'PERMISSION_GROUPS',
    '_BUILTIN_GROUPS', 'BUILTIN_ROLE_PERMISSIONS',
    'BUILTIN_ROLE_UIDS', 'BUILTIN_GROUP_UIDS',
    'SYSTEM_USER', 'is_module_perm', 'is_server_perm', 'is_cluster_perm',
]

_MODULE_PERM_RE = re.compile(r'^module\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')
# Per-server (host) permission key.  'add' authorizes adding host-bound checks to
# THIS specific host (not creating a host — that is the global ``servers_add``);
# 'edit'/'delete' act on existing host-bound checks and the host record.
_SERVER_PERM_RE = re.compile(r'^server\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')
# Per-cluster permission key (cluster.{uid}.{action}) — a cluster is a multi-bind
# check identified by its item UID.
_CLUSTER_PERM_RE = re.compile(r'^cluster\.[a-zA-Z0-9_\-.]+\.(view|add|edit|delete)$')


def is_module_perm(p: str) -> bool:
    """Return True if *p* is a valid per-module permission key (module.{name}.{action})."""
    return bool(_MODULE_PERM_RE.match(p))


def is_server_perm(p: str) -> bool:
    """Return True if *p* is a valid per-server permission key (server.{uid}.{action})."""
    return bool(_SERVER_PERM_RE.match(p))


def is_cluster_perm(p: str) -> bool:
    """Return True if *p* is a valid per-cluster permission key (cluster.{uid}.{action})."""
    return bool(_CLUSTER_PERM_RE.match(p))

# Valid user roles ordered by privilege (highest first).
# 'none' is a built-in role with zero permissions — user gets access only through groups.
ROLES = ('admin', 'editor', 'viewer', 'none')

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
    'modules_view',    # view modules list
    'modules_add',     # create new module entries
    'modules_edit',    # edit module settings and items
    'modules_delete',  # delete items from modules / remove whole modules
    'servers_view',    # view the servers (host registry) tab
    'servers_add',     # add modules/checks to a server
    'servers_edit',    # edit servers, host-bound checks and run host tests/migration
    'servers_delete',  # delete servers from the host registry
    'clusters_view',   # view the Clusters sub-tab (multi-bind checks)
    'clusters_add',    # create clusters (multi-host-bound checks)
    'clusters_edit',   # edit clusters and toggle them
    'clusters_delete', # delete clusters
    'credentials_view',   # view the reusable credentials tab
    'credentials_add',    # create reusable credentials
    'credentials_edit',   # edit reusable credentials
    'credentials_delete', # delete reusable credentials
    'config_view',     # read config.json (without editing)
    'config_edit',     # write config.json
    'overview_view',   # view the overview dashboard
    'overview_edit',   # customise the overview dashboard layout
    'overview_set_default',    # save the org-wide default dashboard layout
    'overview_reset_factory',  # reset the dashboard to the factory built-in layout
    'sessions_view',   # view active sessions
    'sessions_revoke', # revoke sessions
    'checks_view',     # view check results / status tab
    'checks_run',      # trigger module checks on demand
    'history_view',    # view historical check data and charts
    'history_delete',  # delete historical data
    'syslog_view',     # view received syslog messages
    'syslog_delete',   # clear stored syslog messages
    'services_view',   # view the Services dashboard (scheduler/syslog/worker/DB)
    'services_control',  # start/stop embedded services from the Services tab
    'events_view',     # view the event-notification rules
    'events_add',      # create event-notification rules
    'events_edit',     # edit event-notification rules
    'events_delete',   # delete event-notification rules
    'events_notify_view',    # view the sent-notifications log
    'events_notify_delete',  # clear the sent-notifications log
)

# Permissions grouped for the role editor UI.
PERMISSION_GROUPS = [
    ('perm_group_users',    ['users_view', 'users_add', 'users_edit', 'users_delete']),
    ('perm_group_roles',    ['roles_view', 'roles_add', 'roles_edit', 'roles_delete']),
    ('perm_group_groups',   ['groups_view', 'groups_add', 'groups_edit', 'groups_delete']),
    ('perm_group_audit',    ['audit_view', 'audit_delete']),
    ('perm_group_modules',  ['modules_view', 'modules_add', 'modules_edit', 'modules_delete']),
    ('perm_group_servers',  ['servers_view', 'servers_add', 'servers_edit', 'servers_delete']),
    ('perm_group_clusters', ['clusters_view', 'clusters_add', 'clusters_edit', 'clusters_delete']),
    ('perm_group_credentials', ['credentials_view', 'credentials_add', 'credentials_edit', 'credentials_delete']),
    ('perm_group_config',   ['config_view', 'config_edit']),
    ('perm_group_overview', ['overview_view', 'overview_edit', 'overview_set_default', 'overview_reset_factory']),
    ('perm_group_sessions', ['sessions_view', 'sessions_revoke']),
    ('perm_group_checks',   ['checks_view', 'checks_run']),
    ('perm_group_history',  ['history_view', 'history_delete']),
    ('perm_group_syslog',   ['syslog_view', 'syslog_delete']),
    ('perm_group_services', ['services_view', 'services_control']),
    ('perm_group_events',   ['events_view', 'events_add', 'events_edit', 'events_delete',
                             'events_notify_view', 'events_notify_delete']),
]

# Stable UUIDs for built-in roles and groups (never change these).
BUILTIN_ROLE_UIDS: dict[str, str] = {
    'admin':    '00000000-0000-4000-8000-000000000001',
    'editor':   '00000000-0000-4000-8000-000000000002',
    'viewer':   '00000000-0000-4000-8000-000000000003',
    'none':     '00000000-0000-4000-8000-000000000000',
}
BUILTIN_GROUP_UIDS: dict[str, str] = {
    'administrators': '00000000-0000-4000-8000-000000000010',
}

# Built-in groups identified by their stable UID (cannot be deleted or modified).
_BUILTIN_GROUPS: frozenset[str] = frozenset(BUILTIN_GROUP_UIDS.values())

# Reserved internal username for system-generated audit entries.
# This name MUST NOT be assigned to any real user account.
SYSTEM_USER: str = 'system'

# Built-in role → permission mapping (immutable).
BUILTIN_ROLE_PERMISSIONS: dict[str, frozenset] = {
    'admin':  frozenset(PERMISSIONS),
    # Editor: edit existing monitoring config and manage identity, but never add
    # or delete wholesale — no module/server add, no whole-module/server/check
    # deletion, no history/audit purge, no session revoke, and no
    # creating/removing users/roles/groups (edit only).
    'editor': frozenset({
        'modules_view', 'modules_edit',
        'servers_view', 'servers_edit',
        'clusters_view', 'clusters_edit',
        'config_view', 'config_edit',
        'overview_view', 'overview_edit',
        'checks_view', 'checks_run',
        'audit_view',
        'sessions_view',
        'users_view', 'users_edit',
        'roles_view', 'roles_edit',
        'groups_view', 'groups_edit',
        'history_view',
        'syslog_view',
        'services_view', 'services_control',
        'events_view', 'events_edit',
        'events_notify_view',
    }),  # editor edits existing rules but never adds/deletes wholesale
    'viewer': frozenset({
        'users_view', 'roles_view', 'groups_view',
        'audit_view', 'sessions_view', 'modules_view', 'checks_view', 'overview_view',
        'servers_view',
        'clusters_view',
        'history_view',
        'syslog_view',
        'services_view',
        'events_view',
        'events_notify_view',
    }),
    'none': frozenset(),
}
