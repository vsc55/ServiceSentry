#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite-backed audit log store.

Stores audit entries in the ``audit`` table inside ``data.db`` (shared with
the history store).  Thread-safe: each thread maintains its own connection
via ``threading.local``.

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
import os
import sqlite3
import threading


class AuditStore:
    """Thread-safe SQLite audit log."""

    def __init__(self, db_path: str) -> None:
        self._path  = db_path
        self._local = threading.local()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._bootstrap()

    # ── Connection ────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30, isolation_level=None)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            conn.execute('PRAGMA synchronous=NORMAL')
            self._local.conn = conn
        return conn

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        conn = self._conn()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      TEXT    NOT NULL DEFAULT '',
                event   TEXT    NOT NULL DEFAULT '',
                user    TEXT    NOT NULL DEFAULT '',
                ip      TEXT    NOT NULL DEFAULT '',
                detail  TEXT    NOT NULL DEFAULT ''
            )
        ''')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_audit_id ON audit(id DESC)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_audit_event ON audit(event)'
        )
        conn.commit()

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
        after each insert, so historical data migrated from audit.json is
        never wiped out all at once.
        """
        raw_detail = (
            json.dumps(detail, ensure_ascii=False)
            if not isinstance(detail, str) else detail
        )
        conn = self._conn()
        conn.execute(
            'INSERT INTO audit(ts, event, user, ip, detail) VALUES(?,?,?,?,?)',
            (ts, event, user, ip, raw_detail),
        )
        conn.commit()
        if max_entries > 0:
            self._prune_one(max_entries)

    def delete_all(self) -> int:
        """Delete every entry.  Returns the number deleted."""
        conn = self._conn()
        conn.execute('DELETE FROM audit')
        deleted = conn.execute('SELECT changes()').fetchone()[0]
        conn.commit()
        return deleted

    def delete_by_id(self, entry_id: int) -> bool:
        """Delete one entry by its primary key.  Returns True if found."""
        conn = self._conn()
        conn.execute('DELETE FROM audit WHERE id = ?', (entry_id,))
        deleted = conn.execute('SELECT changes()').fetchone()[0]
        conn.commit()
        return deleted > 0

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_all(self, *, newest_first: bool = True) -> list[dict]:
        """Return all entries as a list of dicts."""
        order = 'DESC' if newest_first else 'ASC'
        rows = self._conn().execute(
            f'SELECT id, ts, event, user, ip, detail FROM audit ORDER BY id {order}'
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count(self) -> int:
        row = self._conn().execute('SELECT COUNT(*) FROM audit').fetchone()
        return row[0] if row else 0

    # ── Migration ─────────────────────────────────────────────────────────────

    def migrate_from_list(self, entries: list[dict]) -> int:
        """Bulk-insert entries from audit.json format.

        Skips the operation if the audit table already has rows (migration
        already done).  Returns the number of rows inserted.
        """
        if self.count() > 0:
            return 0
        if not entries:
            return 0
        conn = self._conn()
        rows = []
        for e in entries:
            detail = e.get('detail', '')
            if not isinstance(detail, str):
                detail = json.dumps(detail, ensure_ascii=False)
            rows.append((
                e.get('ts', ''),
                e.get('event', ''),
                e.get('user', ''),
                e.get('ip', ''),
                detail,
            ))
        conn.executemany(
            'INSERT INTO audit(ts, event, user, ip, detail) VALUES(?,?,?,?,?)',
            rows,
        )
        conn.commit()
        return len(rows)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _prune_one(self, max_entries: int) -> None:
        """Delete the single oldest entry if the table exceeds *max_entries*.

        Sliding-window strategy: removes at most one row per insert so
        migrated historical data is preserved for as long as possible and
        is gradually displaced by new entries rather than wiped all at once.
        """
        conn = self._conn()
        row = conn.execute('SELECT COUNT(*) FROM audit').fetchone()
        if row and row[0] > max_entries:
            conn.execute(
                'DELETE FROM audit WHERE id = (SELECT MIN(id) FROM audit)'
            )
            conn.commit()

    def close(self) -> None:
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None


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
