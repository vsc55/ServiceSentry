#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the modules domain owns (see :mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_modules',
    'order': 150,
    'permissions': (
        {'flag': 'modules_view',   'roles': ('editor', 'viewer')},  # view modules list
        {'flag': 'modules_add',    'roles': ()},                    # create module entries
        {'flag': 'modules_edit',   'roles': ('editor',)},           # edit module settings/items
        {'flag': 'modules_delete', 'roles': ()},                    # delete items/modules
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import _modules_list_rows, incident_rows, modules_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'modules', 'icon': 'bi-puzzle', 'label_key': 'overview_modules',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 20,
     'perms': {'any': ['modules_view']}, 'nav': {'tab': '#tab-modules'},
     'stat': modules_stat,
     'view': {'kind': 'stat', 'icon': 'bi-puzzle-fill', 'label_key': 'overview_modules',
              'accent': 'indigo', 'data_url': '/api/v1/overview/widget/modules'}},
    {'id': 'incidents', 'icon': 'bi-exclamation-triangle', 'label_key': 'overview_incidents',
     'cols': 4, 'h': 140, 'has_h': True, 'order': 140,
     'perms': {'any': ['modules_view']}, 'nav': {'tab': '#tab-status'},
     'rows': incident_rows,
     'view': {'kind': 'table', 'icon': 'bi-exclamation-triangle', 'title_key': 'overview_incidents',
              'accent': 'red', 'data_url': '/api/v1/overview/widget/incidents',
              'empty_key': 'overview_no_issues', 'empty_ok': True,
              'columns': [
                  {'key': 'module', 'label_key': 'col_module', 'sortable': True, 'cell': 'module_incident'},
                  {'key': 'check',  'label_key': 'col_check',  'sortable': True, 'cell': 'check_danger'},
                  {'key': 'host',   'label_key': 'col_host',   'sortable': True, 'cell': 'host_code'},
              ]}},
    {'id': 'modules_list', 'icon': 'bi-puzzle', 'label_key': 'overview_modules',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 160,
     'perms': {'any': ['modules_view']}, 'nav': {'tab': '#tab-modules'},
     # Data-driven AJAX table: rows fetched (filtered) server-side by ``rows``, painted
     # by the generic table renderer from ``columns`` (cell types); ``rows`` is stripped
     # before the descriptor is serialised to the frontend.
     'rows': _modules_list_rows,
     'view': {'kind': 'table', 'icon': 'bi-puzzle', 'title_key': 'overview_modules',
              'accent': 'indigo', 'data_url': '/api/v1/overview/widget/modules_list',
              # Compound severity filter: a level with a =/≥ operator (warning/error), plus
              # the fixed 'active' option. No maintenance (a module isn't a host).
              'filter': {'kind': 'severity', 'store': 'modf', 'param': 'f', 'maintenance': False,
                         'levels': [
                  {'v': '',        'label_key': 'all'},
                  {'v': 'on',      'label_key': 'dw_mod_on',
                   'badge': {'color': '#16a34a', 'bg': 'rgba(34,197,94,.16)'}},
                  {'v': 'warning', 'label_key': 'status_warning', 'op': True,
                   'badge': {'color': '#d97706', 'bg': 'rgba(245,158,11,.18)'}},
                  {'v': 'error',   'label_key': 'host_status_error', 'op': True,
                   'badge': {'color': '#dc3545', 'bg': 'rgba(220,53,69,.16)'}},
              ]},
              'columns': [
                  {'key': 'name',    'label_key': 'col_module',     'sortable': True, 'cell': 'module_name'},
                  {'key': 'enabled', 'label_key': 'col_enabled',    'sortable': True, 'cell': 'on_badge'},
                  {'key': 'checks',  'label_key': 'col_checks',                       'cell': 'checks'},
                  {'key': 'items',   'label_key': 'overview_items', 'sortable': True, 'cell': 'num', 'align': 'muted'},
              ]}},
]
