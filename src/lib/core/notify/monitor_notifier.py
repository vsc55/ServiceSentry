#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cycle-scoped notifier for the monitor.

The monitor collects a cycle's check-state changes and flushes them **grouped per
channel** at the end of the cycle, routed by the notifications matrix
(``{channel}_on_{kind}`` for kinds ``down`` / ``recovery`` / ``warn``).  Each channel
decides how to group (Telegram batches emoji lines, Email sends one digest, Webhook and
Teams send one call per alert) — that logic lives in the channel's ``flush`` in
``lib/core/notify/<channel>/channel.py``, discovered from the registry, so this notifier
knows nothing channel-specific.

This replaces the monitor's old direct, threaded ``lib.providers.telegram.Telegram``
client. The monitor's cycle cuts its batch and hands it to ONE sender thread
(:meth:`MonitorNotifier.flush_later`), so a slow channel delays the alerts, not the checks.
"""

from __future__ import annotations

import queue
import socket
import threading

from lib.core.notify import registry
from lib.debug import DebugLevel


#: The batches waiting to be sent, and the one thread that sends them, in order.
_OUTBOX: queue.Queue = queue.Queue()
_SENDER_LOCK = threading.Lock()
_SENDER: list = []


def _sender_loop() -> None:
    while True:
        notifier, alerts, public_url = _OUTBOX.get()
        try:
            notifier._send(alerts, public_url)
        except Exception:  # pylint: disable=broad-except
            pass
        finally:
            _OUTBOX.task_done()


def drain(timeout: float = 30.0) -> bool:
    """Wait until every handed-over batch has been sent; whether it emptied in *timeout*.
    For whoever must know the alerts went out — a test, a shutdown."""
    import time                                                   # noqa: PLC0415
    end = time.monotonic() + timeout
    while _OUTBOX.unfinished_tasks:
        if time.monotonic() > end:
            return False
        time.sleep(0.02)
    return True


def _ensure_sender() -> None:
    with _SENDER_LOCK:
        if not _SENDER or not _SENDER[0].is_alive():
            t = threading.Thread(target=_sender_loop, name='notify-sender', daemon=True)
            t.start()
            _SENDER[:] = [t]


class MonitorNotifier:
    """Accumulates a monitoring cycle's alerts and flushes them grouped per channel.

    Routing/channel access goes through the device's core notification router
    (``wa._notify``) when present, so the monitor sends *through* the router — the same
    channel registry every other subsystem uses; it falls back to the device itself when a
    router isn't wired (legacy surface: ``_read_config_file`` / ``_CONFIG_FILE`` / ``_dbg``).
    """

    def __init__(self, wa, *, route_kind: str | None = None):
        # Prefer the core router (owns the channel stores + config surface); fall back to
        # the device's own surface so tests and any un-migrated caller keep working.
        self._wa = getattr(wa, '_notify', None) or wa
        self._alerts: list[dict] = []
        # Alerts are added from the module threads â€” a straggler's among them, landing while
        # the cycle cuts its batch â€” so the add and the cut must not interleave: an append to
        # the list just handed over was an alert sent with the wrong batch or not at all.
        self._alerts_lock = threading.Lock()
        # When set, the WHOLE flush routes as this one kind (``notifications|{channel}_on_
        # {route_kind}``) regardless of each alert's own kind — e.g. an on-demand "Run all"
        # routes as a single ``manual_run`` event, while its digest still shows the real
        # down/recovery states. None → the normal per-kind daemon routing.
        self._route_kind = route_kind

    def add(self, kind: str, module: str, item: str, message: str,
            also: str = '') -> None:
        """Buffer one alert. ``kind`` ∈ {down, recovery, warn}.

        ``also`` is a SECOND kind this alert may be routed by — a module saying "this failure
        is a kind of its own" (an SNMP device that answered nothing is the collection not
        happening, not a check that failed). It is additive: a channel takes the alert if
        EITHER row is ticked.

        Additive and not a replacement, because a matrix cell is stored only when somebody
        ticks it and reads false until then. Routing by the new kind alone would have silently
        stopped every alert that arrives today as a `down` — the alert would not have failed,
        it would simply have stopped, which is the worst shape a notification bug takes.
        """
        if kind and message:
            with self._alerts_lock:
                self._alerts.append({'kind': kind, 'module': module or '',
                                     'item': item or '', 'message': message,
                                     'also': str(also or '')})

    def has_pending(self) -> bool:
        return bool(self._alerts)

    def flush(self, *, public_url: str = '') -> dict:
        """Send the buffered alerts grouped per enabled channel, then clear the buffer.

        Returns ``{channel: (ok, info)}`` for each channel attempted (empty when there
        was nothing to send)."""
        with self._alerts_lock:
            alerts, self._alerts = self._alerts, []
        if not alerts:
            return {}
        return self._send(alerts, public_url)

    def flush_later(self, *, public_url: str = '') -> bool:
        """Take the buffered alerts now and send them on the notifier's own thread.

        The monitor flushed inline, at the end of its cycle and inside its cycle lock: one
        webhook call per alert, ten seconds each when the receiver is down — which it often is
        in the very outage being reported. Three hundred DOWN alerts held the lock for some
        fifty minutes, with no check running and every «run now» answered «busy». The batch is
        still cut here, so what one cycle found goes out together and in order.

        Returns whether there was anything to send."""
        with self._alerts_lock:
            alerts, self._alerts = self._alerts, []
        if not alerts:
            return False
        _ensure_sender()
        _OUTBOX.put((self, alerts, public_url))
        return True

    def _send(self, alerts: list, public_url: str) -> dict:
        wa = self._wa
        try:
            cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        except Exception as exc:  # pylint: disable=broad-except
            wa._dbg(f"> Notify >> config read failed: {exc}", DebugLevel.error)
            return {}
        notif = cfg.get('notifications') or {}
        hostname = socket.gethostname()
        results: dict[str, tuple] = {}

        for name, ch in registry.channels().items():
            if self._route_kind:
                # Route the whole batch as one kind (e.g. manual_run): all-or-nothing per channel.
                picked = alerts if notif.get(f'{name}_on_{self._route_kind}', False) else []
            else:
                picked = [a for a in alerts
                          if notif.get(f'{name}_on_{a["kind"]}', False)
                          or (a.get('also')
                              and notif.get(f'{name}_on_{a["also"]}', False))]
            if not picked:
                continue
            try:
                results[name] = ch.flush(wa, cfg, picked, hostname, public_url)
            except Exception as exc:  # pylint: disable=broad-except
                results[name] = (False, str(exc))
                wa._dbg(f"> Notify > {name} >> {type(exc).__name__}: {exc}", DebugLevel.error)
        wa._dbg(f"> Notify >> flushed {len(alerts)} alert(s): "
                f"{ {k: v[0] for k, v in results.items()} }", DebugLevel.info)
        return results
