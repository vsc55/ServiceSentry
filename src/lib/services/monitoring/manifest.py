#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification events the monitoring subsystem publishes (discovered by lib.core.notify.events).

The monitor forwards a check's state changes as these kinds; they auto-route through the
``notifications|{channel}_on_{kind}`` matrix (see :class:`lib.core.notify.monitor_notifier`).

The kind strings are declared here — the single source of truth — and referenced by the
emitter (:meth:`lib.services.monitoring.monitor.Monitor._alert_kind`), so a monitoring kind
exists in exactly one place: this discovered descriptor.
"""

_SRC = 'monitoring'

# Kind strings — the single source of truth (registry declaration + the monitor emitter).
KIND_DOWN = 'down'
KIND_RECOVERY = 'recovery'
KIND_WARN = 'warn'

# Kind emitted by an on-demand "Run all" / "Run select" (Status tab) — the whole run routes
# as this single event (see lib/services/monitoring/checks_mixin.py), separate from the
# daemon's per-kind down/recovery/warn.  Its own 'manual' source groups it apart in the UI.
KIND_MANUAL_RUN = 'manual_run'

# Scheduler lifecycle — an operator starting/stopping the background check daemon.
# Distinct from the health domain's crash detection (service_down/up), which ignores
# a clean start/stop; these fire on the explicit action.
KIND_SCHED_STARTED = 'scheduler_started'
KIND_SCHED_STOPPED = 'scheduler_stopped'

NOTIFY_EVENTS = [
    {'key': KIND_DOWN,     'source': _SRC, 'label_key': 'notif_event_down',     'matrix': True, 'order': 10},
    {'key': KIND_RECOVERY, 'source': _SRC, 'label_key': 'notif_event_recovery', 'matrix': True, 'order': 11},
    {'key': KIND_WARN,     'source': _SRC, 'label_key': 'notif_event_warn',     'matrix': True, 'order': 12},
    {'key': KIND_SCHED_STARTED, 'source': _SRC, 'label_key': 'notif_event_scheduler_started',
     'matrix': True, 'order': 20},
    {'key': KIND_SCHED_STOPPED, 'source': _SRC, 'label_key': 'notif_event_scheduler_stopped',
     'matrix': True, 'order': 21},
    {'key': KIND_MANUAL_RUN, 'source': 'manual', 'label_key': 'notif_event_manual_run',
     'matrix': True, 'order': 90},
]


# ── Permissions this package contributes ─────────────────────────
"""Permissions the monitoring service (the check engine) owns — the Checks tab (see
lib.services.ipban.permissions for the pattern).  Discovered by
:func:`lib.core.permissions.discover_permissions` and merged into the central registry
by :mod:`lib.web_admin.constants`.
"""

MODULE_PERMISSIONS = {
    'group': 'perm_group_checks',   # i18n key for the role-editor group heading
    'order': 10,                    # ordering among discovered (service-owned) groups
    'permissions': (
        {'flag': 'checks_view', 'roles': ('editor', 'viewer')},  # view check results / status tab
        {'flag': 'checks_run',  'roles': ('editor',)},           # trigger module checks on demand
    ),
}


# ── Overview widgets this package contributes ────────────────────
from .overview_widget import checks_stat  # noqa: F401

OVERVIEW_WIDGETS = [
    {'id': 'checks', 'icon': 'bi-activity', 'label_key': 'overview_status',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 10,
     'perms': {'any': ['checks_view', 'checks_run']}, 'nav': {'tab': '#tab-status'},
     'stat': checks_stat,
     'view': {'kind': 'stat', 'icon': 'bi-activity', 'label_key': 'overview_status',
              'accent': 'green', 'data_url': '/api/v1/overview/widget/checks'}},
]


# ── Service self-description ─────────────────────────────────────
# Self-description for the web admin's Services tab.  The registry discovers this
# (see lib.services.discover_embedded_services); the host wires the embedded
# status/control by convention (``_service_monitoring_status`` / ``_control_monitoring``).
EMBEDDED_SERVICE = {
    'key': 'monitoring', 'label_key': 'svc_monitor', 'icon': 'bi-arrow-repeat',
    'order': 10, 'controllable': True,
}

# Standalone launch (main.py --monitor): discover_standalone_services() maps the CLI
# mode flag to ``service.run_standalone``; ``order`` resolves a tie if two were set.
STANDALONE = {'key': 'monitoring', 'dest': 'monitor_mode', 'banner': 'banner_monitor', 'order': 10}
