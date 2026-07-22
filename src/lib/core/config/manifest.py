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


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import webhooks_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'webhooks', 'icon': 'bi-broadcast', 'label_key': 'overview_webhooks',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 80,
     'perms': {'any': ['config_view', 'config_edit']}, 'nav': {'tab': '#tab-config'},
     'stat': webhooks_stat,
     'view': {'kind': 'stat', 'icon': 'bi-broadcast', 'label_key': 'overview_webhooks',
              'accent': 'purple', 'data_url': '/api/v1/overview/widget/webhooks'}},
]
