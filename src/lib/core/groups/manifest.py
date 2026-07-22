#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the groups domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_groups',   # i18n key for the role-editor group heading
    'order': 130,                   # core domains ordered after the services (10–40)
    'permissions': (
        {'flag': 'groups_view',   'roles': ('editor', 'viewer')},  # see the groups list
        {'flag': 'groups_add',    'roles': ()},                    # create groups
        {'flag': 'groups_edit',   'roles': ('editor',)},           # edit groups
        {'flag': 'groups_delete', 'roles': ()},                    # delete groups
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import groups_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'groups', 'icon': 'bi-people', 'label_key': 'overview_groups',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 50,
     'perms': {'any': ['groups_view']}, 'nav': {'tab': '#tab-access', 'sub': '#subtab-groups'},
     'stat': groups_stat,
     'view': {'kind': 'stat', 'icon': 'bi-people-fill', 'label_key': 'overview_groups',
              'accent': 'emerald', 'data_url': '/api/v1/overview/widget/groups'}},
]
