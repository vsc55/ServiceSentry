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
