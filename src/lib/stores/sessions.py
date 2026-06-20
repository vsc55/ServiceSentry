#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for WebAdmin sessions.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL supported through the same interface).

The relationship to the owning user is stored as ``user_uid`` (the user's
stable UID), not by username, so renames never break the association.

The session's own public identifier is ``uid`` (a short hex id, safe to
expose); the secret ``token`` is the primary key and is never sent to clients.

Schema::

    sessions(uid, token PK, user_uid, created, last_seen, ip, user_agent)
"""

from __future__ import annotations

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='sessions',
    columns=(
        Column('uid',        'TEXT', nullable=False, default="''"),
        Column('token',      'TEXT', primary_key=True),
        Column('user_uid',   'TEXT', nullable=False, default="''"),
        Column('created',    'TEXT', nullable=False, default="''"),
        Column('last_seen',  'TEXT', nullable=False, default="''"),
        Column('ip',         'TEXT', nullable=False, default="''"),
        Column('user_agent', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_sessions_user_uid', ('user_uid',)),),
    renames={'sid': 'uid'},  # legacy column rename, data preserved
)

_T = _SCHEMA.name  # table name — single source of truth


class SessionsStore:
    """Relational store for WebAdmin sessions (backend-agnostic)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return all sessions as ``{token: {uid, user_uid, …}}``."""
        rows = self._db.fetchall(
            'SELECT token, uid, user_uid, created, last_seen, ip, user_agent '
            f'FROM {_T}'
        )
        return {
            r[0]: {
                'uid':        r[1],
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
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, sessions: dict) -> bool:
        """Replace all sessions atomically."""
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T}')
                for token, s in sessions.items():
                    self._db.execute(
                        f'INSERT INTO {_T}'
                        '(token, uid, user_uid, created, last_seen, ip, user_agent)'
                        ' VALUES(?,?,?,?,?,?,?)',
                        (token,
                         s.get('uid', ''),        s.get('user_uid', ''),
                         s.get('created', ''),    s.get('last_seen', ''),
                         s.get('ip', ''),         s.get('user_agent', '')),
                    )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def upsert(self, token: str, session: dict) -> bool:
        """Insert or replace a single session row (portable delete-then-insert)."""
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE token = ?', (token,))
                self._db.execute(
                    f'INSERT INTO {_T}'
                    '(token, uid, user_uid, created, last_seen, ip, user_agent)'
                    ' VALUES(?,?,?,?,?,?,?)',
                    (token,
                     session.get('uid', ''),        session.get('user_uid', ''),
                     session.get('created', ''),    session.get('last_seen', ''),
                     session.get('ip', ''),         session.get('user_agent', '')),
                )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, token: str) -> bool:
        """Delete a single session by token.  Returns True if found."""
        try:
            with self._db.transaction():
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE token = ?', (token,))
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_by_user_uid(self, user_uid: str) -> int:
        """Delete all sessions for a given user UID.  Returns count deleted."""
        try:
            with self._db.transaction():
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE user_uid = ?', (user_uid,))
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""
