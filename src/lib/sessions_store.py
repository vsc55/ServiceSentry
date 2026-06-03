#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Columnar SQLite store for WebAdmin sessions.

The relationship to the owning user is stored as ``user_uid`` (the user's
stable UID), not by username, so renames never break the association.

Schema::

    sessions(token PK, sid, user_uid, created, last_seen, ip, user_agent)

Thread-safe: per-thread connections via ``threading.local``.
"""

from __future__ import annotations

import os
import sqlite3
import threading


class SessionsStore:
    """Columnar SQLite store for WebAdmin sessions."""

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
        """Create the sessions table if it doesn't exist yet."""
        conn = self._conn()
        cols = {r[1] for r in conn.execute('PRAGMA table_info(sessions)').fetchall()}

        if not cols:
            conn.execute('''
                CREATE TABLE sessions (
                    token      TEXT PRIMARY KEY,
                    sid        TEXT NOT NULL DEFAULT '',
                    user_uid   TEXT NOT NULL DEFAULT '',
                    created    TEXT NOT NULL DEFAULT '',
                    last_seen  TEXT NOT NULL DEFAULT '',
                    ip         TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT ''
                )
            ''')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_sessions_user_uid '
                'ON sessions(user_uid)'
            )

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return all sessions as ``{token: {sid, user_uid, …}}``."""
        rows = self._conn().execute(
            'SELECT token, sid, user_uid, created, last_seen, ip, user_agent '
            'FROM sessions'
        ).fetchall()
        return {
            r[0]: {
                'sid':        r[1],
                'user_uid':   r[2],
                'created':    r[3],
                'last_seen':  r[4],
                'ip':         r[5],
                'user_agent': r[6],
            }
            for r in rows
        }

    def count(self) -> int:
        """Return the number of stored sessions."""
        row = self._conn().execute('SELECT COUNT(*) FROM sessions').fetchone()
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, sessions: dict) -> bool:
        """Replace all sessions atomically."""
        try:
            conn = self._conn()
            conn.execute('DELETE FROM sessions')
            for token, s in sessions.items():
                conn.execute(
                    'INSERT INTO sessions'
                    '(token, sid, user_uid, created, last_seen, ip, user_agent)'
                    ' VALUES(?,?,?,?,?,?,?)',
                    (token,
                     s.get('sid', ''),        s.get('user_uid', ''),
                     s.get('created', ''),    s.get('last_seen', ''),
                     s.get('ip', ''),         s.get('user_agent', '')),
                )
            conn.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def upsert(self, token: str, session: dict) -> bool:
        """Insert or replace a single session row."""
        try:
            self._conn().execute(
                'INSERT OR REPLACE INTO sessions'
                '(token, sid, user_uid, created, last_seen, ip, user_agent)'
                ' VALUES(?,?,?,?,?,?,?)',
                (token,
                 session.get('sid', ''),        session.get('user_uid', ''),
                 session.get('created', ''),    session.get('last_seen', ''),
                 session.get('ip', ''),         session.get('user_agent', '')),
            )
            self._conn().commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, token: str) -> bool:
        """Delete a single session by token.  Returns True if found."""
        try:
            conn = self._conn()
            conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
            deleted = conn.execute('SELECT changes()').fetchone()[0]
            conn.commit()
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_by_user_uid(self, user_uid: str) -> int:
        """Delete all sessions for a given user UID.  Returns count deleted."""
        try:
            conn = self._conn()
            conn.execute('DELETE FROM sessions WHERE user_uid = ?', (user_uid,))
            deleted = conn.execute('SELECT changes()').fetchone()[0]
            conn.commit()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None
