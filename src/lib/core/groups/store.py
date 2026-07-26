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

import uuid as _uuid_mod

from lib.db import BaseConnector
from lib.db.freshness import bump_version
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

_GROUPS_SCHEMA = TableSpec(
    name='groups',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('enabled',     'INTEGER', nullable=False, default='1'),
        Column('landing_page', 'TEXT', nullable=False, default="''"),
        Column('source',      'TEXT', nullable=False, default="'local'"),
        Column('external_id', 'TEXT', nullable=False, default="''"),
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

# Table names — single source of truth.
_T_GROUPS = _GROUPS_SCHEMA.name
_T_GROUPS_ROLES = _GROUPS_ROLES_SCHEMA.name


from lib.util.entity_audit import utc_now_iso as _now   # one timestamp format


class GroupsStore(BaseStore):
    """Relational store for WebAdmin user groups (backend-agnostic)."""

    _TABLE = _T_GROUPS

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        # ``groups`` is a reserved word in MySQL 8 — quote the table name (dialect-aware) in
        # every raw query (the ``groups_roles`` / ``users_groups`` compound names are fine).
        self._qtg = db.quote_ident(_T_GROUPS)
        self._bootstrap()

    @property
    def _sql_table(self) -> str:
        """``groups`` is a reserved word on MySQL 8 — every raw query uses the quoted
        form, and so must the freshness probe: unquoted it does not raise, it just makes
        the probe answer "no idea", and a probe that cannot answer never reloads."""
        return self._qtg

    # ── Schema ────────────────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        db = self._db
        db.reconcile_table(_GROUPS_SCHEMA)
        db.reconcile_table(_GROUPS_ROLES_SCHEMA)
        self._backfill_audit_columns()
        db.commit()
        self._ensure_version_row()

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> dict:
        """Return {uid: {uid, name, description, roles, enabled,
                         created_at, updated_at, updated_by}}."""
        groups: dict = {}
        for row in self._db.fetchall(
            'SELECT uid, name, description, enabled, landing_page, source, external_id, '
            'created_at, updated_at, updated_by '
            f'FROM {self._qtg}'
        ):
            (uid, name, desc, enabled, landing_page, source, external_id,
             created_at, updated_at, updated_by) = row
            groups[uid] = {
                'uid':          uid,
                'name':         name,
                'description':  desc,
                'enabled':      bool(enabled),
                'landing_page': landing_page or '',
                'source':       source or 'local',
                'external_id':  external_id or '',
                'roles':        [],
                'created_at':   created_at or '',
                'updated_at':   updated_at or '',
                'updated_by':   updated_by or '',
            }
        for row in self._db.fetchall(
            'SELECT uid, group_uid, role_uid, created_at, created_by '
            f'FROM {_T_GROUPS_ROLES} ORDER BY group_uid, role_uid'
        ):
            _, grp_uid, role_uid, r_created_at, r_created_by = row
            if grp_uid in groups:
                groups[grp_uid]['roles'].append(role_uid)
                groups[grp_uid].setdefault('roles_audit', {})[role_uid] = {
                    'created_at': r_created_at or '',
                    'created_by': r_created_by or '',
                }
        return groups

    # ── Write ─────────────────────────────────────────────────────────────────

    def _write_row(self, uid: str, data: dict) -> None:
        now = _now()
        row = self._db.fetchone(
            f'SELECT created_at, source, external_id, landing_page FROM {self._qtg} WHERE uid = ?',
            (uid,))
        created_at = (row[0] if row else None) or data.get('created_at') or now
        # Keep the origin (local/scim) stable across edits unless explicitly given.
        source = data.get('source') or (row[1] if row else None) or 'local'
        # Keep the SCIM externalId stable unless explicitly provided.
        external_id = data.get('external_id')
        if external_id is None:
            external_id = (row[2] if row else None) or ''
        updated_at = data.get('updated_at') or now
        updated_by = data.get('updated_by') if data.get('updated_by') is not None else ''
        # Keep the landing page stable across edits unless explicitly provided.
        landing_page = data.get('landing_page')
        if landing_page is None:
            landing_page = (row[3] if row and len(row) > 3 else None) or ''
        # Portable upsert: delete-then-insert the group row.
        self._db.execute(f'DELETE FROM {self._qtg} WHERE uid = ?', (uid,))
        self._db.execute(
            f'INSERT INTO {self._qtg}(uid,name,description,enabled,landing_page,source,'
            'external_id,created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (uid, data.get('name', uid), data.get('description', ''),
             1 if data.get('enabled', True) else 0, landing_page, source, external_id,
             created_at, updated_at, updated_by),
        )
        # The role links are diffed rather than replaced, so an assignment keeps the
        # timestamp of when it was actually made.
        existing_roles = {
            r[0] for r in self._db.fetchall(
                f'SELECT role_uid FROM {_T_GROUPS_ROLES} WHERE group_uid=?', (uid,))
        }
        new_roles = {str(r) for r in data.get('roles', []) if r}
        for role_uid in existing_roles - new_roles:
            self._db.execute(
                f'DELETE FROM {_T_GROUPS_ROLES} WHERE group_uid=? AND role_uid=?',
                (uid, role_uid))
        for role_uid in new_roles - existing_roles:
            self._db.execute(
                f'INSERT INTO {_T_GROUPS_ROLES}(uid,group_uid,role_uid,created_at,created_by)'
                ' VALUES(?,?,?,?,?)',
                (str(_uuid_mod.uuid4()), uid, role_uid, now, updated_by),
            )

    def _delete_row(self, uid: str) -> bool:
        self._db.execute(f'DELETE FROM {_T_GROUPS_ROLES} WHERE group_uid = ?', (uid,))
        return self._db.execute(f'DELETE FROM {self._qtg} WHERE uid = ?', (uid,)) > 0

    def upsert(self, uid: str, data: dict) -> bool:
        """Insert or replace a single group, preserving created_at and doing smart role diff."""
        try:
            with self._db.transaction():
                self._write_row(uid, data)
                bump_version(self._db, _T_GROUPS)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, uid: str) -> bool:
        """Delete a group and its role assignments."""
        try:
            with self._db.transaction():
                deleted = self._delete_row(uid)
                bump_version(self._db, _T_GROUPS)
                return deleted
        except Exception:  # pylint: disable=broad-except
            return False

    def apply(self, writes: dict, deletes=()) -> bool:
        """Write only what changed — see :mod:`lib.core.entity_sync`.

        Groups this caller never knew about are left alone: a group the CLI created while
        the web admin held an older copy no longer vanishes when that copy is saved.
        """
        try:
            with self._db.transaction():
                for uid in deletes:
                    self._delete_row(uid)
                for uid, data in writes.items():
                    self._write_row(uid, data)
                bump_version(self._db, _T_GROUPS)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

