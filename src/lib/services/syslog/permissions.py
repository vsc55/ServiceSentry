#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the syslog receiver owns (see lib.services.ipban.permissions for the
pattern).  Discovered by :func:`lib.core.permissions.discover_permissions` and merged
into the central registry by :mod:`lib.web_admin.constants`.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_syslog',   # i18n key for the role-editor group heading
    'order': 20,                    # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'syslog_view',   'roles': ('editor', 'viewer')},  # view received syslog messages
        {'flag': 'syslog_delete', 'roles': ()},                    # clear stored syslog messages
    ),
}
