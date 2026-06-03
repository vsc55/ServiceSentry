#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational SQLite store for WebAdmin user groups.

``uid`` is the primary key for groups.  The ``name`` column is UNIQUE.
The group-role relationship lives in ``groups_roles``, which uses UIDs on
both sides.

Schema::

    groups(uid PK, name UNIQUE, description, enabled,
           created_at, updated_at, updated_by)

    groups_roles(uid PK, group_uid, role_uid, UNIQUE(group_uid, role_uid),
                 created_at, created_by)

Thread-safe: per-thread connections via ``threading.local``.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid as _uuid_mod


class GroupsStore:
    """Relational SQLite store for WebAdmin user groups."""

    def __init__(self, db_path: str) -> None:
        self._path  = db_path
        self._local = threading.local()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._bootstrap()

    # ── Connection ────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(
                self._path, check_same_thread=False,
                timeout=30, isolation_level=None,
            )
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            conn.execute('PRAGMA synchronous=NORMAL')
            self._local.conn = conn
        return conn

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        """Create tables if they don't exist yet."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute('PRAGMA table_info(groups)').fetchall()}
        if not cols:
            conn.execute('''
                CREATE TABLE groups (
                    uid         TEXT PRIMARY KEY,
                    name        TEXT NOT NULL DEFAULT '' UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    enabled     INTEGER NOT NULL DEFAULT 1,
                    created_at  TEXT NOT NULL DEFAULT '',
                    updated_at  TEXT NOT NULL DEFAULT '',
                    updated_by  TEXT NOT NULL DEFAULT ''
                )
            ''')
            conn.execute('''
                CREATE TABLE groups_roles (
                    uid        TEXT PRIMARY KEY,
                    group_uid  TEXT NOT NULL,
                    role_uid   TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    UNIQUE (group_uid, role_uid)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_gr_group ON groups_roles(group_uid)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_gr_role  ON groups_roles(role_uid)')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS groups_roles (
                uid        TEXT PRIMARY KEY,
                group_uid  TEXT NOT NULL,
                role_uid   TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                UNIQUE (group_uid, role_uid)
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_gr_group ON groups_roles(group_uid)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_gr_role  ON groups_roles(role_uid)')
        # Ensure unique index on name (covers tables created without UNIQUE clause)
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_name ON groups(name)')
        # Backfill empty audit columns for existing rows
        import time as _t
        _now = _t.strftime('%Y-%m-%dT%H:%M:%SZ', _t.gmtime())
        conn.execute(
            'UPDATE groups SET created_at=?, updated_at=?, updated_by=? WHERE created_at=""',
            (_now, _now, 'system'),
        )

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return {uid: {uid, name, description, roles, enabled,
                         created_at, updated_at, updated_by}}."""
        conn = self._conn()
        groups: dict = {}
        for row in conn.execute(
            'SELECT uid, name, description, enabled, created_at, updated_at, updated_by '
            'FROM groups'
        ).fetchall():
            uid, name, desc, enabled, created_at, updated_at, updated_by = row
            groups[uid] = {
                'uid':         uid,
                'name':        name,
                'description': desc,
                'enabled':     bool(enabled),
                'roles':       [],
                'created_at':  created_at or '',
                'updated_at':  updated_at or '',
                'updated_by':  updated_by or '',
            }
        for row in conn.execute(
            'SELECT uid, group_uid, role_uid, created_at, created_by '
            'FROM groups_roles ORDER BY group_uid, role_uid'
        ).fetchall():
            _, grp_uid, role_uid, r_created_at, r_created_by = row
            if grp_uid in groups:
                groups[grp_uid]['roles'].append(role_uid)
                groups[grp_uid].setdefault('roles_audit', {})[role_uid] = {
                    'created_at': r_created_at or '',
                    'created_by': r_created_by or '',
                }
        return groups

    def count(self) -> int:
        row = self._conn().execute('SELECT COUNT(*) FROM groups').fetchone()
        return row[0] if row else 0

    def count_roles(self) -> int:
        row = self._conn().execute('SELECT COUNT(*) FROM groups_roles').fetchone()
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, groups: dict) -> bool:
        """Replace all groups atomically, preserving created_at and doing smart role diff."""
        import time as _time  # noqa: PLC0415
        now = _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())
        try:
            conn = self._conn()
            conn.execute('BEGIN')
            existing_created = {
                r[0]: r[1]
                for r in conn.execute('SELECT uid, created_at FROM groups').fetchall()
            }
            existing_role_ts = {
                (r[0], r[1]): {'uid': r[2], 'created_at': r[3], 'created_by': r[4]}
                for r in conn.execute(
                    'SELECT group_uid, role_uid, uid, created_at, created_by FROM groups_roles'
                ).fetchall()
            }
            conn.execute('DELETE FROM groups_roles')
            conn.execute('DELETE FROM groups')
            for uid, d in groups.items():
                created_at = existing_created.get(uid) or d.get('created_at') or now
                updated_at = d.get('updated_at') or now
                updated_by = d.get('updated_by') if d.get('updated_by') is not None else ''
                conn.execute(
                    'INSERT INTO groups(uid,name,description,enabled,'
                    'created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)',
                    (uid, d.get('name', uid), d.get('description', ''),
                     1 if d.get('enabled', True) else 0,
                     created_at, updated_at, updated_by),
                )
                for role_uid in d.get('roles', []):
                    if not role_uid:
                        continue
                    existing = existing_role_ts.get((uid, role_uid), {})
                    conn.execute(
                        'INSERT INTO groups_roles(uid,group_uid,role_uid,created_at,created_by)'
                        ' VALUES(?,?,?,?,?)',
                        (existing.get('uid') or str(_uuid_mod.uuid4()), uid, str(role_uid),
                         existing.get('created_at') or now,
                         existing.get('created_by') or d.get('updated_by') or ''),
                    )
            conn.execute('COMMIT')
            return True
        except Exception:  # pylint: disable=broad-except
            try:
                self._conn().execute('ROLLBACK')
            except Exception:  # pylint: disable=broad-except
                pass
            return False

    def upsert(self, uid: str, data: dict) -> bool:
        """Insert or replace a single group, preserving created_at and doing smart role diff."""
        import time as _time  # noqa: PLC0415
        now = _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())
        try:
            conn = self._conn()
            conn.execute('BEGIN')
            existing_created = conn.execute(
                'SELECT created_at FROM groups WHERE uid = ?', (uid,)
            ).fetchone()
            created_at = (existing_created[0] if existing_created else None) or data.get('created_at') or now
            updated_at = data.get('updated_at') or now
            updated_by = data.get('updated_by') if data.get('updated_by') is not None else ''
            conn.execute(
                'INSERT OR REPLACE INTO groups(uid,name,description,enabled,'
                'created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)',
                (uid, data.get('name', uid), data.get('description', ''),
                 1 if data.get('enabled', True) else 0,
                 created_at, updated_at, updated_by),
            )
            existing_roles = {
                r[0]: {'row_uid': r[1], 'created_at': r[2], 'created_by': r[3]}
                for r in conn.execute(
                    'SELECT role_uid, uid, created_at, created_by '
                    'FROM groups_roles WHERE group_uid=?', (uid,)
                ).fetchall()
            }
            new_roles = {str(r) for r in data.get('roles', []) if r}
            for role_uid in set(existing_roles) - new_roles:
                conn.execute('DELETE FROM groups_roles WHERE group_uid=? AND role_uid=?', (uid, role_uid))
            for role_uid in new_roles - set(existing_roles):
                conn.execute(
                    'INSERT INTO groups_roles(uid,group_uid,role_uid,created_at,created_by)'
                    ' VALUES(?,?,?,?,?)',
                    (str(_uuid_mod.uuid4()), uid, role_uid, now, updated_by),
                )
            conn.execute('COMMIT')
            return True
        except Exception:  # pylint: disable=broad-except
            try:
                self._conn().execute('ROLLBACK')
            except Exception:  # pylint: disable=broad-except
                pass
            return False

    def delete(self, uid: str) -> bool:
        """Delete a group and its role assignments."""
        try:
            conn = self._conn()
            conn.execute('BEGIN')
            conn.execute('DELETE FROM groups_roles WHERE group_uid = ?', (uid,))
            conn.execute('DELETE FROM groups WHERE uid = ?', (uid,))
            deleted = conn.execute('SELECT changes()').fetchone()[0]
            conn.execute('COMMIT')
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            try:
                self._conn().execute('ROLLBACK')
            except Exception:  # pylint: disable=broad-except
                pass
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
