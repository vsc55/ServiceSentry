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


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'overview_default_layout_set', 'severity': 'info'},
    {'key': 'overview_reset_factory', 'severity': 'warning'},
]
