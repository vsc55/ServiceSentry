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
from lib.db.schema import Column, Index, TableSpec

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


class RolesStore:
    """Relational store for custom roles + built-in overrides (backend-agnostic)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        db = self._db
        db.reconcile_table(_SCHEMA)
        # Backfill empty audit columns for existing rows.
        import time as _t  # noqa: PLC0415
        _now = _t.strftime('%Y-%m-%dT%H:%M:%SZ', _t.gmtime())
        db.execute(
            f"UPDATE {_T} SET created_at=?, updated_at=?, updated_by=? WHERE created_at=''",
            (_now, _now, 'system'),
        )
        db.commit()

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

    def count(self) -> int:
        """Return the number of rows in the roles table."""
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, roles: dict) -> bool:
        """Replace all role rows atomically.

        *roles* is ``{uid: {uid, name, description, permissions, enabled,
        created_at, updated_at, updated_by}}``.  Includes built-in override
        rows (UID as key, name/description only — permissions not stored).
        """
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T}')
                for uid, d in roles.items():
                    self._db.execute(
                        f'INSERT INTO {_T}(uid, name, description, permissions, enabled,'
                        ' created_at, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?)',
                        (uid, d.get('name', uid),
                         d.get('description', ''),
                         json.dumps(d.get('permissions', []), ensure_ascii=False),
                         1 if d.get('enabled', True) else 0,
                         d.get('created_at', ''),
                         d.get('updated_at', ''),
                         d.get('updated_by', '')),
                    )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_role(self, uid: str) -> bool:
        """Delete a role row by UID.  Returns True if found."""
        try:
            with self._db.transaction():
                deleted = self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
            return deleted > 0
        except Exception:  # pylint: disable=broad-except
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""
