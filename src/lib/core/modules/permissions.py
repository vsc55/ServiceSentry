#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the modules domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_modules',
    'order': 150,
    'permissions': (
        {'flag': 'modules_view',   'roles': ('editor', 'viewer')},  # view modules list
        {'flag': 'modules_add',    'roles': ()},                    # create module entries
        {'flag': 'modules_edit',   'roles': ('editor',)},           # edit module settings/items
        {'flag': 'modules_delete', 'roles': ()},                    # delete items/modules
    ),
}
