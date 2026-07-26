#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for custom roles and built-in role name overrides.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL supported through the same interface).

Custom roles are identified by their stable ``uid`` PK; the ``name`` column
is UNIQUE.  Built-in role customisations (name/description overrides) are
stored as rows in the same table using the built-in UID.

Schema::

    roles(uid PK, name UNIQUE, description, permissions TEXT/JSON,
          enabled, created_at, updated_at, updated_by)
"""

from __future__ import annotations

import json

from lib.db import BaseConnector
from lib.db.freshness import bump_version
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

_SCHEMA = TableSpec(
    name='roles',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('permissions', 'TEXT', nullable=False, default="'[]'"),
        Column('enabled',     'INTEGER', nullable=False, default='1'),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_roles_name', ('name',), unique=True),),
)

_T = _SCHEMA.name  # table name — single source of truth


class RolesStore(BaseStore):
    """Relational store for custom roles + built-in overrides (backend-agnostic)."""

    _TABLE = _T

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        db = self._db
        db.reconcile_table(_SCHEMA)
        self._backfill_audit_columns()
        db.commit()
        self._ensure_version_row()

    # ── Read ──────────────────────────────────────────────────────────────────

    def load_roles(self) -> dict:
        """Return all role rows as ``{uid: {uid, name, description, permissions,
        enabled, created_at, updated_at, updated_by}}``."""
        rows = self._db.fetchall(
            'SELECT uid, name, description, permissions, enabled, '
            f'created_at, updated_at, updated_by FROM {_T}'
        )
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

    # ── Write ─────────────────────────────────────────────────────────────────

    def apply(self, writes: dict, deletes=()) -> bool:
        """Write only what changed — see :mod:`lib.core.entity_sync`.

        Rows this caller never knew about are untouched — which is the point: two
        processes editing different roles no longer delete each other's work, as they did
        when a save meant "empty the table and put back what I have".

        An upsert is SELECT-then-UPDATE-or-INSERT rather than a rowcount check: MySQL
        reports 0 rows affected for an UPDATE that sets a row to the values it already
        has, so "0 means it is not there, insert it" would try to insert a duplicate.
        """
        try:
            with self._db.transaction():
                for uid in deletes:
                    self._db.execute(f'DELETE FROM {_T} WHERE uid=?', (uid,))
                for uid, d in writes.items():
                    values = (d.get('name', uid), d.get('description', ''),
                              json.dumps(d.get('permissions', []), ensure_ascii=False),
                              1 if d.get('enabled', True) else 0,
                              d.get('created_at', ''), d.get('updated_at', ''),
                              d.get('updated_by', ''))
                    exists = self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid=?', (uid,))
                    if exists:
                        self._db.execute(
                            f'UPDATE {_T} SET name=?, description=?, permissions=?, enabled=?,'
                            ' created_at=?, updated_at=?, updated_by=? WHERE uid=?',
                            (*values, uid))
                    else:
                        self._db.execute(
                            f'INSERT INTO {_T}(name, description, permissions, enabled,'
                            ' created_at, updated_at, updated_by, uid) VALUES(?,?,?,?,?,?,?,?)',
                            (*values, uid))
                bump_version(self._db, _T)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_role(self, uid: str) -> bool:
        """Delete a role row by UID.  Returns True if found."""
        try:
            with self._db.transaction():
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
                bump_version(self._db, _T)
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False
