#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent state for the decoupled event worker.

Two tiny tables in the main DB so the worker survives restarts and several
processes (embedded WebAdmin / external service) agree:

* ``event_cooldowns`` — ``rule_uid -> last_fire`` (epoch seconds). Replaces the
  former in-memory cooldown dict so a rule does not re-fire after a restart and
  so a single rule's cooldown is honoured across processes.
* ``event_cursor``    — ``source -> last_id`` (the highest source-table row id
  already evaluated). The worker reads new rows (``id > last_id``) and advances
  the cursor, so events are consumed off the ingestion path.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite / PostgreSQL / MySQL).
Upserts use the portable UPDATE-then-INSERT pattern.
"""

from __future__ import annotations

from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_COOLDOWN = TableSpec(
    name='event_cooldowns',
    columns=(
        Column('rule_uid',  'TEXT', primary_key=True),
        Column('last_fire', 'REAL', nullable=False, default='0'),
    ),
)
_CURSOR = TableSpec(
    name='event_cursor',
    columns=(
        Column('source',  'TEXT', primary_key=True),
        Column('last_id', 'INTEGER', nullable=False, default='0'),
    ),
)


class EventStateStore:
    """Cooldown + per-source cursor state for the event worker."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_COOLDOWN)
        self._db.reconcile_table(_CURSOR)

    # ── cooldown ──────────────────────────────────────────────────────────────
    def cooldowns(self) -> dict[str, float]:
        """All ``rule_uid -> last_fire`` (used to warm the in-memory cache)."""
        rows = self._db.fetchall('SELECT rule_uid, last_fire FROM event_cooldowns')
        return {r[0]: float(r[1] or 0) for r in rows}

    def set_cooldown(self, rule_uid: str, last_fire: float) -> None:
        if not rule_uid:
            return
        n = self._db.execute(
            'UPDATE event_cooldowns SET last_fire=? WHERE rule_uid=?',
            (float(last_fire), rule_uid))
        if not n:
            self._db.execute(
                'INSERT INTO event_cooldowns(rule_uid, last_fire) VALUES(?,?)',
                (rule_uid, float(last_fire)))
        self._db.commit()

    # ── cursor ────────────────────────────────────────────────────────────────
    def cursor(self, source: str) -> int | None:
        """Last processed row id for *source*, or ``None`` when never seeded (so the
        worker can start from the current tail instead of replaying all history)."""
        row = self._db.fetchone(
            'SELECT last_id FROM event_cursor WHERE source=?', (source,))
        return int(row[0]) if row and row[0] is not None else None

    def set_cursor(self, source: str, last_id: int) -> None:
        n = self._db.execute(
            'UPDATE event_cursor SET last_id=? WHERE source=?',
            (int(last_id), source))
        if not n:
            self._db.execute(
                'INSERT INTO event_cursor(source, last_id) VALUES(?,?)',
                (source, int(last_id)))
        self._db.commit()
