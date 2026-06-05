#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for WebAdmin user accounts.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default, but
PostgreSQL/MySQL are supported through the same interface), so this store
never talks to a specific database driver directly.

The user→group membership lives in a dedicated ``users_groups`` table keyed
by the user's stable UID and the group's stable UID, so renaming either side
never breaks the relationship.

Core fields have dedicated columns; variable/optional fields (LDAP/OIDC sync
data, lockout counters, …) go into a JSON ``extra`` column.

Schema::

    users(uid UNIQUE, username PK, password_hash, role, display_name,
          email, lang, dark_mode, enabled, auth_source, extra,
          created_at, updated_at, updated_by)
    users_groups(user_uid, group_uid, PRIMARY KEY(user_uid, group_uid))
"""

from __future__ import annotations

import json

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

# Fields stored as individual columns; everything else goes into ``extra``.
_CORE = frozenset({
    'uid', 'password_hash', 'role', 'display_name', 'email',
    'lang', 'dark_mode', 'enabled', 'auth_source',
    'created_at', 'updated_at', 'updated_by',
    # 'groups' is intentionally excluded — stored in users_groups table
})

_USERS_SCHEMA = TableSpec(
    name='users',
    columns=(
        Column('uid',           'TEXT', nullable=False, default="''", unique=True),
        Column('username',      'TEXT', primary_key=True),
        Column('password_hash', 'TEXT', nullable=False, default="''"),
        Column('role',          'TEXT', nullable=False, default="''"),
        Column('display_name',  'TEXT', nullable=False, default="''"),
        Column('email',         'TEXT', nullable=False, default="''"),
        Column('lang',          'TEXT', nullable=False, default="''"),
        Column('dark_mode',     'INTEGER'),
        Column('enabled',       'INTEGER', nullable=False, default='1'),
        Column('auth_source',   'TEXT', nullable=False, default="'local'"),
        Column('extra',         'TEXT', nullable=False, default="'{}'"),
        Column('created_at',    'TEXT', nullable=False, default="''"),
        Column('updated_at',    'TEXT', nullable=False, default="''"),
        Column('updated_by',    'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_users_role', ('role',)),),
)

_USERS_GROUPS_SCHEMA = TableSpec(
    name='users_groups',
    columns=(
        Column('user_uid',  'TEXT', nullable=False),
        Column('group_uid', 'TEXT', nullable=False),
    ),
    composite_pk=('user_uid', 'group_uid'),
    indexes=(
        Index('idx_users_groups_user',  ('user_uid',)),
        Index('idx_users_groups_group', ('group_uid',)),
    ),
)


class UsersStore:
    """Relational store for WebAdmin user accounts (backend-agnostic)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        """Reconcile tables to the declarative schema; backfill audit columns."""
        db = self._db
        db.reconcile_table(_USERS_SCHEMA)
        db.reconcile_table(_USERS_GROUPS_SCHEMA)
        # Backfill empty audit columns for existing rows.
        import time as _t  # noqa: PLC0415
        _now = _t.strftime('%Y-%m-%dT%H:%M:%SZ', _t.gmtime())
        db.execute(
            "UPDATE users SET created_at=?, updated_at=?, updated_by=? WHERE created_at=''",
            (_now, _now, 'system'),
        )
        db.commit()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _insert_user_row(self, username: str, data: dict) -> str:
        """Insert the user row (callers DELETE first to avoid conflicts).

        Returns the uid used.
        """
        uid   = data.get('uid') or username
        dm    = data.get('dark_mode')
        extra = {k: v for k, v in data.items() if k not in _CORE and k != 'groups'}
        self._db.execute(
            'INSERT INTO users'
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
        users: dict = {}
        uid_to_name: dict = {}

        for row in self._db.fetchall(
            'SELECT username, uid, password_hash, role, display_name, email,'
            ' lang, dark_mode, enabled, auth_source, extra,'
            ' created_at, updated_at, updated_by FROM users'
        ):
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
        for user_uid, group_uid in self._db.fetchall(
            'SELECT user_uid, group_uid FROM users_groups ORDER BY user_uid, group_uid'
        ):
            name = uid_to_name.get(user_uid)
            if name and name in users:
                users[name]['groups'].append(group_uid)

        return users

    def count(self) -> int:
        """Return the number of stored users."""
        row = self._db.fetchone('SELECT COUNT(*) FROM users')
        return row[0] if row else 0

    def count_groups(self) -> int:
        """Return the total number of user-group memberships."""
        row = self._db.fetchone('SELECT COUNT(*) FROM users_groups')
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, users: dict) -> bool:
        """Replace all users and their group memberships atomically."""
        try:
            with self._db.transaction():
                self._db.execute('DELETE FROM users_groups')
                self._db.execute('DELETE FROM users')
                for username, data in users.items():
                    uid = self._insert_user_row(username, data)
                    for grp_uid in dict.fromkeys(data.get('groups', [])):  # dedupe, keep order
                        if grp_uid:
                            self._db.execute(
                                'INSERT INTO users_groups(user_uid, group_uid) VALUES(?,?)',
                                (uid, str(grp_uid)),
                            )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def upsert(self, username: str, data: dict) -> bool:
        """Insert or replace a single user and their group memberships."""
        try:
            with self._db.transaction():
                uid = data.get('uid') or username
                self._db.execute('DELETE FROM users WHERE username = ?', (username,))
                self._db.execute('DELETE FROM users_groups WHERE user_uid = ?', (uid,))
                uid = self._insert_user_row(username, data)
                for grp_uid in dict.fromkeys(data.get('groups', [])):
                    if grp_uid:
                        self._db.execute(
                            'INSERT INTO users_groups(user_uid, group_uid) VALUES(?,?)',
                            (uid, str(grp_uid)),
                        )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, username: str) -> bool:
        """Delete a user and their group memberships."""
        try:
            row = self._db.fetchone('SELECT uid FROM users WHERE username = ?', (username,))
            if not row:
                return False
            uid = row[0]
            with self._db.transaction():
                self._db.execute('DELETE FROM users_groups WHERE user_uid = ?', (uid,))
                self._db.execute('DELETE FROM users WHERE username = ?', (username,))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""
