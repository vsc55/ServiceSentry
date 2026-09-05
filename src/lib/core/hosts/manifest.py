#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the devices domain contributes (the host registry — see :mod:`lib.discovery`)."""


# ── What a device IS ─────────────────────────────────────────────────────────────────────
#
# The registry holds servers, but it also holds a NAS, a switch, a UPS and whatever else
# answers on the network — the section was called "Servers" while the SNMP catalogue beside
# it shipped profiles for Mikrotik, Linksys and two makes of UPS.
#
# So a device says what it is, and the panel stops guessing. Declared here rather than in the
# store because it is a vocabulary, not a schema detail: the icon a row wears, the way a
# fleet is grouped, and one day what a discovery run proposes after asking a device over
# SNMP (`detect_profiles` already knows how to ask).
#
# It is a PROPERTY and deliberately not a section: everything the panel does with an entry —
# address, credential, profiles, maintenance, tags, the checks bound to it — is the same
# whichever of these it is, and splitting by type would force a decision at creation time
# that is often wrong. A NAS *is* a server; a hypervisor is both.
#
# `''` (unset) is always allowed and is what every existing device has: making people
# classify a fleet before they can save anything would be a worse form than none.
HOST_TYPES: tuple[dict, ...] = (
    {'id': 'server',      'icon': 'bi-hdd-rack'},
    {'id': 'workstation', 'icon': 'bi-pc-display'},
    {'id': 'nas',         'icon': 'bi-hdd-stack'},
    {'id': 'hypervisor',  'icon': 'bi-boxes'},
    {'id': 'switch',      'icon': 'bi-ethernet'},
    {'id': 'router',      'icon': 'bi-router'},
    {'id': 'firewall',    'icon': 'bi-shield-lock'},
    {'id': 'ups',         'icon': 'bi-battery-charging'},
    {'id': 'printer',     'icon': 'bi-printer'},
    {'id': 'camera',      'icon': 'bi-camera-video'},
    {'id': 'other',       'icon': 'bi-hdd-network'},
)

#: The icon an unclassified device wears — the one the section has always used.
HOST_TYPE_FALLBACK_ICON = 'bi-hdd-network'


def host_type_ids() -> tuple:
    """Just the ids, for validation."""
    return tuple(t['id'] for t in HOST_TYPES)


def host_type_icon(type_id) -> str:
    """The icon for a type, or the generic one for anything unrecognised."""
    wanted = str(type_id or '').strip().lower()
    for t in HOST_TYPES:
        if t['id'] == wanted:
            return t['icon']
    return HOST_TYPE_FALLBACK_ICON

MODULE_PERMISSIONS = {
    'group': 'perm_group_devices',
    'order': 160,
    'permissions': (
        {'flag': 'devices_view',   'roles': ('editor', 'viewer')},  # view the servers tab
        {'flag': 'devices_add',    'roles': ()},                    # add modules/checks to a server
        {'flag': 'devices_edit',   'roles': ('editor',)},           # edit servers / host-bound checks
        {'flag': 'devices_delete', 'roles': ()},                    # delete servers
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import coverage_stat, server_list_rows, servers_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'servers', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 30,
     'perms': {'any': ['devices_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'stat': servers_stat,
     'view': {'kind': 'stat', 'icon': 'bi-hdd-network-fill', 'label_key': 'overview_servers',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/servers'}},
    {'id': 'coverage', 'icon': 'bi-pie-chart', 'label_key': 'overview_coverage',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 100,
     'perms': {'any': ['devices_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'stat': coverage_stat,
     'view': {'kind': 'stat', 'icon': 'bi-pie-chart-fill', 'label_key': 'overview_coverage',
              'accent': 'green', 'data_url': '/api/v1/overview/widget/coverage'}},
    {'id': 'servers_list', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 170,
     'perms': {'any': ['devices_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
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


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'host_cloned', 'severity': 'success'},
    {'key': 'host_created', 'severity': 'success'},
    {'key': 'host_deleted', 'severity': 'danger'},
    {'key': 'host_ssh_tested', 'severity': 'muted'},
    {'key': 'host_test_check', 'severity': 'muted'},
    {'key': 'host_tested', 'severity': 'muted'},
    {'key': 'host_updated', 'severity': 'info'},
    {'key': 'hosts_migrated', 'severity': 'info'},
]


# ── What of this package can belong to a company ─────────────────────────────────────────
#
# A machine belongs to somebody whether or not it is bolted into a rack: a VM, a VIP, a laptop
# on a desk. The scope lived in the inventory's list of owner scopes, which said that a host
# with no rack was the inventory's business — it is not; the registry is here.
#
# No `chain`: a host has no container to inherit from. It belongs to whoever was told about it,
# and to nobody otherwise — which is the honest answer and the one every screen already draws.
ORG_SCOPES = ({'scope': 'host', 'label_key': 'orgs_scope_host'},)
