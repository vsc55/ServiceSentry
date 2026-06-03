#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Columnar SQLite store for WebAdmin user accounts.

The user→group membership is stored in a dedicated ``users_groups`` table
using the user's stable UID and the group's stable UID, so renaming either
side never breaks the relationship.

Core fields have dedicated columns for efficient queries.  Variable or
optional fields (``_failed_attempts``, ``_locked_until``, LDAP/OIDC sync
fields, etc.) are stored in a JSON ``extra`` column so the schema remains
stable when new auth providers add fields.

Schema::

    users(username PK, uid UNIQUE, password_hash, role, display_name,
          email, lang, dark_mode, enabled, auth_source, extra TEXT/JSON)
    users_groups(user_uid, group_uid, PRIMARY KEY(user_uid, group_uid))

Thread-safe: per-thread connections via ``threading.local``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading


# Fields stored as individual columns; everything else goes into ``extra``.
_CORE = frozenset({
    'uid', 'password_hash', 'role', 'display_name', 'email',
    'lang', 'dark_mode', 'enabled', 'auth_source',
    'created_at', 'updated_at', 'updated_by',
    # 'groups' is intentionally excluded — stored in users_groups table
})


class UsersStore:
    """Relational SQLite store for WebAdmin user accounts."""

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
        """Create tables if they don't exist yet."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()}
        if not cols:
            self._create_tables(conn)
        else:
            # Forward-migration: add audit columns if missing
            for col in ('created_at', 'updated_at', 'updated_by'):
                if col not in cols:
                    conn.execute(f'ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT ""')
            conn.commit()
        # Backfill empty audit columns for existing rows
        import time as _t
        _now = _t.strftime('%Y-%m-%dT%H:%M:%SZ', _t.gmtime())
        conn.execute(
            'UPDATE users SET created_at=?, updated_at=?, updated_by=? WHERE created_at=""',
            (_now, _now, 'system'),
        )
        conn.commit()

        # Always ensure users_groups exists (no FK — managed by app)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users_groups (
                user_uid  TEXT NOT NULL,
                group_uid TEXT NOT NULL,
                PRIMARY KEY (user_uid, group_uid)
            )
        ''')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_users_groups_user '
            'ON users_groups(user_uid)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_users_groups_group '
            'ON users_groups(group_uid)'
        )
        conn.commit()

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute('''
            CREATE TABLE users (
                username      TEXT PRIMARY KEY,
                uid           TEXT UNIQUE NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL DEFAULT '',
                role          TEXT NOT NULL DEFAULT '',
                display_name  TEXT NOT NULL DEFAULT '',
                email         TEXT NOT NULL DEFAULT '',
                lang          TEXT NOT NULL DEFAULT '',
                dark_mode     INTEGER,
                enabled       INTEGER NOT NULL DEFAULT 1,
                auth_source   TEXT NOT NULL DEFAULT 'local',
                extra         TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL DEFAULT '',
                updated_at    TEXT NOT NULL DEFAULT '',
                updated_by    TEXT NOT NULL DEFAULT ''
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_users_uid  ON users(uid)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)')
        conn.execute('''
            CREATE TABLE users_groups (
                user_uid  TEXT NOT NULL,
                group_uid TEXT NOT NULL,
                PRIMARY KEY (user_uid, group_uid)
            )
        ''')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_users_groups_user  ON users_groups(user_uid)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_users_groups_group ON users_groups(group_uid)'
        )
        conn.commit()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _insert_user_row(self, conn: sqlite3.Connection, username: str, data: dict,
                         *, replace: bool = False) -> str:
        """Insert/replace the user row.  Returns the uid used."""
        uid  = data.get('uid') or username
        dm   = data.get('dark_mode')
        extra = {k: v for k, v in data.items() if k not in _CORE and k != 'groups'}
        verb = 'INSERT OR REPLACE' if replace else 'INSERT OR IGNORE'
        conn.execute(
            f'{verb} INTO users'
            '(username, uid, password_hash, role, display_name, email,'
            ' lang, dark_mode, enabled, auth_source, extra,'
            ' created_at, updated_at, updated_by)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (username, uid,
             data.get('password_hash', ''), data.get('role', ''),
             data.get('display_name', ''), data.get('email', ''),
             data.get('lang', ''),
             None if dm is None else (1 if dm else 0),
             1 if data.get('enabled', True) else 0,
             data.get('auth_source', 'local'),
             json.dumps(extra, ensure_ascii=False),
             data.get('created_at', ''),
             data.get('updated_at', ''),
             data.get('updated_by', '')),
        )
        return uid

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return all users as ``{username: {uid, role, groups: […], …}}``."""
        conn = self._conn()
        users: dict = {}
        uid_to_name: dict = {}

        for row in conn.execute(
            'SELECT username, uid, password_hash, role, display_name, email,'
            ' lang, dark_mode, enabled, auth_source, extra,'
            ' created_at, updated_at, updated_by FROM users'
        ).fetchall():
            (username, uid, pw_hash, role, display_name, email,
             lang, dark_mode, enabled, auth_source, extra_raw,
             created_at, updated_at, updated_by) = row
            try:
                extra = json.loads(extra_raw) if extra_raw else {}
            except (ValueError, TypeError):
                extra = {}
            user = {
                'uid':           uid,
                'password_hash': pw_hash,
                'role':          role,
                'display_name':  display_name,
                'email':         email,
                'lang':          lang,
                'dark_mode':     None if dark_mode is None else bool(dark_mode),
                'enabled':       bool(enabled),
                'auth_source':   auth_source,
                'created_at':    created_at or '',
                'updated_at':    updated_at or '',
                'updated_by':    updated_by or '',
                'groups':        [],
            }
            user.update(extra)
            users[username] = user
            uid_to_name[uid] = username

        # Populate groups from the relationship table
        for user_uid, group_uid in conn.execute(
            'SELECT user_uid, group_uid FROM users_groups ORDER BY user_uid, group_uid'
        ).fetchall():
            name = uid_to_name.get(user_uid)
            if name and name in users:
                users[name]['groups'].append(group_uid)

        return users

    def count(self) -> int:
        """Return the number of stored users."""
        row = self._conn().execute('SELECT COUNT(*) FROM users').fetchone()
        return row[0] if row else 0

    def count_groups(self) -> int:
        """Return the total number of user-group memberships."""
        row = self._conn().execute('SELECT COUNT(*) FROM users_groups').fetchone()
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, users: dict) -> bool:
        """Replace all users and their group memberships atomically."""
        try:
            conn = self._conn()
            conn.execute('DELETE FROM users_groups')
            conn.execute('DELETE FROM users')
            for username, data in users.items():
                uid = self._insert_user_row(conn, username, data)
                for grp_uid in data.get('groups', []):
                    if grp_uid:
                        conn.execute(
                            'INSERT INTO users_groups(user_uid, group_uid) VALUES(?,?)',
                            (uid, str(grp_uid)),
                        )
            conn.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def upsert(self, username: str, data: dict) -> bool:
        """Insert or replace a single user and their group memberships."""
        try:
            conn = self._conn()
            uid = self._insert_user_row(conn, username, data, replace=True)
            conn.execute('DELETE FROM users_groups WHERE user_uid = ?', (uid,))
            for grp_uid in data.get('groups', []):
                if grp_uid:
                    conn.execute(
                        'INSERT INTO users_groups(user_uid, group_uid) VALUES(?,?)',
                        (uid, str(grp_uid)),
                    )
            conn.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, username: str) -> bool:
        """Delete a user and their group memberships."""
        try:
            conn = self._conn()
            row = conn.execute('SELECT uid FROM users WHERE username = ?', (username,)).fetchone()
            if not row:
                return False
            uid = row[0]
            conn.execute('DELETE FROM users_groups WHERE user_uid = ?', (uid,))
            conn.execute('DELETE FROM users WHERE username = ?', (username,))
            conn.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
