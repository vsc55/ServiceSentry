#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the credentials domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_credentials',
    'order': 180,
    'permissions': (
        # viewer sees them too: the listing masks every secret (secret_manager.mask_sensitive)
        # and a viewer already reaches that endpoint through servers_view/modules_view for the
        # host form's credential picker — withholding the flag only hid the Credentials tab.
        {'flag': 'credentials_view',   'roles': ('editor', 'viewer')},  # view reusable credentials
        {'flag': 'credentials_add',    'roles': ()},           # create reusable credentials (admin)
        {'flag': 'credentials_edit',   'roles': ('editor',)},  # edit reusable credentials
        {'flag': 'credentials_delete', 'roles': ()},           # delete reusable credentials (admin)
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import credentials_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'credentials', 'icon': 'bi-key', 'label_key': 'overview_credentials',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 90,
     'perms': {'any': ['credentials_view', 'servers_view', 'modules_view']},
     'nav': {'tab': '#tab-access', 'sub': '#subtab-credentials'},
     'stat': credentials_stat,
     'view': {'kind': 'stat', 'icon': 'bi-key-fill', 'label_key': 'overview_credentials',
              'accent': 'teal', 'data_url': '/api/v1/overview/widget/credentials'}},
]
