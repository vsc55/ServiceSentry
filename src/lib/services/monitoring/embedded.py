#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The service monitor running embedded in the web admin.

Composes the shared scheduler (:class:`_MonitoringMixin`) with the host context
(:class:`_EmbeddedBase`).  Owns its own persistent ``Monitor`` and scheduler
thread; shares the host's ``_check_lock`` so the scheduler and an on-demand check
never overlap.
"""

from __future__ import annotations

from lib.services.embedded import _EmbeddedBase
from lib.services.monitoring.manager import _MonitoringMixin


class EmbeddedMonitor(_EmbeddedBase, _MonitoringMixin):

    _LEADER_GATED = True       # single-owner: only the lease holder runs cycles
    # Desired-state knob a dedicated --monitor container reconciles (start/stop).
    _EXTERNAL_KNOB = ('monitoring|enabled', True, False)

    def __init__(self, host):
        _EmbeddedBase.__init__(self, host)
        self._monitoring_init_state()

    # ── boot ──────────────────────────────────────────────────────────────────
    def start_at_boot(self) -> None:
        """Start the scheduler at web-admin boot when enabled + hosted here +
        autostart (its own gating; the WebAdmin just calls this on every service)."""
        if (self._monitoring_enabled() and self._embedded_monitor_enabled()
                and self._monitoring_autostart()):
            self._monitoring_start(run_now=True)

    # ── ServiceDescriptor surface (Services tab) ──────────────────────────────
    def status(self) -> dict:
        """Mirror of syslog: an ``enabled`` flag, embedded vs external decided by
        the SS_MONITORING_EMBEDDED env."""
        d = self._monitoring_status_dict()
        enabled = bool(d.get('enabled'))
        embedded = self._embedded_monitor_enabled()
        running = bool(d.get('running'))
        if not embedded:
            state = 'external'
        elif not enabled:
            state = 'disabled'
        else:
            state = 'running' if running else 'stopped'
        return {
            'state': state, 'running': running, 'enabled': enabled,
            # Controllable when hosted here + enabled, OR when a dedicated container
            # owns it (start/stop then edits the shared desired-state it reconciles).
            'embedded': embedded, 'controllable': (not embedded) or enabled,
            'interval': d.get('interval'), 'next_in': d.get('next_in'),
            'last_run': d.get('last_run'),
            'detail': [
                {'label_key': 'svc_mode',
                 'value_key': 'svc_mode_embedded' if embedded else 'svc_mode_container'},
                {'label_key': 'svc_interval',
                 'value': f"{d.get('interval')} s" if d.get('interval') is not None else '—'},
                {'label_key': 'svc_next_run', 'value': d.get('next_in'), 'fmt': 'in'},
                {'label_key': 'svc_last_run', 'value': d.get('last_run'), 'fmt': 'ago'},
            ],
        }

    def control(self, action: str) -> tuple:
        if not self._embedded_monitor_enabled():
            return self._control_external(action)   # a dedicated container owns it
        if action == 'stop':
            ok = self._monitoring_stop()
            return ok, '' if ok else 'already'
        if not self._monitoring_enabled():           # start needs enabled in config
            return False, 'disabled'
        ok = self._monitoring_start()
        return ok, '' if ok else 'already'

    # ── used by routes/daemon + routes/config ─────────────────────────────────
    def status_dict(self) -> dict:
        return self._monitoring_status_dict()

    def start(self, run_now: bool = False) -> bool:
        return self._monitoring_start(run_now=run_now)

    def stop(self) -> bool:
        return self._monitoring_stop()

    @property
    def enabled(self) -> bool:
        return self._monitoring_enabled()

    @property
    def running(self) -> bool:
        return self._monitoring_running

    @property
    def interval(self) -> int:
        return self._monitoring_interval

    def on_config_changed(self, changed) -> None:
        # Master switch: disabling the monitor from the config tab stops it when
        # running (enabling does NOT auto-start — that is autostart/Services).
        if 'monitoring|enabled' in changed and not self.enabled and self.running:
            self.stop()


def make_embedded(host) -> EmbeddedMonitor:
    return EmbeddedMonitor(host)
