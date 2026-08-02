#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the history domain contributes: its permissions and its maintenance actions."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_history',
    'order': 210,
    'permissions': (
        {'flag': 'history_view',   'roles': ('editor', 'viewer')},  # view historical check data
        {'flag': 'history_delete', 'roles': ()},                    # delete historical data
    ),
}

# Data wipes live in Config → General → Maintenance, not in the History toolbar. Both
# name a JS function shipped with the history UI; the picker for a single series lives
# there too, since choosing one is a History concern the config panel knows nothing of.
CONFIG_ACTIONS = [
    {'section': 'maintenance', 'id': 'history_clear_series',
     'label_key': 'history_clear_series', 'tooltip_key': 'history_clear_series_tt',
     'icon': 'bi-trash3', 'variant': 'warning', 'order': 10,
     'button_key': 'act_wipe', 'group_label_key': 'cfg_actions_group_wipe', 'desc_key': 'history_clear_series_desc',
     'perm': 'history_delete', 'fn': 'showHistoryClearSeriesModal'},
    {'section': 'maintenance', 'id': 'history_clear_all',
     'label_key': 'history_clear_all', 'tooltip_key': 'history_clear_all_tt',
     'icon': 'bi-trash3', 'variant': 'danger', 'order': 20,
     'button_key': 'act_wipe', 'group_label_key': 'cfg_actions_group_wipe', 'desc_key': 'history_clear_all_desc',
     'perm': 'history_delete', 'fn': '_historyClearAll'},
]


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'history_all_deleted', 'severity': 'danger'},
    {'key': 'history_deleted', 'severity': 'danger'},
]
