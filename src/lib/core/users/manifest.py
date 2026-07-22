#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the users domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_users',   # i18n key for the role-editor group heading
    'order': 110,                  # core domains ordered after the services (10–40)
    'permissions': (
        {'flag': 'users_view',   'roles': ('editor', 'viewer')},  # see the users list
        {'flag': 'users_add',    'roles': ()},                    # create users
        {'flag': 'users_edit',   'roles': ('editor',)},           # edit user properties / role
        {'flag': 'users_delete', 'roles': ()},                    # delete users
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import users_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'users', 'icon': 'bi-person', 'label_key': 'overview_users',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 40,
     'perms': {'any': ['users_view']}, 'nav': {'tab': '#tab-access', 'sub': '#subtab-users'},
     'stat': users_stat,
     'view': {'kind': 'stat', 'icon': 'bi-person-fill', 'label_key': 'overview_users',
              'accent': 'orange', 'data_url': '/api/v1/overview/widget/users'}},
]
