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
