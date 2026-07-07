#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``EventStateStore`` — persistent state for the decoupled event worker.

Two tiny, independent tables live in their own modules (``cooldowns`` and
``cursor``); this facade composes them into the single handle the worker is given
(``_attach_event_state``), so the per-table split leaves the consumer API unchanged:

* ``event_cooldowns`` — :class:`~lib.services.events.store.cooldowns.CooldownsStore`
* ``event_cursor``    — :class:`~lib.services.events.store.cursor.CursorStore`

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite / PostgreSQL / MySQL).
"""

from __future__ import annotations

from lib.db import BaseConnector

from .cooldowns import CooldownsStore
from .cursor import CursorStore


class EventStateStore:
    """Cooldown + per-source cursor state for the event worker (facade)."""

    def __init__(self, db: BaseConnector) -> None:
        self._cooldowns = CooldownsStore(db)
        self._cursor = CursorStore(db)

    # ── cooldown ──────────────────────────────────────────────────────────────
    def cooldowns(self) -> dict[str, float]:
        return self._cooldowns.cooldowns()

    def set_cooldown(self, rule_uid: str, last_fire: float) -> None:
        self._cooldowns.set_cooldown(rule_uid, last_fire)

    # ── cursor ────────────────────────────────────────────────────────────────
    def cursor(self, source: str) -> int | None:
        return self._cursor.cursor(source)

    def set_cursor(self, source: str, last_id: int) -> None:
        self._cursor.set_cursor(source, last_id)
