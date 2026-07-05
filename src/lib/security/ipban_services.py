#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service capability registry for the internal fail2ban.

Instead of hardcoding "the web supports page/minimal/reject, syslog only drops",
every port-exposing service *declares* what it is and what block responses it can
produce.  The fail2ban discovers these descriptors, so the UI can show the exposed
attack surface + a per-service block-action selector limited to what each service
supports, and the enforcement reads the configured action from here — a new
service just registers a descriptor and works, nothing else to touch.

A block *action* is one entry from :data:`BLOCK_ACTIONS`; a service declares the
subset it ``supports`` and a ``default``.  The configured per-service action is
persisted (injected ``persist`` callback) and resolved by :meth:`action_for`.

Framework-free and thread-safe (the descriptors' ``endpoints`` are refreshed at
runtime, e.g. when the syslog ports change).
"""

from __future__ import annotations

import threading

# Catalog of block-action kinds (what a service can do with a jailed IP).
#   drop    — silently discard, no response (connectionless UDP: a true drop).
#   reject  — accept then reject minimally (empty HTTP 403 / closed socket).
#   minimal — a bare-text error (HTTP 403).
#   page    — a rich styled error page (HTTP only).
#   json    — a structured JSON error (HTTP/API only).
BLOCK_ACTIONS = ('drop', 'reject', 'minimal', 'page', 'json')


class IpBanServiceRegistry:
    """Registry of port-exposing services + their supported block actions.

    Thread-safe.  ``persist(service_id, action)`` (optional) is called whenever a
    per-service action is set, so the choice survives a restart."""

    def __init__(self, *, persist=None):
        self._lock = threading.RLock()
        self._persist = persist
        # id -> {'id','label_key','supports','default','endpoints'}
        self._services: dict[str, dict] = {}
        # id -> configured action (validated against the service's 'supports')
        self._actions: dict[str, str] = {}

    def set_persist(self, persist) -> None:
        self._persist = persist

    def load_actions(self, actions) -> None:
        """Seed the configured per-service actions from persistence (on boot)."""
        with self._lock:
            for svc, act in (actions or {}).items():
                if act in BLOCK_ACTIONS:
                    self._actions[svc] = act

    def register(self, *, id: str, label_key: str, supports, default: str,
                 endpoints=()) -> None:
        """Declare (or update) a service.  Idempotent — re-registering refreshes the
        endpoints (e.g. syslog after a port change) and capabilities."""
        supports = tuple(a for a in supports if a in BLOCK_ACTIONS) or ('reject',)
        if default not in supports:
            default = supports[0]
        with self._lock:
            self._services[id] = {
                'id': id, 'label_key': label_key, 'supports': supports,
                'default': default, 'endpoints': list(endpoints or ()),
            }
            # Drop a stale configured action that the service no longer supports.
            if self._actions.get(id) not in supports:
                self._actions.pop(id, None)

    def unregister(self, service_id: str) -> None:
        with self._lock:
            self._services.pop(service_id, None)

    def action_for(self, service_id: str) -> str:
        """The effective block action for a service: its configured override if set
        and still supported, else the service's declared default (else 'reject')."""
        with self._lock:
            svc = self._services.get(service_id)
            if svc is None:
                return self._actions.get(service_id, 'reject')
            act = self._actions.get(service_id)
            return act if act in svc['supports'] else svc['default']

    def set_action(self, service_id: str, action: str) -> bool:
        """Configure a service's block action.  '' / unsupported clears the override
        (back to the service default).  Returns True if the service exists."""
        with self._lock:
            svc = self._services.get(service_id)
            if svc is None:
                return False
            if action in svc['supports']:
                self._actions[service_id] = action
            else:
                action = ''
                self._actions.pop(service_id, None)
        if self._persist:
            try:
                self._persist(service_id, action)
            except Exception:  # pylint: disable=broad-except
                pass
        return True

    def services(self) -> list[dict]:
        """Snapshot of registered services with their resolved current action, for
        the API/UI.  Sorted by id for a stable display order."""
        with self._lock:
            out = []
            for svc in self._services.values():
                out.append({
                    'id': svc['id'], 'label_key': svc['label_key'],
                    'supports': list(svc['supports']), 'default': svc['default'],
                    'endpoints': [dict(e) for e in svc['endpoints']],
                    'action': self._actions.get(svc['id'], ''),   # '' = using default
                    'effective': self.action_for(svc['id']),
                })
            out.sort(key=lambda d: d['id'])
            return out
