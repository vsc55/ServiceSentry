#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the sessions domain owns.

Discovered by :func:`lib.core.permissions.discover_permissions` and merged by
:mod:`lib.web_admin.constants` — so the flags live WITH the domain instead of hardcoded
centrally (the same self-describing pattern as the service ``permissions.py`` modules).
``admin`` implicitly gets every flag; ``roles`` lists the OTHER builtin roles that grant
it.  i18n labels stay in the lang files (data vs. presentation).
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_sessions',   # i18n key for the role-editor group heading
    'order': 100,                     # core domains ordered after the services (10–40)
    'permissions': (
        {'flag': 'sessions_view',   'roles': ('editor', 'viewer')},  # view active sessions
        {'flag': 'sessions_revoke', 'roles': ()},                    # revoke sessions
    ),
}
