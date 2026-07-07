#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the overview domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_overview',
    'order': 200,
    'permissions': (
        {'flag': 'overview_view',          'roles': ('editor', 'viewer')},  # view the overview dashboard
        {'flag': 'overview_edit',          'roles': ('editor',)},           # customise the layout
        {'flag': 'overview_set_default',   'roles': ()},                    # save org-wide default layout
        {'flag': 'overview_reset_factory', 'roles': ()},                    # reset to factory layout
    ),
}
