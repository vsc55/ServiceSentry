#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service-health evaluator — turns the observed heartbeat liveness into notifications.

Background services (monitor/syslog/events, embedded or standalone) each beat into the
:class:`lib.services.manager.instances.ServiceInstancesStore`.  This evaluator periodically
classifies each service as **up / down / idle** from those rows and emits a ``service_down``
/ ``service_up`` notification **once per transition** — so an operator learns when a worker
crashes or a pod dies, without a live control that spams every poll.

Design notes:

* ``up``   — at least one instance is *running* and *fresh* (beat within ``down_after_secs``).
* ``down`` — nothing fresh-running, but an instance still claims ``running`` → it crashed /
  became unreachable (NOT a clean stop).
* ``idle`` — only cleanly-stopped instances (or none): the operator turned it off, so no alert.
* First observation of a service seeds its state **without** alerting (no boot-time noise).
* Leader-gated (a lease) so multiple web-admin replicas don't each fire the same alert.

The classification is a pure function (:func:`classify`) so it is unit-tested without threads,
DB or config.
"""

from __future__ import annotations

import threading
import time


def _default_text(key, *args):
    """Fallback text resolver (no host wired): the default-language i18n string."""
    from lib.i18n import translate  # noqa: PLC0415
    return translate('', key, *args)


def classify(instances: list, *, now: float, down_after_secs: float) -> dict:
    """Map heartbeat rows → ``{service_key: 'up' | 'down' | 'idle'}`` (see module doc)."""
    by_key: dict[str, list] = {}
    for r in instances or []:
        key = (r.get('service_key') or '').strip()
        if key:
            by_key.setdefault(key, []).append(r)
    out: dict[str, str] = {}
    for key, rows in by_key.items():
        fresh_running = claims_running = False
        for r in rows:
            last = r.get('last_seen') or 0
            fresh = (now - last) <= down_after_secs
            if bool(r.get('running')):
                claims_running = True
                fresh_running = fresh_running or fresh
        out[key] = 'up' if fresh_running else ('down' if claims_running else 'idle')
    return out


class ServiceHealthMonitor:
    """Periodically classify service liveness and emit up/down transitions once.

    Collaborators are injected as callables so this stays host-agnostic and testable:
    ``instances_provider() -> list[row]``, ``dispatch(kind, **fields)``,
    ``config_getter() -> dict`` (the ``services`` config section), ``is_leader() -> bool``.
    """

    def __init__(self, *, instances_provider, dispatch, config_getter,
                 is_leader=lambda: True, dbg=lambda *a, **k: None,
                 text_fn=None):
        text_fn = text_fn or _default_text
        self._instances = instances_provider
        self._dispatch = dispatch
        self._config = config_getter
        self._is_leader = is_leader
        self._dbg = dbg
        self._text = text_fn        # (key, *args) -> localized text with admin override
        self._state: dict[str, str] = {}     # service_key -> last observed health (up/down)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── evaluation (pure-ish: no threads/sleep) ─────────────────────────────────
    def evaluate_once(self, *, now: float) -> dict:
        """Classify once and emit any up/down transitions.  Returns the emitted
        ``{service_key: kind}`` (empty when disabled / no transition / not leader)."""
        cfg = self._config() or {}
        if not cfg.get('notify_down'):
            return {}
        try:
            down_after = max(15, int(cfg.get('down_after_secs') or 60))
        except (TypeError, ValueError):
            down_after = 60
        states = classify(self._instances() or [], now=now, down_after_secs=down_after)
        emitted: dict[str, str] = {}
        leader: bool | None = None
        for key, cur in states.items():
            if cur == 'idle':
                self._state.pop(key, None)      # operator-stopped → forget, never alert
                continue
            prev = self._state.get(key)
            if prev is None:
                self._state[key] = cur          # seed silently (no boot-time alert)
                continue
            if cur == prev:
                continue
            self._state[key] = cur
            if leader is None:
                leader = bool(self._is_leader())
            if not leader:
                continue
            down = cur == 'down'
            kind = 'service_down' if down else 'service_up'
            emitted[key] = kind
            try:
                self._dispatch(
                    kind, module='services', item=key,
                    status=self._text('notif_status_down' if down else 'notif_status_up'),
                    message=self._text('notif_msg_service_down' if down
                                       else 'notif_msg_service_up', key))
            except Exception:  # pylint: disable=broad-except
                self._dbg(f'> Health >> dispatch failed for {key!r}')
        return emitted

    # ── background loop ──────────────────────────────────────────────────────────
    def start(self, *, poll_getter=lambda: 30) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def _loop():
            while True:
                try:
                    interval = max(5, int(poll_getter() or 30))
                except (TypeError, ValueError):
                    interval = 30
                if self._stop.wait(interval):
                    return
                try:
                    self.evaluate_once(now=time.time())
                except Exception:  # pylint: disable=broad-except
                    pass

        self._thread = threading.Thread(target=_loop, name='svc-health', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
