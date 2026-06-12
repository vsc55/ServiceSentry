#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for monitored hosts (servers).

A *host* is a target you monitor (by address) together with its per-protocol
connection profiles — SSH, SNMP, database, HTTP… — so the same server's
connection details are defined **once** and reused by every watchful module's
checks instead of being re-entered per module.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL through the same interface), like the other entity stores.

Secret values inside the per-protocol ``profiles`` (ssh/db passwords, SNMPv3
keys, tokens…) are encrypted at rest with :mod:`lib.secret_manager` using the
same value-level Fernet scheme as ``modules.json`` / ``config.json``.  ``get``
and ``list`` return decrypted profiles (so the monitor can connect); the API
route is responsible for masking secrets before sending them to the client.

Schema::

    hosts(uid PK, name UNIQUE, address, tags(json list), description,
          profiles(json {protocol: {field: value}}),
          created_at, updated_at, updated_by)
"""

from __future__ import annotations

import json
import time
import uuid

from lib import secret_manager
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_HOSTS_SCHEMA = TableSpec(
    name='hosts',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        Column('address',     'TEXT', nullable=False, default="''"),
        Column('tags',        'TEXT', nullable=False, default="'[]'"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('profiles',    'TEXT', nullable=False, default="'{}'"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_hosts_name', ('name',)),),
)

_COLS = ('uid', 'name', 'address', 'tags', 'description', 'profiles',
         'created_at', 'updated_at', 'updated_by')
_SELECT = ', '.join(_COLS)


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class HostsStore:
    """Relational store for monitored hosts (backend-agnostic)."""

    def __init__(self, db: BaseConnector, *, fernet=None, secret_keys=None) -> None:
        self._db = db
        self._fernet = fernet
        self._secret_keys = secret_keys or secret_manager.ENCRYPT_KEYS
        self._bootstrap()

    # ── Schema ──────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_HOSTS_SCHEMA)

    # ── Secret encryption (value-level, inside profiles) ──────────────────────
    def _encrypt(self, profiles):
        if self._fernet and isinstance(profiles, dict):
            return secret_manager.encrypt_sensitive(profiles, self._fernet, keys=self._secret_keys)
        return profiles

    def _decrypt(self, profiles):
        if self._fernet:
            return secret_manager.decrypt_all(profiles, self._fernet)
        return profiles

    # ── Row mapping ───────────────────────────────────────────────────────────
    def _row_to_host(self, row, decrypt: bool) -> dict:
        uid, name, address, tags, desc, profiles, c_at, u_at, u_by = row
        try:
            tags_l = json.loads(tags) if tags else []
        except (ValueError, TypeError):
            tags_l = []
        try:
            prof = json.loads(profiles) if profiles else {}
        except (ValueError, TypeError):
            prof = {}
        if decrypt:
            prof = self._decrypt(prof)
        return {
            'uid':         uid,
            'name':        name,
            'address':     address,
            'tags':        tags_l if isinstance(tags_l, list) else [],
            'description': desc or '',
            'profiles':    prof if isinstance(prof, dict) else {},
            'created_at':  c_at or '',
            'updated_at':  u_at or '',
            'updated_by':  u_by or '',
        }

    # ── Read ──────────────────────────────────────────────────────────────────
    def list(self, *, decrypt: bool = True) -> list[dict]:
        """Return all hosts ordered by name."""
        return [self._row_to_host(r, decrypt)
                for r in self._db.fetchall(f'SELECT {_SELECT} FROM hosts ORDER BY name')]

    def get(self, uid: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {_SELECT} FROM hosts WHERE uid = ?', (uid,))
        return self._row_to_host(row, decrypt) if row else None

    def get_by_name(self, name: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {_SELECT} FROM hosts WHERE name = ?', (name,))
        return self._row_to_host(row, decrypt) if row else None

    def count(self) -> int:
        row = self._db.fetchone('SELECT COUNT(*) FROM hosts')
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────
    def create(self, data: dict, *, actor: str = '') -> str | None:
        """Insert a new host.  Returns its uid, or None on invalid/duplicate name."""
        name = str(data.get('name') or '').strip()
        if not name:
            return None
        if self._db.fetchone('SELECT 1 FROM hosts WHERE name = ?', (name,)):
            return None  # duplicate name
        uid = str(data.get('uid') or uuid.uuid4())
        now = _now()
        try:
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO hosts ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?)',
                    (uid, name, str(data.get('address') or ''),
                     json.dumps(data.get('tags') or [], ensure_ascii=False),
                     str(data.get('description') or ''),
                     json.dumps(self._encrypt(data.get('profiles') or {}), ensure_ascii=False),
                     now, now, actor or ''),
                )
            return uid
        except Exception:  # pylint: disable=broad-except
            return None

    def update(self, uid: str, data: dict, *, actor: str = '') -> bool:
        """Update an existing host.  ``profiles`` is replaced wholesale (the
        caller should have restored any masked secrets first)."""
        if not self._db.fetchone('SELECT 1 FROM hosts WHERE uid = ?', (uid,)):
            return False
        name = str(data.get('name') or '').strip()
        if not name:
            return False
        # Reject a rename that collides with another host's name.
        clash = self._db.fetchone('SELECT uid FROM hosts WHERE name = ? AND uid <> ?', (name, uid))
        if clash:
            return False
        try:
            with self._db.transaction():
                self._db.execute(
                    'UPDATE hosts SET name=?, address=?, tags=?, description=?, '
                    'profiles=?, updated_at=?, updated_by=? WHERE uid=?',
                    (name, str(data.get('address') or ''),
                     json.dumps(data.get('tags') or [], ensure_ascii=False),
                     str(data.get('description') or ''),
                     json.dumps(self._encrypt(data.get('profiles') or {}), ensure_ascii=False),
                     _now(), actor or '', uid),
                )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, uid: str) -> bool:
        try:
            row = self._db.fetchone('SELECT 1 FROM hosts WHERE uid = ?', (uid,))
            if not row:
                return False
            with self._db.transaction():
                self._db.execute('DELETE FROM hosts WHERE uid = ?', (uid,))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""
