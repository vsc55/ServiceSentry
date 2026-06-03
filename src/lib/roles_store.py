#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Columnar SQLite store for custom roles and built-in role name overrides.

Custom roles are identified by their stable ``uid`` PK.  The ``name`` column
is UNIQUE.  Built-in role customisations (name/description overrides) are
stored as rows in the same table using the built-in UID.

Schema::

    roles(uid PK, name UNIQUE, description, permissions TEXT/JSON,
          enabled, created_at, updated_at, updated_by)

Thread-safe: per-thread connections via ``threading.local``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading


class RolesStore:
    """Columnar SQLite store for custom roles and built-in role name overrides."""

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
        """Create tables if they don't exist; add missing columns to existing tables."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute('PRAGMA table_info(roles)').fetchall()}

        if not cols:
            conn.execute('''
                CREATE TABLE roles (
                    uid         TEXT PRIMARY KEY,
                    name        TEXT NOT NULL DEFAULT '' UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    permissions TEXT NOT NULL DEFAULT '[]',
                    enabled     INTEGER NOT NULL DEFAULT 1,
                    created_at  TEXT NOT NULL DEFAULT '',
                    updated_at  TEXT NOT NULL DEFAULT '',
                    updated_by  TEXT NOT NULL DEFAULT ''
                )
            ''')
        else:
            # Forward-migration: add audit columns if missing
            for col in ('created_at', 'updated_at', 'updated_by'):
                if col not in cols:
                    conn.execute(f'ALTER TABLE roles ADD COLUMN {col} TEXT NOT NULL DEFAULT ""')

        # Ensure unique index on name (covers tables created without UNIQUE clause)
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_roles_name ON roles(name)')
        # Backfill empty audit columns for existing rows
        import time as _t
        _now = _t.strftime('%Y-%m-%dT%H:%M:%SZ', _t.gmtime())
        conn.execute(
            'UPDATE roles SET created_at=?, updated_at=?, updated_by=? WHERE created_at=""',
            (_now, _now, 'system'),
        )

    # ── Read ──────────────────────────────────────────────────────────────────

    def load_roles(self) -> dict:
        """Return all role rows as ``{uid: {uid, name, description, permissions,
        enabled, created_at, updated_at, updated_by}}``."""
        rows = self._conn().execute(
            'SELECT uid, name, description, permissions, enabled, '
            'created_at, updated_at, updated_by FROM roles'
        ).fetchall()
        result = {}
        for r in rows:
            try:
                perms = json.loads(r[3]) if r[3] else []
            except (ValueError, TypeError):
                perms = []
            result[r[0]] = {
                'uid':         r[0],
                'name':        r[1],
                'description': r[2],
                'permissions': perms,
                'enabled':     bool(r[4]),
                'created_at':  r[5] or '',
                'updated_at':  r[6] or '',
                'updated_by':  r[7] or '',
            }
        return result

    def load_builtin_overrides(self) -> dict:
        """Return override rows for built-in roles as ``{builtin_uid: {name, description}}``.

        Built-in override rows have no permissions (permissions come from code).
        """
        from lib.web_admin.constants import BUILTIN_ROLE_UIDS as _BRUIDS
        builtin_uids = set(_BRUIDS.values())
        return {uid: data for uid, data in self.load_roles().items()
                if uid in builtin_uids}

    def count(self) -> int:
        """Return the number of rows in the roles table."""
        row = self._conn().execute('SELECT COUNT(*) FROM roles').fetchone()
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, roles: dict) -> bool:
        """Replace all role rows atomically.

        *roles* is ``{uid: {uid, name, description, permissions, enabled,
        created_at, updated_at, updated_by}}``.  Includes built-in override
        rows (UID as key, name/description only — permissions not stored).
        """
        try:
            conn = self._conn()
            conn.execute('BEGIN')
            conn.execute('DELETE FROM roles')
            for uid, d in roles.items():
                conn.execute(
                    'INSERT INTO roles(uid, name, description, permissions, enabled,'
                    ' created_at, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?)',
                    (uid, d.get('name', uid),
                     d.get('description', ''),
                     json.dumps(d.get('permissions', []), ensure_ascii=False),
                     1 if d.get('enabled', True) else 0,
                     d.get('created_at', ''),
                     d.get('updated_at', ''),
                     d.get('updated_by', '')),
                )
            conn.execute('COMMIT')
            return True
        except Exception:  # pylint: disable=broad-except
            try:
                self._conn().execute('ROLLBACK')
            except Exception:  # pylint: disable=broad-except
                pass
            return False

    def upsert_builtin_override(self, uid: str, name: str, description: str) -> bool:
        """Upsert a name/description override for a built-in role."""
        try:
            self._conn().execute(
                'INSERT OR REPLACE INTO roles(uid, name, description, permissions, enabled,'
                ' created_at, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?)',
                (uid, name, description, '[]', 1, '', '', ''),
            )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_role(self, uid: str) -> bool:
        """Delete a role row by UID.  Returns True if found."""
        try:
            conn = self._conn()
            conn.execute('DELETE FROM roles WHERE uid = ?', (uid,))
            deleted = conn.execute('SELECT changes()').fetchone()[0]
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
