#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backed store for the editable application configuration.

One row per config field, keyed by its ``section|field`` path (e.g.
``modules|threads``, ``web_admin|lang``).  This is the **editable** layer: a
field present in ``config.json`` (or an env var) overrides it and is shown
read-only in the UI — the resolution/precedence (env > config.json > DB >
default) lives one layer up.  The store itself is value-agnostic: it stores and
returns exactly what it is given (secrets stay ciphertext).
"""

from __future__ import annotations

import json
import time
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec


def _now() -> str:
    """ISO-8601 UTC timestamp (same format the other stores use)."""
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _loads(text):
    """Parse a stored JSON value back to its Python type (None on error)."""
    try:
        return json.loads(text) if text not in (None, '') else None
    except (ValueError, TypeError):
        return None


_CONFIG_SCHEMA = TableSpec(
    name='config',
    columns=(
        Column('uid',        'TEXT', primary_key=True),                          # row identity (convention)
        Column('path',       'TEXT', nullable=False, default="''", unique=True),  # 'section|field'
        Column('value',      'TEXT', nullable=False, default="''"),               # JSON-encoded value
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_config_path', ('path',)),),
)

_T = _CONFIG_SCHEMA.name  # table name — single source of truth


class ConfigStore:
    """Backend-agnostic store for the editable configuration (one row per path)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._version = 0
        self._bootstrap()

    # ── Schema ────────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_CONFIG_SCHEMA)

    # ── Meta ──────────────────────────────────────────────────────────────────
    def version(self) -> int:
        """Monotonic counter bumped on every write (cheap cache invalidation)."""
        return self._version

    def is_empty(self) -> bool:
        """True when no config field has been stored yet."""
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return not (row and row[0])

    # ── Read ──────────────────────────────────────────────────────────────────
    def load_all(self) -> dict:
        """Return ``{path: value}`` for every stored field (value-agnostic)."""
        return {path: _loads(value)
                for path, value in self._db.fetchall(f'SELECT path, value FROM {_T}')}

    def get(self, path: str):
        """Return the stored value for *path*, or None when absent."""
        row = self._db.fetchone(f'SELECT value FROM {_T} WHERE path = ?', (path,))
        return _loads(row[0]) if row else None

    def has(self, path: str) -> bool:
        """True when *path* has a row (distinguishes a stored ``null`` from absent)."""
        return self._db.fetchone(f'SELECT 1 FROM {_T} WHERE path = ?', (path,)) is not None

    # ── Write ─────────────────────────────────────────────────────────────────
    def set_many(self, values: dict, *, actor: str = '') -> None:
        """Upsert ``{path: value}`` in one transaction.  UID is stable per path
        (reused when the row exists, generated for new paths)."""
        if not isinstance(values, dict) or not values:
            return
        now = _now()
        wrote = False
        with self._db.transaction():
            existing = {p: (u, v) for (u, p, v) in
                        self._db.fetchall(f'SELECT uid, path, value FROM {_T}')}
            for path, value in values.items():
                vj = json.dumps(value, ensure_ascii=False)
                row = existing.get(path)
                if row is not None:
                    uid, cur = row
                    if cur == vj:
                        continue                          # unchanged → don't touch the row
                    self._db.execute(
                        f'UPDATE {_T} SET value=?, updated_at=?, updated_by=? WHERE uid=?',
                        (vj, now, actor, uid))
                    wrote = True
                else:
                    self._db.execute(
                        f'INSERT INTO {_T} (uid, path, value, created_at, updated_at, updated_by) '
                        'VALUES (?,?,?,?,?,?)', (str(uuid.uuid4()), path, vj, now, now, actor))
                    wrote = True
        if wrote:
            self._version += 1

    def set(self, path: str, value, *, actor: str = '') -> None:
        """Upsert a single field."""
        self.set_many({path: value}, actor=actor)

    def delete_many(self, paths) -> None:
        """Delete the given paths (no-op for absent ones)."""
        paths = [p for p in (paths or [])]
        if not paths:
            return
        with self._db.transaction():
            for path in paths:
                self._db.execute(f'DELETE FROM {_T} WHERE path = ?', (path,))
        self._version += 1

    def delete(self, path: str) -> None:
        """Delete a single field."""
        self.delete_many([path])


def create(db: BaseConnector) -> ConfigStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return ConfigStore(db)
