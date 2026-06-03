#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic key-value (JSON-blob) store for WebAdmin entities.

Handles ``users`` and ``groups``.  Sessions and roles have their own
dedicated stores with proper column schemas:

    users   — key = username,    data = JSON blob   (this module)
    groups  — key = group name,  data = JSON blob   (this module)
    sessions → sessions_store.py / SessionsStore
    roles    → roles_store.py    / RolesStore

Thread-safe: per-thread connections via ``threading.local``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading


_TABLES: tuple = ()   # users → UsersStore, groups → GroupsStore, sessions → SessionsStore, roles → RolesStore


class EntityStore:
    """Key-value persistence for WebAdmin entities.

    The ``save_all`` / ``load`` pair mirrors the previous atomic-JSON-file
    pattern: on every persist, the table is replaced in a single transaction.
    """

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
        for table in _TABLES:
            conn.execute(f'''
                CREATE TABLE IF NOT EXISTS "{table}" (
                    key  TEXT PRIMARY KEY,
                    data TEXT NOT NULL DEFAULT "{{}}"
                )
            ''')
        conn.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self, table: str) -> dict:
        """Return all rows as ``{key: parsed_value}``."""
        rows = self._conn().execute(
            f'SELECT key, data FROM "{table}"'
        ).fetchall()
        result = {}
        for key, raw in rows:
            try:
                result[key] = json.loads(raw)
            except (ValueError, TypeError):
                result[key] = {}
        return result

    def count(self, table: str) -> int:
        row = self._conn().execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, table: str, data: dict) -> bool:
        """Replace every row in *table* with *data* atomically."""
        try:
            conn = self._conn()
            conn.execute(f'DELETE FROM "{table}"')
            for key, value in data.items():
                raw = json.dumps(value, ensure_ascii=False)
                conn.execute(
                    f'INSERT INTO "{table}"(key, data) VALUES(?, ?)',
                    (key, raw),
                )
            conn.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def upsert(self, table: str, key: str, value: dict) -> bool:
        """Insert or replace a single row.  More efficient for session writes."""
        try:
            conn = self._conn()
            conn.execute(
                f'INSERT OR REPLACE INTO "{table}"(key, data) VALUES(?, ?)',
                (key, json.dumps(value, ensure_ascii=False)),
            )
            conn.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, table: str, key: str) -> bool:
        """Delete one row.  Returns True when the row was found."""
        try:
            conn = self._conn()
            conn.execute(f'DELETE FROM "{table}" WHERE key = ?', (key,))
            deleted = conn.execute('SELECT changes()').fetchone()[0]
            conn.commit()
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    # ── Migration ─────────────────────────────────────────────────────────────

    def migrate_from_json(
        self, table: str, json_path: str, *, rename_bak: bool = True
    ) -> int:
        """Import entries from *json_path* if the table is empty.

        Renames the source file to ``<path>.bak`` after a successful import.
        Returns the number of rows inserted (0 if skipped).
        """
        if self.count(table) > 0:
            return 0
        if not os.path.isfile(json_path):
            return 0
        try:
            with open(json_path, encoding='utf-8') as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return 0
            self.save_all(table, data)
            count = self.count(table)
            if rename_bak and count > 0:
                try:
                    os.replace(json_path, json_path + '.bak')
                except OSError:
                    pass
            return count
        except (OSError, ValueError):
            return 0

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
