#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``event_cooldowns`` — ``rule_uid -> last_fire`` (epoch seconds).

Replaces the former in-memory cooldown dict so a rule does not re-fire after a
restart and a rule's cooldown is honoured across processes.  Backed by a pluggable
:class:`lib.db.BaseConnector`; upserts use the portable UPDATE-then-INSERT pattern.
Reached through the :class:`~lib.services.events.store.EventStateStore` facade.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

# uid is the PK (project convention); the natural key (rule_uid) stays the
# meaningful lookup key, kept UNIQUE.
_COOLDOWN = TableSpec(
    name='event_cooldowns',
    columns=(
        Column('uid',       'TEXT', primary_key=True),
        Column('rule_uid',  'TEXT', nullable=False, default="''", unique=True),
        Column('last_fire', 'REAL', nullable=False, default='0'),
    ),
)


class CooldownsStore:
    """Per-rule cooldown timestamps (``event_cooldowns``)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_COOLDOWN)

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
                'INSERT INTO event_cooldowns(uid, rule_uid, last_fire) VALUES(?,?,?)',
                (str(uuid.uuid4()), rule_uid, float(last_fire)))
        self._db.commit()
