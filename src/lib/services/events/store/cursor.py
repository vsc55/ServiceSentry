#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``event_cursor`` — ``source -> last_id`` (highest source-table row id evaluated).

The worker reads new rows (``id > last_id``) and advances the cursor, so events are
consumed off the ingestion path across restarts / processes.  Backed by a pluggable
:class:`lib.db.BaseConnector`; upserts use the portable UPDATE-then-INSERT pattern.
Reached through the :class:`~lib.services.events.store.EventStateStore` facade.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

# uid is the PK (project convention); the natural key (source) stays the meaningful
# lookup key, kept UNIQUE.
_CURSOR = TableSpec(
    name='event_cursor',
    columns=(
        Column('uid',     'TEXT', primary_key=True),
        Column('source',  'TEXT', nullable=False, default="''", unique=True),
        Column('last_id', 'INTEGER', nullable=False, default='0'),
    ),
)


class CursorStore:
    """Per-source ingestion cursor (``event_cursor``)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_CURSOR)

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
                'INSERT INTO event_cursor(uid, source, last_id) VALUES(?,?,?)',
                (str(uuid.uuid4()), source, int(last_id)))
        self._db.commit()
