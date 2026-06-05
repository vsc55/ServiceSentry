#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational audit-log store.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL supported through the same interface).

Schema
------
    id      — auto-increment PK (insertion order = chronological order)
    ts      — ISO 8601 timestamp string (kept for display compatibility)
    event   — event code  (e.g. 'login_ok', 'config_saved')
    user    — username or 'system'
    ip      — client IP or 'internal'
    detail  — JSON-encoded extra data (string / list / dict)
"""

from __future__ import annotations

import json

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='audit',
    columns=(
        Column('id',     'AUTOINCREMENT', primary_key=True),
        Column('ts',     'TEXT', nullable=False, default="''"),
        Column('event',  'TEXT', nullable=False, default="''"),
        Column('user',   'TEXT', nullable=False, default="''"),
        Column('ip',     'TEXT', nullable=False, default="''"),
        Column('detail', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(
        Index('idx_audit_id',    ('id DESC',)),
        Index('idx_audit_event', ('event',)),
    ),
)


class AuditStore:
    """Relational audit log (backend-agnostic)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert(
        self,
        ts: str,
        event: str,
        user: str,
        ip: str,
        detail: str | list | dict,
        *,
        max_entries: int = 0,
    ) -> None:
        """Insert one audit entry.

        When *max_entries* > 0 the table is kept within that bound using a
        **sliding-window** strategy: only the single oldest entry is removed
        after each insert, so historical data is never wiped out all at once.
        """
        raw_detail = (
            json.dumps(detail, ensure_ascii=False)
            if not isinstance(detail, str) else detail
        )
        self._db.execute(
            'INSERT INTO audit(ts, event, user, ip, detail) VALUES(?,?,?,?,?)',
            (ts, event, user, ip, raw_detail),
        )
        self._db.commit()
        if max_entries > 0:
            self._prune_one(max_entries)

    def delete_all(self) -> int:
        """Delete every entry.  Returns the number deleted."""
        with self._db.transaction():
            deleted = self._db.execute('DELETE FROM audit')
        return deleted

    def delete_by_id(self, entry_id: int) -> bool:
        """Delete one entry by its primary key.  Returns True if found."""
        with self._db.transaction():
            deleted = self._db.execute('DELETE FROM audit WHERE id = ?', (entry_id,))
        return deleted > 0

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_all(self, *, newest_first: bool = True) -> list[dict]:
        """Return all entries as a list of dicts."""
        order = 'DESC' if newest_first else 'ASC'
        rows = self._db.fetchall(
            f'SELECT id, ts, event, user, ip, detail FROM audit ORDER BY id {order}'
        )
        return [_row_to_dict(r) for r in rows]

    def count(self) -> int:
        row = self._db.fetchone('SELECT COUNT(*) FROM audit')
        return row[0] if row else 0

    # ── Migration ─────────────────────────────────────────────────────────────

    def migrate_from_list(self, entries: list[dict]) -> int:
        """Bulk-insert entries from audit.json format.

        Skips the operation if the audit table already has rows.  Returns the
        number of rows inserted.
        """
        if self.count() > 0 or not entries:
            return 0
        rows = []
        for e in entries:
            detail = e.get('detail', '')
            if not isinstance(detail, str):
                detail = json.dumps(detail, ensure_ascii=False)
            rows.append((
                e.get('ts', ''), e.get('event', ''),
                e.get('user', ''), e.get('ip', ''), detail,
            ))
        with self._db.transaction():
            self._db.executemany(
                'INSERT INTO audit(ts, event, user, ip, detail) VALUES(?,?,?,?,?)',
                rows,
            )
        return len(rows)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _prune_one(self, max_entries: int) -> None:
        """Delete the single oldest entry if the table exceeds *max_entries*."""
        row = self._db.fetchone('SELECT COUNT(*) FROM audit')
        if row and row[0] > max_entries:
            self._db.execute('DELETE FROM audit WHERE id = (SELECT MIN(id) FROM audit)')
            self._db.commit()

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(row: tuple) -> dict:
    entry_id, ts, event, user, ip, detail_raw = row
    try:
        detail = json.loads(detail_raw) if detail_raw else ''
    except (ValueError, TypeError):
        detail = detail_raw
    return {
        '_id':    entry_id,
        'ts':     ts,
        'event':  event,
        'user':   user,
        'ip':     ip,
        'detail': detail,
    }
