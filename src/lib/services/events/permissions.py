#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the event processor owns (see lib.services.ipban.permissions for the
pattern).  Discovered by :func:`lib.core.permissions.discover_permissions` and merged
into the central registry by :mod:`lib.web_admin.constants`.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_events',   # i18n key for the role-editor group heading
    'order': 40,                    # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'events_view',          'roles': ('editor', 'viewer')},  # view event-notification rules
        {'flag': 'events_add',           'roles': ()},                     # create rules
        {'flag': 'events_edit',          'roles': ('editor',)},            # edit rules
        {'flag': 'events_delete',        'roles': ()},                     # delete rules
        {'flag': 'events_notify_view',   'roles': ('editor', 'viewer')},   # view the sent-notifications log
        {'flag': 'events_notify_delete', 'roles': ()},                     # clear the sent-notifications log
    ),
}
