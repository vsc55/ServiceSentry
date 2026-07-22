#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the roles domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_roles',   # i18n key for the role-editor group heading
    'order': 120,                  # core domains ordered after the services (10–40)
    'permissions': (
        {'flag': 'roles_view',   'roles': ('editor', 'viewer')},  # see the roles list
        {'flag': 'roles_add',    'roles': ()},                    # create custom roles
        {'flag': 'roles_edit',   'roles': ('editor',)},           # edit custom roles
        {'flag': 'roles_delete', 'roles': ()},                    # delete custom roles
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import roles_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'roles', 'icon': 'bi-shield-shaded', 'label_key': 'overview_roles',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 60,
     'perms': {'any': ['roles_view']}, 'nav': {'tab': '#tab-access', 'sub': '#subtab-roles'},
     'stat': roles_stat,
     'view': {'kind': 'stat', 'icon': 'bi-shield-fill-check', 'label_key': 'overview_roles',
              'accent': 'violet', 'data_url': '/api/v1/overview/widget/roles'}},
]
