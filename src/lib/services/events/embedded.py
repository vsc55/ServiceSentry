#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The event processor running embedded in the web admin.

Composes the shared rule-evaluation worker (:class:`_EventsMixin`) with the host
context (:class:`_EmbeddedBase`).  Owns the worker thread + cooldown cache; reads
the shared stores (rules / notification-log / event-state and the syslog / audit
*sources*) from the host.
"""

from __future__ import annotations

import os

from lib.services.embedded import _EmbeddedBase
from lib.services.events.manager import _EventsMixin


class EmbeddedEvents(_EmbeddedBase, _EventsMixin):

    _LEADER_GATED = True       # single-owner: only the lease holder advances the cursor

    def __init__(self, host):
        _EmbeddedBase.__init__(self, host)
        self._init_events()
        self._attach_event_state(getattr(host, '_event_state_store', None))

    # ── shared stores delegated to the host (sources + dispatch bookkeeping) ───
    @property
    def _event_rules_store(self):
        return getattr(self._host, '_event_rules_store', None)

    @property
    def _notification_log_store(self):
        return getattr(self._host, '_notification_log_store', None)

    @property
    def _syslog_store(self):
        return getattr(self._host, '_syslog_store', None)

    @property
    def _audit_store(self):
        return getattr(self._host, '_audit_store', None)

    # ── gating ────────────────────────────────────────────────────────────────
    @staticmethod
    def _env_on() -> bool:
        v = os.environ.get('SS_EVENTS_EMBEDDED', '1').strip().lower()
        return v not in ('0', 'false', 'no', 'off')

    def _mode(self) -> str:
        return str((self._config_section('events') or {}).get('mode') or 'embedded').lower()

    def _autostart(self) -> bool:
        from lib.config.spec import cfg_get  # noqa: PLC0415
        return bool(cfg_get(self._config_section('events'), 'events|autostart'))

    def _poll(self) -> int:
        p = (self._config_section('events') or {}).get('poll_secs')
        return int(p) if p not in (None, '') else 2

    # ── boot ──────────────────────────────────────────────────────────────────
    def start_at_boot(self) -> None:
        if self._mode() == 'embedded' and self._env_on() and self._autostart():
            self._start_event_worker(self._poll())

    # ── ServiceDescriptor surface (Services tab) ──────────────────────────────
    def status(self) -> dict:
        mode = self._mode()
        env_on = self._env_on()
        running = bool(self._event_worker_running())
        embedded = env_on and mode != 'external'
        controllable = env_on and mode == 'embedded'
        if mode == 'external':
            state = 'external'
        elif mode == 'off':
            state = 'disabled'
        else:
            state = 'running' if running else 'stopped'
        rules = self._events_rules() or []
        rules_enabled = sum(1 for r in rules if r.get('enabled'))
        mode_key = ('svc_mode_container' if mode == 'external'
                    else 'svc_state_disabled' if mode == 'off'
                    else 'svc_mode_embedded')
        return {
            'state': state, 'running': running, 'embedded': embedded,
            'controllable': controllable, 'mode': mode, 'poll_secs': self._poll(),
            'rules': len(rules), 'rules_enabled': rules_enabled,
            'detail': [
                {'label_key': 'svc_mode', 'value_key': mode_key},
                {'label_key': 'svc_poll', 'value': f"{self._poll()} s"},
                {'label_key': 'svc_rules', 'value': f"{rules_enabled}/{len(rules)}"},
            ],
        }

    def control(self, action: str) -> tuple:
        if not (self._mode() == 'embedded' and self._env_on()):
            return False, 'not_controllable'
        if action == 'stop':
            self._stop_event_worker()
            self._audit_system('events_worker_stopped', {})
            return True, ''
        self._start_event_worker(self._poll())
        ok = bool(self._event_worker_running())
        if ok:
            self._audit_system('events_worker_started', {})
        return ok, '' if ok else 'already'

    # ── used by routes/config ─────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return bool(self._event_worker_running())

    def stop_worker(self) -> None:
        self._stop_event_worker()

    def on_config_changed(self, changed) -> None:
        # Leaving embedded mode (→ external/off) stops the running worker.
        if 'events|mode' in changed and self.running and self._mode() != 'embedded':
            self.stop_worker()


def make_embedded(host) -> EmbeddedEvents:
    return EmbeddedEvents(host)
