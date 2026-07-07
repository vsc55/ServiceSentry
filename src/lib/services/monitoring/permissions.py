#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the monitoring service (the check engine) owns — the Checks tab (see
lib.services.ipban.permissions for the pattern).  Discovered by
:func:`lib.core.permissions.discover_permissions` and merged into the central registry
by :mod:`lib.web_admin.constants`.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_checks',   # i18n key for the role-editor group heading
    'order': 10,                    # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'checks_view', 'roles': ('editor', 'viewer')},  # view check results / status tab
        {'flag': 'checks_run',  'roles': ('editor',)},           # trigger module checks on demand
    ),
}
