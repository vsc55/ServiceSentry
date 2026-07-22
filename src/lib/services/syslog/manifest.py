#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events the syslog receiver publishes (discovered by lib.core.notify.events).

``syslog`` is the built-in syslog-receiver alert kind that auto-routes through the
``notifications|{channel}_on_syslog`` matrix.  (Rule-driven syslog alerting goes through
the events domain's ``event`` kind instead — see ``lib/services/events/manifest.py``.)
"""

NOTIFY_EVENTS = [
    # matrix=True keeps the notifications|{channel}_on_syslog config keys (no migration);
    # ui=False hides the row in the routing grid — the built-in syslog alert was replaced by
    # Event rules, so kind='syslog' has no active dispatcher (a live control would mislead).
    {'key': 'syslog', 'source': 'syslog', 'label_key': 'notif_event_syslog',
     'matrix': True, 'ui': False, 'order': 20},
]


# ── Permissions this package contributes ─────────────────────────
"""Permissions the syslog receiver owns (see lib.services.ipban.permissions for the
pattern).  Discovered by :func:`lib.core.permissions.discover_permissions` and merged
into the central registry by :mod:`lib.web_admin.constants`.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_syslog',   # i18n key for the role-editor group heading
    'order': 20,                    # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'syslog_view',   'roles': ('editor', 'viewer')},  # view received syslog messages
        {'flag': 'syslog_delete', 'roles': ()},                    # clear stored syslog messages
    ),
}


# ── Maintenance action this package contributes ──────────────────
# Wiping the message store is grouped with the other data wipes in Config → General →
# Maintenance rather than sitting in the Syslog toolbar. `fn` ships with the syslog UI.
CONFIG_ACTIONS = [
    {'section': 'maintenance', 'id': 'syslog_clear',
     'label_key': 'syslog_clear_all', 'tooltip_key': 'syslog_clear_all_tt',
     'icon': 'bi-trash3', 'variant': 'danger', 'order': 30,
     'perm': 'syslog_delete', 'fn': '_syslogClear'},
]


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import syslog_rows, syslog_stats_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'syslog_stats', 'icon': 'bi-card-list', 'label_key': 'overview_syslog_stats',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 110,
     'perms': {'any': ['syslog_view']}, 'nav': {'url': '/syslog'},
     'stat': syslog_stats_stat,
     'view': {'kind': 'stat', 'icon': 'bi-card-list', 'label_key': 'overview_syslog_stats',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/syslog_stats'}},
    {'id': 'syslog', 'icon': 'bi-card-list', 'label_key': 'overview_syslog',
     'cols': 12, 'h': 200, 'has_h': True, 'order': 190,
     'perms': {'any': ['syslog_view']}, 'nav': {'url': '/syslog'},
     'rows': syslog_rows,
     'view': {'kind': 'table', 'icon': 'bi-card-list', 'title_key': 'overview_syslog',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/syslog',
              'empty_key': 'syslog_empty', 'row_class': 'syslog_sev',
              'filter': {'store': 'sev', 'param': 'severity_max', 'badge_fn': 'sev'},
              'columns': [
                  {'key': 'when',     'label_key': 'syslog_time',     'cell': 'syslog_when'},
                  {'key': 'severity', 'label_key': 'syslog_severity', 'cell': 'severity'},
                  {'key': 'host',     'label_key': 'syslog_host',     'cell': 'syslog_host'},
                  {'key': 'message',  'label_key': 'syslog_message',  'cell': 'message'},
              ]}},
]


# ── Service self-description ─────────────────────────────────────
# Self-description for the web admin's Services tab (see
# lib.services.discover_embedded_services); the host wires the embedded
# status/control by convention (``_service_syslog_status`` / ``_control_syslog``).
EMBEDDED_SERVICE = {
    'key': 'syslog', 'label_key': 'svc_syslog', 'icon': 'bi-hdd-stack',
    'order': 20, 'controllable': True,
}

# Standalone launch (main.py --syslog) — see discover_standalone_services().
STANDALONE = {'key': 'syslog', 'dest': 'syslog_mode', 'banner': 'banner_syslog', 'order': 20}
