#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for WebAdmin user groups.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL supported through the same interface).

``uid`` is the primary key for groups; the ``name`` column is UNIQUE.
The group-role relationship lives in ``groups_roles``, keyed by UID on both
sides, with each assignment row carrying its own stable ``uid`` PK.

Schema::

    groups(uid PK, name UNIQUE, description, enabled,
           created_at, updated_at, updated_by)
    groups_roles(uid PK, group_uid, role_uid, UNIQUE(group_uid, role_uid),
                 created_at, created_by)
"""

from __future__ import annotations

import time as _time
import uuid as _uuid_mod

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_GROUPS_SCHEMA = TableSpec(
    name='groups',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('enabled',     'INTEGER', nullable=False, default='1'),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_groups_name', ('name',), unique=True),),
)

_GROUPS_ROLES_SCHEMA = TableSpec(
    name='groups_roles',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('group_uid',  'TEXT', nullable=False),
        Column('role_uid',   'TEXT', nullable=False),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('created_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(
        Index('idx_gr_group', ('group_uid',)),
        Index('idx_gr_role',  ('role_uid',)),
    ),
    unique_constraints=(('group_uid', 'role_uid'),),
)


def _now() -> str:
    return _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())


class GroupsStore:
    """Relational store for WebAdmin user groups (backend-agnostic)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        db = self._db
        db.reconcile_table(_GROUPS_SCHEMA)
        db.reconcile_table(_GROUPS_ROLES_SCHEMA)
        # Backfill empty audit columns for existing rows.
        db.execute(
            "UPDATE groups SET created_at=?, updated_at=?, updated_by=? WHERE created_at=''",
            (_now(), _now(), 'system'),
        )
        db.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return {uid: {uid, name, description, roles, enabled,
                         created_at, updated_at, updated_by}}."""
        groups: dict = {}
        for row in self._db.fetchall(
            'SELECT uid, name, description, enabled, created_at, updated_at, updated_by '
            'FROM groups'
        ):
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
        for row in self._db.fetchall(
            'SELECT uid, group_uid, role_uid, created_at, created_by '
            'FROM groups_roles ORDER BY group_uid, role_uid'
        ):
            _, grp_uid, role_uid, r_created_at, r_created_by = row
            if grp_uid in groups:
                groups[grp_uid]['roles'].append(role_uid)
                groups[grp_uid].setdefault('roles_audit', {})[role_uid] = {
                    'created_at': r_created_at or '',
                    'created_by': r_created_by or '',
                }
        return groups

    def count(self) -> int:
        row = self._db.fetchone('SELECT COUNT(*) FROM groups')
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, groups: dict) -> bool:
        """Replace all groups atomically, preserving created_at and role timestamps."""
        now = _now()
        try:
            with self._db.transaction():
                existing_created = {
                    r[0]: r[1]
                    for r in self._db.fetchall('SELECT uid, created_at FROM groups')
                }
                existing_role_ts = {
                    (r[0], r[1]): {'uid': r[2], 'created_at': r[3], 'created_by': r[4]}
                    for r in self._db.fetchall(
                        'SELECT group_uid, role_uid, uid, created_at, created_by FROM groups_roles'
                    )
                }
                self._db.execute('DELETE FROM groups_roles')
                self._db.execute('DELETE FROM groups')
                for uid, d in groups.items():
                    created_at = existing_created.get(uid) or d.get('created_at') or now
                    updated_at = d.get('updated_at') or now
                    updated_by = d.get('updated_by') if d.get('updated_by') is not None else ''
                    self._db.execute(
                        'INSERT INTO groups(uid,name,description,enabled,'
                        'created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)',
                        (uid, d.get('name', uid), d.get('description', ''),
                         1 if d.get('enabled', True) else 0,
                         created_at, updated_at, updated_by),
                    )
                    for role_uid in dict.fromkeys(d.get('roles', [])):  # dedupe, keep order
                        if not role_uid:
                            continue
                        existing = existing_role_ts.get((uid, role_uid), {})
                        self._db.execute(
                            'INSERT INTO groups_roles(uid,group_uid,role_uid,created_at,created_by)'
                            ' VALUES(?,?,?,?,?)',
                            (existing.get('uid') or str(_uuid_mod.uuid4()), uid, str(role_uid),
                             existing.get('created_at') or now,
                             existing.get('created_by') or d.get('updated_by') or ''),
                        )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def upsert(self, uid: str, data: dict) -> bool:
        """Insert or replace a single group, preserving created_at and doing smart role diff."""
        now = _now()
        try:
            with self._db.transaction():
                row = self._db.fetchone('SELECT created_at FROM groups WHERE uid = ?', (uid,))
                created_at = (row[0] if row else None) or data.get('created_at') or now
                updated_at = data.get('updated_at') or now
                updated_by = data.get('updated_by') if data.get('updated_by') is not None else ''
                # Portable upsert: delete-then-insert the group row.
                self._db.execute('DELETE FROM groups WHERE uid = ?', (uid,))
                self._db.execute(
                    'INSERT INTO groups(uid,name,description,enabled,'
                    'created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)',
                    (uid, data.get('name', uid), data.get('description', ''),
                     1 if data.get('enabled', True) else 0,
                     created_at, updated_at, updated_by),
                )
                existing_roles = {
                    r[0]: {'row_uid': r[1], 'created_at': r[2], 'created_by': r[3]}
                    for r in self._db.fetchall(
                        'SELECT role_uid, uid, created_at, created_by '
                        'FROM groups_roles WHERE group_uid=?', (uid,)
                    )
                }
                new_roles = {str(r) for r in data.get('roles', []) if r}
                for role_uid in set(existing_roles) - new_roles:
                    self._db.execute(
                        'DELETE FROM groups_roles WHERE group_uid=? AND role_uid=?', (uid, role_uid)
                    )
                for role_uid in new_roles - set(existing_roles):
                    self._db.execute(
                        'INSERT INTO groups_roles(uid,group_uid,role_uid,created_at,created_by)'
                        ' VALUES(?,?,?,?,?)',
                        (str(_uuid_mod.uuid4()), uid, role_uid, now, updated_by),
                    )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, uid: str) -> bool:
        """Delete a group and its role assignments."""
        try:
            with self._db.transaction():
                self._db.execute('DELETE FROM groups_roles WHERE group_uid = ?', (uid,))
                deleted = self._db.execute('DELETE FROM groups WHERE uid = ?', (uid,))
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""
