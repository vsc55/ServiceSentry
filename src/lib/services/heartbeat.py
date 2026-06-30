#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service heartbeat mixin — the *observed state* writer of the control plane.

Mixed into both the embedded service objects (in the web admin process) and the
standalone ``*Service`` daemons, so the very same code publishes a liveness row
to :class:`lib.stores.service_instances.ServiceInstancesStore` every few seconds.
The web admin then reads that table to show the real state of every instance —
including the ones running in another container/pod — instead of guessing from
check activity.

The host must expose ``_service_instances_store`` (the embedded base delegates it
to the WebAdmin; each standalone service builds its own on the shared connector).
Identity/running/detail come from small overridable hooks, defaulting to values
derived from the object's ``status()`` so a service rarely needs to override more
than its key.
"""

from __future__ import annotations

import os
import socket
import threading


def hostname() -> str:
    """Best identifier for *this* instance's host: the k8s pod name when present
    (downward API), else the container/host name."""
    return (os.environ.get('POD_NAME') or os.environ.get('HOSTNAME')
            or socket.gethostname() or 'unknown')


class _HeartbeatMixin:
    """Publish a periodic liveness row for one service instance."""

    _HB_KEY: str | None = None      # service key ('monitoring'/'syslog'/'events')
    _HB_MODE: str = 'standalone'    # 'embedded' (web process) or 'standalone'
    _HB_EVERY: int = 10             # seconds between beats
    _HB_VERSION: str | None = None  # optional code version string
    _HB_DEAD_AFTER: int = 150       # drop instances unseen this long (crashed pods)

    # Single-owner services (monitor, events) set this so only the lease holder
    # does the work; other replicas are hot standby. Active-active services
    # (syslog) leave it False. TTL must be a few beats so a missed beat ≠ failover.
    _LEADER_GATED: bool = False
    _LEADER_TTL: int = 30

    # ── context hooks (overridable; sensible defaults from status()) ───────────
    def _hb_store(self):
        return getattr(self, '_service_instances_store', None)

    def _hb_key(self) -> str | None:
        return self._HB_KEY

    def _hb_instance_id(self) -> str:
        v = getattr(self, '_hb_iid', None)
        if v is None:
            v = f'{hostname()}:{os.getpid()}:{self._hb_key()}'
            self._hb_iid = v
        return v

    def _hb_status(self) -> dict:
        try:
            return self.status() or {}
        except Exception:  # pylint: disable=broad-except
            return {}

    def _hb_running(self) -> bool:
        r = getattr(self, 'running', None)
        if isinstance(r, bool):
            return r
        return bool(self._hb_status().get('running'))

    def _hb_detail(self) -> dict:
        s = self._hb_status()
        keys = ('interval', 'poll_secs', 'udp_port', 'tcp_port', 'tls_port', 'next_in')
        return {k: s.get(k) for k in keys if s.get(k) is not None}

    def _hb_last_cycle(self) -> float | None:
        s = self._hb_status()
        return s.get('last_run') or s.get('last_cycle') or s.get('last_activity')

    def _hb_control_url(self) -> str | None:
        # Set by start_control_server() when the HTTP poke listener is enabled.
        return getattr(self, '_control_url', None)

    # ── poke target: run a reconcile + drain now (called by the control server) ─
    def _control_reconcile(self) -> dict:
        """Converge immediately: re-run the service's config reconcile (if it has
        one), drain queued commands and refresh the heartbeat.  This is what the
        HTTP poke triggers so a desired-state change / command takes effect now
        instead of at the next poll."""
        fn = getattr(self, '_reconcile_once', None)
        if fn is not None:
            try:
                fn()
            except Exception:  # pylint: disable=broad-except
                pass
        self._drain_commands()
        self._heartbeat_write()
        return {'ok': True, 'key': self._hb_key(), 'running': self._hb_running()}

    # ── imperative commands (drained from the shared queue) ────────────────────
    _HB_DRAIN_MAX = 20      # commands handled per tick (backstop against a flood)

    def _hb_commands_store(self):
        return getattr(self, '_service_commands_store', None)

    def _drain_commands(self) -> None:
        """Claim + run any queued commands for this service, then ack the result.

        Runs on the hosting instance (this is the same loop that writes the
        heartbeat), so commands enqueued from the web UI execute wherever the
        service actually lives — embedded here or in a remote pod.  Best-effort:
        a handler error is recorded as a failed command, never raised."""
        store = self._hb_commands_store()
        key = self._hb_key()
        apply_fn = getattr(self, '_apply_command', None)
        if store is None or not key or apply_fn is None:
            return
        for _ in range(self._HB_DRAIN_MAX):
            cmd = store.claim_next(key, self._hb_instance_id())
            if cmd is None:
                break
            try:
                ok, result = apply_fn(cmd.get('action', ''), cmd.get('args') or {})
            except Exception as exc:  # pylint: disable=broad-except
                ok, result = False, str(exc)
            store.complete(cmd.get('id'), bool(ok), str(result))

    # ── leadership (single-owner services: lease holder does the work) ─────────
    def _leader_store(self):
        return getattr(self, '_service_leader_store', None)

    def _work_allowed(self) -> bool:
        """Whether THIS instance should do the service's work right now.  Always
        true for non-gated (active-active) services; for gated ones, only the lease
        holder.  With no leader store available it defaults to true (sole owner) so
        the single-process / embedded case keeps working unchanged."""
        if not self._LEADER_GATED:
            return True
        if self._leader_store() is None:
            return True
        return bool(getattr(self, '_is_leader', False))

    def _renew_leadership(self) -> None:
        """Acquire or renew the lease (gated services only); refresh ``_is_leader``."""
        if not self._LEADER_GATED:
            self._is_leader = True
            return
        store = self._leader_store()
        if store is None:
            self._is_leader = True          # back-compat: behave as sole owner
            return
        self._is_leader = store.try_acquire(
            self._hb_key(), self._hb_instance_id(),
            host=hostname(), ttl=self._LEADER_TTL)

    # ── write ───────────────────────────────────────────────────────────────────
    def _heartbeat_write(self) -> None:
        store = self._hb_store()
        key = self._hb_key()
        if store is None or not key:
            return
        detail = self._hb_detail()
        if self._LEADER_GATED:
            detail = {**detail, 'leader': bool(getattr(self, '_is_leader', False))}
        store.heartbeat(
            self._hb_instance_id(), key,
            mode=self._HB_MODE, running=self._hb_running(),
            host=hostname(), pid=os.getpid(), version=self._HB_VERSION,
            control_url=self._hb_control_url(), last_cycle_at=self._hb_last_cycle(),
            detail=detail)

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def start_heartbeat(self, *, key: str | None = None, mode: str | None = None,
                        every: int | None = None) -> None:
        """Start the background heartbeat thread (idempotent).  ``key``/``mode``
        let the host stamp identity without subclassing (the web admin passes the
        service key + 'embedded')."""
        if key:
            self._HB_KEY = key
        if mode:
            self._HB_MODE = mode
        if getattr(self, '_hb_thread', None) is not None:
            return
        if self._hb_store() is None or not self._hb_key():
            return
        self._hb_stop = threading.Event()
        interval = every or self._HB_EVERY
        # Drop this process's own restart 'zombies' (same host+mode+service, old PID)
        # so a restart leaves exactly one live row, not an accumulating pile.
        store = self._hb_store()
        if store is not None and self._hb_key():
            try:
                store.clear_others(self._hb_key(), self._HB_MODE, hostname(),
                                   self._hb_instance_id())
            except Exception:  # pylint: disable=broad-except
                pass
        self._renew_leadership()         # claim the lease before the first beat
        self._heartbeat_write()          # appear immediately, don't wait a full beat
        self._drain_commands()           # pick up anything already queued

        def _loop():
            beat = 0
            while not self._hb_stop.wait(interval):
                self._renew_leadership()
                self._heartbeat_write()
                self._drain_commands()
                beat += 1
                if beat % 6 == 0:        # ~once a minute: drop long-dead instances
                    self._heartbeat_prune()

        self._hb_thread = threading.Thread(
            target=_loop, name=f'hb-{self._hb_key()}', daemon=True)
        self._hb_thread.start()

    def _heartbeat_prune(self) -> None:
        """Drop instance rows not seen for a while — pods that crashed without a
        clean shutdown (a different host, so clear_others didn't catch them)."""
        store = self._hb_store()
        if store is not None:
            try:
                store.prune(self._HB_DEAD_AFTER)
            except Exception:  # pylint: disable=broad-except
                pass

    def stop_heartbeat(self) -> None:
        """Stop beating, release the lease (instant failover) and mark this instance
        cleanly down (best-effort)."""
        ev = getattr(self, '_hb_stop', None)
        if ev is not None:
            ev.set()
        if self._LEADER_GATED:
            lstore = self._leader_store()
            if lstore is not None and self._hb_key():
                lstore.release(self._hb_key(), self._hb_instance_id())
        store = self._hb_store()
        if store is not None and self._hb_key():
            store.mark_down(self._hb_instance_id())
