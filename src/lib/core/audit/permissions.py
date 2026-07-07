#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the audit domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_audit',   # i18n key for the role-editor group heading
    'order': 140,                  # core domains ordered after the services (10–40)
    'permissions': (
        {'flag': 'audit_view',   'roles': ('editor', 'viewer')},  # read audit log
        {'flag': 'audit_delete', 'roles': ()},                    # delete audit entries
    ),
}
