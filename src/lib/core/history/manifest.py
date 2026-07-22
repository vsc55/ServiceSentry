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
     'perm': 'history_delete', 'fn': 'showHistoryClearSeriesModal'},
    {'section': 'maintenance', 'id': 'history_clear_all',
     'label_key': 'history_clear_all', 'tooltip_key': 'history_clear_all_tt',
     'icon': 'bi-trash3', 'variant': 'danger', 'order': 20,
     'perm': 'history_delete', 'fn': '_historyClearAll'},
]
