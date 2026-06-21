#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for outgoing notification webhooks.

A *webhook* is one HTTP endpoint ServiceSentry POSTs to on status changes.  Each
is an independent record (url, method, headers, body template, signing secret),
so — like hosts/credentials/modules — they live in their **own** DB table, not in
``config.json``.  The ``secret`` field inside ``data`` is encrypted at rest with
:mod:`lib.secret_manager`; ``list``/``get`` return decrypted data so the
dispatcher can sign requests, and the API route masks it before sending out.

Schema::

    webhooks(uid PK, data(json {name, enabled, url, method, headers,
                                 body_template, timeout, secret, secret_header}),
             created_at, updated_at, updated_by)
"""

from __future__ import annotations

import json
import time
import uuid

from lib import secret_manager
from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_WEBHOOKS_SCHEMA = TableSpec(
    name='webhooks',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
)

_T = _WEBHOOKS_SCHEMA.name  # table name — single source of truth
_SELECT = 'uid, data, created_at, updated_at, updated_by'


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class WebhooksStore:
    """Backend-agnostic store for notification webhooks (one row per webhook)."""

    def __init__(self, db: BaseConnector, *, fernet=None, secret_keys=None) -> None:
        self._db = db
        self._fernet = fernet
        self._secret_keys = secret_keys or secret_manager.ENCRYPT_KEYS
        self._bootstrap()

    # ── Schema ──────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_WEBHOOKS_SCHEMA)

    # ── Secret encryption (value-level, inside data) ──────────────────────────
    def _encrypt(self, data):
        if self._fernet and isinstance(data, dict):
            return secret_manager.encrypt_sensitive(data, self._fernet, keys=self._secret_keys)
        return data

    def _decrypt(self, data):
        if self._fernet:
            return secret_manager.decrypt_all(data, self._fernet)
        return data

    def _row_to_webhook(self, row, decrypt: bool) -> dict:
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

    # ── Read ──────────────────────────────────────────────────────────────────
    def list(self, *, decrypt: bool = True) -> list[dict]:
        """Return all webhooks (id + fields), ordered by creation time."""
        return [self._row_to_webhook(r, decrypt)
                for r in self._db.fetchall(
                    f'SELECT {_SELECT} FROM {_T} ORDER BY created_at, uid')]

    def get(self, uid: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE uid = ?', (uid,))
        return self._row_to_webhook(row, decrypt) if row else None

    def count(self) -> int:
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return row[0] if row else 0

    def is_empty(self) -> bool:
        return self.count() == 0

    # ── Write ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _split(webhook: dict) -> tuple[str, dict]:
        """Split a webhook dict into (uid, data-without-id)."""
        wh = dict(webhook or {})
        uid = str(wh.pop('id', None) or uuid.uuid4())
        return uid, wh

    def upsert(self, webhook: dict, *, actor: str = '') -> str:
        """Insert or replace a webhook (keyed by its ``id``).  Returns the uid."""
        uid, data = self._split(webhook)
        now = _now()
        vj = json.dumps(self._encrypt(data), ensure_ascii=False)
        with self._db.transaction():
            if self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
                self._db.execute(
                    f'UPDATE {_T} SET data=?, updated_at=?, updated_by=? WHERE uid=?',
                    (vj, now, actor or '', uid))
            else:
                self._db.execute(
                    f'INSERT INTO {_T} (uid, data, created_at, updated_at, updated_by) '
                    'VALUES (?,?,?,?,?)', (uid, vj, now, now, actor or ''))
        return uid

    def delete(self, uid: str) -> bool:
        if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
            return False
        with self._db.transaction():
            self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
        return True


def create(db: BaseConnector, **kw) -> WebhooksStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return WebhooksStore(db, **kw)
