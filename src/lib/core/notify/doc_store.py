#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One row per record: ``uid`` primary key + a JSON ``data`` blob + audit columns.

Several notification destinations share exactly this shape — an independent record with
a name, an enabled flag and some endpoint fields, living in its **own** table rather than
in ``config.json`` (like hosts, credentials and modules).  Webhooks and Microsoft Teams
channels were two 135-line stores whose logic was identical: the differences were the
table name, the prose, and whether a local was called ``webhook`` or ``channel``.

Subclass, set :attr:`SCHEMA` and :attr:`SECRET_KEYS` if the record holds a secret, and
the CRUD comes with it::

    class WebhooksStore(JsonDocStore):
        SCHEMA = _WEBHOOKS_SCHEMA

What is deliberately NOT here: anything a caller must think about per destination — the
shape of ``data`` (each API route validates its own), and which of its fields are secret
(declared per store).  A base that also decided those would be doing the part that is
genuinely different.
"""

from __future__ import annotations

import json
import time
import uuid

from lib.db import BaseConnector
from lib.db.schema import TableSpec
from lib.security import secret_manager

# Every column this base reads, in order — subclasses must not redeclare it: the SELECT
# and the row unpacking in _row_to_doc are two halves of one statement.
_SELECT = 'uid, data, created_at, updated_at, updated_by'


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class JsonDocStore:
    """Backend-agnostic CRUD over a uid + JSON-data table."""

    #: The table. Subclasses MUST set it.
    SCHEMA: TableSpec = None
    #: Keys inside ``data`` encrypted at rest. Defaults to the shared secret-key set.
    SECRET_KEYS = None

    def __init__(self, db: BaseConnector, *, fernet=None, secret_keys=None) -> None:
        if self.SCHEMA is None:                      # pragma: no cover - programming error
            raise TypeError(f'{type(self).__name__} must set SCHEMA')
        self._db = db
        self._fernet = fernet
        self._secret_keys = secret_keys or self.SECRET_KEYS or secret_manager.ENCRYPT_KEYS
        self._table = self.SCHEMA.name
        self._bootstrap()

    # ── Schema ──────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(self.SCHEMA)

    # ── Secret encryption (value-level, inside data) ─────────────────────────
    def _encrypt(self, data):
        if self._fernet and isinstance(data, dict):
            return secret_manager.encrypt_sensitive(data, self._fernet, keys=self._secret_keys)
        return data

    def _decrypt(self, data):
        if self._fernet:
            return secret_manager.decrypt_all(data, self._fernet)
        return data

    def _row_to_doc(self, row, decrypt: bool) -> dict:
        uid, data, _c, _u, _by = row
        try:
            d = json.loads(data) if data else {}
        except (ValueError, TypeError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        if decrypt:
            d = self._decrypt(d)
        return {'id': uid, **d}

    # ── Read ────────────────────────────────────────────────────────────────
    def list(self, *, decrypt: bool = True) -> list[dict]:
        """Every record (id + fields), ordered by creation time."""
        return [self._row_to_doc(r, decrypt)
                for r in self._db.fetchall(
                    f'SELECT {_SELECT} FROM {self._table} ORDER BY created_at, uid')]

    def get(self, uid: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(
            f'SELECT {_SELECT} FROM {self._table} WHERE uid = ?', (uid,))
        return self._row_to_doc(row, decrypt) if row else None

    def count(self) -> int:
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {self._table}')
        return row[0] if row else 0

    def is_empty(self) -> bool:
        return self.count() == 0

    # ── Write ───────────────────────────────────────────────────────────────
    @staticmethod
    def _split(doc: dict) -> tuple[str, dict]:
        """Split a record into ``(uid, data-without-id)``, minting a uid when absent."""
        d = dict(doc or {})
        uid = str(d.pop('id', None) or uuid.uuid4())
        return uid, d

    def upsert(self, doc: dict, *, actor: str = '') -> str:
        """Insert or replace a record (keyed by its ``id``). Returns the uid."""
        uid, data = self._split(doc)
        now = _now()
        vj = json.dumps(self._encrypt(data), ensure_ascii=False)
        with self._db.transaction():
            if self._db.fetchone(f'SELECT 1 FROM {self._table} WHERE uid = ?', (uid,)):
                self._db.execute(
                    f'UPDATE {self._table} SET data=?, updated_at=?, updated_by=? '
                    'WHERE uid=?', (vj, now, actor or '', uid))
            else:
                self._db.execute(
                    f'INSERT INTO {self._table} '
                    '(uid, data, created_at, updated_at, updated_by) '
                    'VALUES (?,?,?,?,?)', (uid, vj, now, now, actor or ''))
        return uid

    def delete(self, uid: str) -> bool:
        """Delete by uid. ``False`` when there was nothing to delete."""
        if not self._db.fetchone(f'SELECT 1 FROM {self._table} WHERE uid = ?', (uid,)):
            return False
        with self._db.transaction():
            self._db.execute(f'DELETE FROM {self._table} WHERE uid = ?', (uid,))
        return True
