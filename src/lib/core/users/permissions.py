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
