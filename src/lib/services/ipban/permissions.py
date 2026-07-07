#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the fail2ban service owns.

Discovered by :func:`lib.core.permissions.discover_permissions` and merged by
:mod:`lib.web_admin.constants` into ``PERMISSIONS`` / ``PERMISSION_GROUPS`` /
``BUILTIN_ROLE_PERMISSIONS`` — so the flags live WITH the service instead of hardcoded
in the central constants (the same self-describing pattern as ``embedded.py``).

``admin`` implicitly gets every flag; ``roles`` lists the OTHER builtin roles that
grant it.  i18n labels/descriptions stay in the lang files (data vs. presentation),
like config spec fields and HOME_PAGES.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_ipban',   # i18n key for the role-editor group heading
    'order': 30,                   # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'ipban_ban_view',         'roles': ('editor', 'viewer')},  # view banned IPs + watchlist
        {'flag': 'ipban_ban_add',          'roles': ()},                     # manually ban an IP
        {'flag': 'ipban_ban_edit',         'roles': ('editor',)},            # change a ban's block-action
        {'flag': 'ipban_ban_delete',       'roles': ()},                     # unban an IP
        {'flag': 'ipban_watchlist_clear',  'roles': ()},                     # clear a watchlist IP's counters
        {'flag': 'ipban_whitelist_view',   'roles': ('editor', 'viewer')},   # view the never-ban whitelist
        {'flag': 'ipban_whitelist_add',    'roles': ()},                     # add a whitelist entry
        {'flag': 'ipban_whitelist_delete', 'roles': ()},                     # remove a whitelist entry
        {'flag': 'ipban_history_view',     'roles': ('editor', 'viewer')},   # view the ban history
        {'flag': 'ipban_service_edit',     'roles': ('editor',)},            # set per-service block action
        {'flag': 'ipban_config_edit',      'roles': ('editor',)},            # edit fail2ban settings
    ),
}
