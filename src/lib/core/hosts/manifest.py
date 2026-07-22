#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Permissions the servers domain owns (the host registry — see
:mod:`lib.core.permissions`)."""

MODULE_PERMISSIONS = {
    'group': 'perm_group_servers',
    'order': 160,
    'permissions': (
        {'flag': 'servers_view',   'roles': ('editor', 'viewer')},  # view the servers tab
        {'flag': 'servers_add',    'roles': ()},                    # add modules/checks to a server
        {'flag': 'servers_edit',   'roles': ('editor',)},           # edit servers / host-bound checks
        {'flag': 'servers_delete', 'roles': ()},                    # delete servers
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import coverage_stat, server_list_rows, servers_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'servers', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 30,
     'perms': {'any': ['servers_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'stat': servers_stat,
     'view': {'kind': 'stat', 'icon': 'bi-hdd-network-fill', 'label_key': 'overview_servers',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/servers'}},
    {'id': 'coverage', 'icon': 'bi-pie-chart', 'label_key': 'overview_coverage',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 100,
     'perms': {'any': ['servers_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'stat': coverage_stat,
     'view': {'kind': 'stat', 'icon': 'bi-pie-chart-fill', 'label_key': 'overview_coverage',
              'accent': 'green', 'data_url': '/api/v1/overview/widget/coverage'}},
    {'id': 'servers_list', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 170,
     'perms': {'any': ['servers_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'rows': server_list_rows,
     'view': {'kind': 'table', 'icon': 'bi-hdd-network', 'title_key': 'overview_servers',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/servers_list',
              'empty_key': 'host_monitor_none',
              # Compound severity filter: a level (warning/error) with a =/≥ operator, host
              # type (virtual/physical), and a maintenance checkbox that unions in hosts in
              # maintenance. Levels with ``op:True`` show the =/≥ selector.
              'filter': {'kind': 'severity', 'store': 'srvf', 'param': 'f', 'maintenance': True,
                         'levels': [
                  {'v': '',        'label_key': 'all'},
                  {'v': 'warning', 'label_key': 'status_warning', 'op': True,
                   'badge': {'color': '#d97706', 'bg': 'rgba(245,158,11,.18)'}},
                  {'v': 'error',   'label_key': 'host_status_error', 'op': True,
                   'badge': {'color': '#dc3545', 'bg': 'rgba(220,53,69,.16)'}},
                  {'v': 'virtual', 'label_key': 'host_virtual',
                   'badge': {'color': '#0dcaf0', 'bg': 'rgba(13,202,240,.16)'}},
                  {'v': 'physical', 'label_key': 'host_physical'},
              ]},
              'columns': [
                  {'key': 'name',    'label_key': 'col_server',        'sortable': True, 'cell': 'host_name'},
                  {'key': 'status',  'label_key': 'col_host_status',   'sortable': True, 'cell': 'host_status'},
                  {'key': 'checks',  'label_key': 'col_checks',        'sortable': True, 'cell': 'host_checks'},
                  {'key': 'modules', 'label_key': 'col_host_modules',  'sortable': True, 'cell': 'host_modules'},
              ]}},
]
