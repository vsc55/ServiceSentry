#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the config domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_config',
    'order': 190,
    'permissions': (
        {'flag': 'config_view', 'roles': ('editor',)},  # read config.json
        {'flag': 'config_edit', 'roles': ('editor',)},  # write config.json
    ),
}
