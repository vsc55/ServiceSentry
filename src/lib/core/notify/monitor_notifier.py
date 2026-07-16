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
client — there is no background sender thread; sending happens once, at flush time.
"""

from __future__ import annotations

import socket

from lib.core.notify import registry
from lib.debug import DebugLevel


class MonitorNotifier:
    """Accumulates a monitoring cycle's alerts and flushes them grouped per channel.

    Routing/channel access goes through the host's core notification router
    (``wa._notify``) when present, so the monitor sends *through* the router — the same
    channel registry every other subsystem uses; it falls back to the host itself when a
    router isn't wired (legacy surface: ``_read_config_file`` / ``_CONFIG_FILE`` / ``_dbg``).
    """

    def __init__(self, wa, *, route_kind: str | None = None):
        # Prefer the core router (owns the channel stores + config surface); fall back to
        # the host's own surface so tests and any un-migrated caller keep working.
        self._wa = getattr(wa, '_notify', None) or wa
        self._alerts: list[dict] = []
        # When set, the WHOLE flush routes as this one kind (``notifications|{channel}_on_
        # {route_kind}``) regardless of each alert's own kind — e.g. an on-demand "Run all"
        # routes as a single ``manual_run`` event, while its digest still shows the real
        # down/recovery states. None → the normal per-kind daemon routing.
        self._route_kind = route_kind

    def add(self, kind: str, module: str, item: str, message: str) -> None:
        """Buffer one alert. ``kind`` ∈ {down, recovery, warn}."""
        if kind and message:
            self._alerts.append({'kind': kind, 'module': module or '',
                                 'item': item or '', 'message': message})

    def has_pending(self) -> bool:
        return bool(self._alerts)

    def flush(self, *, public_url: str = '') -> dict:
        """Send the buffered alerts grouped per enabled channel, then clear the buffer.

        Returns ``{channel: (ok, info)}`` for each channel attempted (empty when there
        was nothing to send)."""
        alerts, self._alerts = self._alerts, []
        if not alerts:
            return {}
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
                picked = [a for a in alerts if notif.get(f'{name}_on_{a["kind"]}', False)]
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
