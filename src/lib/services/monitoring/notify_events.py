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
