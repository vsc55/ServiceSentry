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


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import session_rows, session_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'sessions', 'icon': 'bi-plug', 'label_key': 'overview_sessions',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 70,
     'perms': {'any': ['sessions_view']}, 'nav': {'tab': '#tab-access', 'sub': '#subtab-sessions'},
     'stat': session_stat,
     'view': {'kind': 'stat', 'icon': 'bi-plug-fill', 'label_key': 'overview_sessions',
              'accent': 'cyan', 'data_url': '/api/v1/overview/widget/sessions'}},
    {'id': 'sessions_list', 'icon': 'bi-plug', 'label_key': 'overview_sessions',
     'cols': 4, 'h': 140, 'has_h': True, 'order': 130,
     'perms': {'any': ['sessions_view']}, 'nav': {'tab': '#tab-access', 'sub': '#subtab-sessions'},
     'rows': session_rows,
     'view': {'kind': 'table', 'icon': 'bi-plug', 'title_key': 'overview_sessions',
              'accent': 'cyan', 'data_url': '/api/v1/overview/widget/sessions_list',
              'empty_key': 'status_empty', 'columns': [
                  {'key': 'user',      'label_key': 'col_user',      'sortable': True, 'cell': 'session_user'},
                  {'key': 'ip',        'label_key': 'col_ip',        'sortable': True, 'cell': 'code'},
                  {'key': 'browser',   'label_key': 'col_browser',   'sortable': True, 'cell': 'browser'},
                  {'key': 'last_seen', 'label_key': 'col_last_seen', 'sortable': True, 'cell': 'date'},
              ]}},
]
