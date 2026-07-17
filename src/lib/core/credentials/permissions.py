#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the credentials domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_credentials',
    'order': 180,
    'permissions': (
        {'flag': 'credentials_view',   'roles': ('editor',)},  # view reusable credentials
        {'flag': 'credentials_add',    'roles': ()},           # create reusable credentials (admin)
        {'flag': 'credentials_edit',   'roles': ('editor',)},  # edit reusable credentials
        {'flag': 'credentials_delete', 'roles': ()},           # delete reusable credentials (admin)
    ),
}
