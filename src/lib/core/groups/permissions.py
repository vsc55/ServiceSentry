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
