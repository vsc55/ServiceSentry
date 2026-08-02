#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events the event-rules subsystem publishes (discovered by lib.core.notify.events).

An event rule dispatches ``kind='event'`` to the channels **the rule itself picks**, so
this source does NOT auto-route through the ``{channel}_on_{kind}`` matrix (``matrix=False``);
it is registered so the routing UI can still list it as a known notification source.
"""

NOTIFY_EVENTS = [
    {'key': 'event', 'source': 'events', 'label_key': 'notif_event',
     'matrix': False, 'order': 30},
]


# ── Permissions this package contributes ─────────────────────────
"""Permissions the event processor owns (see lib.services.ipban.permissions for the
pattern).  Discovered by :func:`lib.core.permissions.discover_permissions` and merged
into the central registry by :mod:`lib.web_admin.constants`.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_events',   # i18n key for the role-editor group heading
    'order': 40,                    # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'events_view',          'roles': ('editor', 'viewer')},  # view event-notification rules
        {'flag': 'events_add',           'roles': ()},                     # create rules
        {'flag': 'events_edit',          'roles': ('editor',)},            # edit rules
        {'flag': 'events_delete',        'roles': ()},                     # delete rules
        {'flag': 'events_notify_view',   'roles': ('editor', 'viewer')},   # view the sent-notifications log
        {'flag': 'events_notify_delete', 'roles': ()},                     # clear the sent-notifications log
    ),
}


# Clearing the sent-notifications log lives in Config → General → Maintenance, not in the
# Events toolbar — the same move the history, syslog and audit wipes made: that page stays
# open all day, one stray click from erasing the record. The fn ships with the events UI.
CONFIG_ACTIONS = [
    {'section': 'maintenance', 'id': 'events_clear_log',
     'label_key': 'event_log_clear', 'tooltip_key': 'event_log_clear_tt',
     'icon': 'bi-trash3', 'variant': 'danger', 'order': 40,
     'button_key': 'act_wipe', 'group_label_key': 'cfg_actions_group_wipe', 'desc_key': 'event_log_clear_desc',
     'perm': 'events_notify_delete', 'fn': '_eventClearLog'},
]


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import events_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'events', 'icon': 'bi-bell', 'label_key': 'overview_events',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 120,
     'perms': {'any': ['events_view']}, 'nav': {'tab': '#tab-events'},
     'stat': events_stat,
     'view': {'kind': 'stat', 'icon': 'bi-bell-fill', 'label_key': 'overview_events',
              'accent': 'pink', 'data_url': '/api/v1/overview/widget/events'}},
]


# ── Service self-description ─────────────────────────────────────
# Self-description for the web admin's Services tab (see
# lib.services.discover_embedded_services); the host wires the embedded
# status/control by convention (``_service_events_status`` / ``_control_events``).
EMBEDDED_SERVICE = {
    'key': 'events', 'label_key': 'svc_events', 'icon': 'bi-bell',
    'order': 30, 'controllable': True,
}

# Standalone launch (main.py --events) — see discover_standalone_services().
STANDALONE = {'key': 'events', 'dest': 'events_mode', 'banner': 'banner_events', 'order': 30}


# What this package writes to the audit log, and how loud each one is. Declared
# rather than guessed from the event name: the badge is the only thing a glance
# down two hundred rows gives you, and deriving it from a noun made the colour
# depend on what somebody called the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'event_rule_created', 'severity': 'success'},
    {'key': 'event_rule_deleted', 'severity': 'danger'},
    {'key': 'event_rule_test', 'severity': 'muted'},
    {'key': 'event_rule_updated', 'severity': 'info'},
    {'key': 'events_worker_started', 'severity': 'success'},
    {'key': 'events_worker_stopped', 'severity': 'warning'},
    {'key': 'notification_log_cleared', 'severity': 'danger'},
]
