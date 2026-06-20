#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for reusable, named connection credentials.

A *credential* is an SSH identity (user + password or private key) defined
**once** and referenced by many hosts and/or inline checks via ``cred_uid``,
so the same secret is not re-entered per host/module.  The target's address,
port and host-key policy stay on the host/check; a credential only carries the
*identity* (who authenticates and how).

Backed by the shared :class:`lib.db.BaseConnector`, like the other stores.  The
secret fields (``ssh_password``/``ssh_key_string``) inside ``data`` are
encrypted at rest with :mod:`lib.secret_manager` (the same value-level Fernet
scheme as the host profiles).  ``get``/``list`` return decrypted data so the
monitor can connect; the API route masks secrets before sending them out.

Schema::

    credentials(uid PK, name UNIQUE, ctype, description,
                data(json {ssh_user, ssh_auth_method, ssh_password,
                           ssh_key, ssh_key_string}),
                created_at, updated_at, updated_by)
"""

from __future__ import annotations

import json
import time
import uuid

from lib import secret_manager
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

# Identity fields a credential owns; overlaid onto a host/check ssh dict when a
# cred_uid is set.  Address/port/verify_host are NOT here — they belong to the
# target, not the identity.
SSH_CRED_FIELDS = ('ssh_user', 'ssh_auth_method', 'ssh_password', 'ssh_key', 'ssh_key_string')

_CREDS_SCHEMA = TableSpec(
    name='credentials',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        # Credential type — only 'ssh' today, but kept explicit for future kinds.
        Column('ctype',       'TEXT', nullable=False, default="'ssh'"),
        # When 0 the credential is inactive: it is ignored at resolution, so a
        # host/check referencing it falls back to its inline SSH fields.
        Column('enabled',     'INTEGER', nullable=False, default="1"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('data',        'TEXT', nullable=False, default="'{}'"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_credentials_name', ('name',)),),
)

_T = _CREDS_SCHEMA.name  # table name — single source of truth

_COLS = ('uid', 'name', 'ctype', 'enabled', 'description', 'data',
         'created_at', 'updated_at', 'updated_by')
_SELECT = ', '.join(_COLS)


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def apply_credential(target: dict, cred: dict | None) -> dict:
    """Overlay a credential's stored fields onto *target* (a check/ssh dict).

    Returns a NEW dict: every non-empty field the credential holds (its type's
    fields — ssh_user/secret for SSH, auth_user/auth_password for a web auth
    type, …) wins, since choosing a credential means "authenticate as this".
    Other keys in *target* (address, port, host-key policy…) are preserved.
    A falsy *cred* returns a copy of *target* unchanged.
    """
    if not isinstance(target, dict):
        target = {}
    # A disabled credential is ignored — the caller keeps its inline fields.
    if not cred or cred.get('enabled') is False:
        return dict(target)
    data = cred.get('data') if isinstance(cred.get('data'), dict) else cred
    out = dict(target)
    for k, v in (data.items() if isinstance(data, dict) else ()):
        if v not in (None, ''):
            out[k] = v
    return out


class CredentialsStore:
    """Relational store for reusable named credentials (backend-agnostic)."""

    def __init__(self, db: BaseConnector, *, fernet=None, secret_keys=None) -> None:
        self._db = db
        self._fernet = fernet
        self._secret_keys = secret_keys or secret_manager.ENCRYPT_KEYS
        self._bootstrap()

    # ── Schema ──────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_CREDS_SCHEMA)

    # ── Secret encryption (value-level, inside data) ──────────────────────────
    def _encrypt(self, data):
        if self._fernet and isinstance(data, dict):
            return secret_manager.encrypt_sensitive(data, self._fernet, keys=self._secret_keys)
        return data

    def _decrypt(self, data):
        if self._fernet:
            return secret_manager.decrypt_all(data, self._fernet)
        return data

    # ── Row mapping ───────────────────────────────────────────────────────────
    def _row_to_cred(self, row, decrypt: bool) -> dict:
        uid, name, ctype, enabled, desc, data, c_at, u_at, u_by = row
        try:
            d = json.loads(data) if data else {}
        except (ValueError, TypeError):
            d = {}
        if decrypt:
            d = self._decrypt(d)
        return {
            'uid':         uid,
            'name':        name,
            'ctype':       ctype or 'ssh',
            'enabled':     bool(enabled),
            'description': desc or '',
            'data':        d if isinstance(d, dict) else {},
            'created_at':  c_at or '',
            'updated_at':  u_at or '',
            'updated_by':  u_by or '',
        }

    # ── Read ──────────────────────────────────────────────────────────────────
    def list(self, *, decrypt: bool = True) -> list[dict]:
        """Return all credentials ordered by name."""
        return [self._row_to_cred(r, decrypt)
                for r in self._db.fetchall(f'SELECT {_SELECT} FROM {_T} ORDER BY name')]

    def get(self, uid: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE uid = ?', (uid,))
        return self._row_to_cred(row, decrypt) if row else None

    def get_by_name(self, name: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE name = ?', (name,))
        return self._row_to_cred(row, decrypt) if row else None

    def count(self) -> int:
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────
    def create(self, data: dict, *, actor: str = '') -> str | None:
        """Insert a new credential.  Returns its uid, or None on invalid/dup name."""
        name = str(data.get('name') or '').strip()
        if not name:
            return None
        if self._db.fetchone(f'SELECT 1 FROM {_T} WHERE name = ?', (name,)):
            return None  # duplicate name
        uid = str(data.get('uid') or uuid.uuid4())
        now = _now()
        try:
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO {_T} ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?)',
                    (uid, name, str(data.get('ctype') or 'ssh'),
                     0 if data.get('enabled') is False else 1,
                     str(data.get('description') or ''),
                     json.dumps(self._encrypt(data.get('data') or {}), ensure_ascii=False),
                     now, now, actor or ''),
                )
            return uid
        except Exception:  # pylint: disable=broad-except
            return None

    def update(self, uid: str, data: dict, *, actor: str = '') -> bool:
        """Update a credential.  ``data`` is replaced wholesale (the caller
        should have restored any masked secrets first)."""
        if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
            return False
        name = str(data.get('name') or '').strip()
        if not name:
            return False
        clash = self._db.fetchone(
            f'SELECT uid FROM {_T} WHERE name = ? AND uid <> ?', (name, uid))
        if clash:
            return False
        try:
            with self._db.transaction():
                self._db.execute(
                    f'UPDATE {_T} SET name=?, ctype=?, enabled=?, description=?, data=?, '
                    'updated_at=?, updated_by=? WHERE uid=?',
                    (name, str(data.get('ctype') or 'ssh'),
                     0 if data.get('enabled') is False else 1,
                     str(data.get('description') or ''),
                     json.dumps(self._encrypt(data.get('data') or {}), ensure_ascii=False),
                     _now(), actor or '', uid),
                )
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete(self, uid: str) -> bool:
        try:
            if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
                return False
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""
