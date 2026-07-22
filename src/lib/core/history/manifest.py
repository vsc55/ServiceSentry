#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the history domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_history',
    'order': 210,
    'permissions': (
        {'flag': 'history_view',   'roles': ('editor', 'viewer')},  # view historical check data
        {'flag': 'history_delete', 'roles': ()},                    # delete historical data
    ),
}
