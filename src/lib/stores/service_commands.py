#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backed queue of imperative service commands (run-now / reload / clear…).

The *third* concept of the distributed control plane, kept separate from the
desired state (``config``) and the observed state
(:class:`lib.stores.service_instances.ServiceInstancesStore`).  Commands are
one-shot actions — "run a check cycle now", "reload rules" — that don't belong in
declarative config: the web admin enqueues one, and whichever instance hosts that
service (embedded here or in another pod) atomically claims and runs it, then
records the result.

Atomic claim (``UPDATE … WHERE claimed_at IS NULL``) guarantees that with two
replicas of a service only one runs each command.  Backed by the shared system
:class:`lib.db.BaseConnector`, so the producer (web) and the consumer (worker)
use the same rows.
"""

from __future__ import annotations

import json
import time

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='service_commands',
    columns=(
        Column('id',          'AUTOINCREMENT', primary_key=True),
        Column('service_key', 'TEXT', nullable=False, default="''"),
        Column('action',      'TEXT', nullable=False, default="''"),
        Column('args',        'TEXT', nullable=False, default="''"),    # JSON
        Column('created_by',  'TEXT', nullable=False, default="''"),
        Column('created_at',  'REAL'),
        Column('claimed_at',  'REAL'),
        Column('claimed_by',  'TEXT'),                                  # instance_id
        Column('done_at',     'REAL'),
        Column('ok',          'INTEGER'),                              # null until done
        Column('result',      'TEXT'),
    ),
    indexes=(
        Index('idx_svccmd_pending', ('service_key', 'claimed_at')),
        Index('idx_svccmd_created', ('created_at',)),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth

_COLS = ('id', 'service_key', 'action', 'args', 'created_by', 'created_at',
         'claimed_at', 'claimed_by', 'done_at', 'ok', 'result')


def _loads(text):
    try:
        return json.loads(text) if text not in (None, '') else {}
    except (ValueError, TypeError):
        return {}


class ServiceCommandsStore:
    """Backend-agnostic one-shot command queue per service."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema ──────────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    def _row(self, row: tuple) -> dict:
        d = dict(zip(_COLS, row))
        d['args'] = _loads(d.get('args'))
        if d.get('ok') is not None:
            d['ok'] = bool(d['ok'])
        return d

    # ── Producer ────────────────────────────────────────────────────────────────
    def enqueue(self, service_key: str, action: str, *, args: dict | None = None,
                created_by: str = '') -> int:
        """Append a command; returns its id (0 on failure)."""
        try:
            self._db.execute(
                f'INSERT INTO {_T} (service_key, action, args, created_by, created_at) '
                'VALUES (?,?,?,?,?)',
                (service_key, action, json.dumps(args or {}, ensure_ascii=False),
                 created_by, time.time()))
            self._db.commit()
            row = self._db.fetchone(
                f'SELECT MAX(id) FROM {_T} WHERE service_key=? AND action=?',
                (service_key, action))
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Consumer ────────────────────────────────────────────────────────────────
    def claim_next(self, service_key: str, claimer: str) -> dict | None:
        """Atomically claim the oldest unclaimed command for *service_key*.

        Returns the claimed command (or None when the queue is empty).  The
        ``UPDATE … WHERE claimed_at IS NULL`` makes the claim safe against two
        replicas racing for the same row."""
        try:
            with self._db.transaction():
                row = self._db.fetchone(
                    f'SELECT id FROM {_T} WHERE service_key=? AND claimed_at IS NULL '
                    'ORDER BY id ASC', (service_key,))
                if not row:
                    return None
                cmd_id = row[0]
                claimed = self._db.execute(
                    f'UPDATE {_T} SET claimed_at=?, claimed_by=? '
                    'WHERE id=? AND claimed_at IS NULL',
                    (time.time(), claimer, cmd_id))
                if not claimed:
                    return None                       # lost the race to another instance
            full = self._db.fetchone(
                f'SELECT {", ".join(_COLS)} FROM {_T} WHERE id=?', (cmd_id,))
            return self._row(full) if full else None
        except Exception:  # pylint: disable=broad-except
            return None

    def complete(self, cmd_id: int, ok: bool, result: str = '') -> None:
        """Record a claimed command's outcome (the ack)."""
        try:
            self._db.execute(
                f'UPDATE {_T} SET done_at=?, ok=?, result=? WHERE id=?',
                (time.time(), 1 if ok else 0, str(result)[:500], cmd_id))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            pass

    # ── Read / housekeeping ─────────────────────────────────────────────────────
    def list_recent(self, service_key: str | None = None, limit: int = 50) -> list[dict]:
        cols = ', '.join(_COLS)
        if service_key:
            rows = self._db.fetchall(
                f'SELECT {cols} FROM {_T} WHERE service_key=? ORDER BY id DESC LIMIT ?',
                (service_key, int(limit)))
        else:
            rows = self._db.fetchall(
                f'SELECT {cols} FROM {_T} ORDER BY id DESC LIMIT ?', (int(limit),))
        return [self._row(r) for r in rows]

    def prune(self, older_than_secs: float = 86400) -> int:
        """Drop finished commands older than *older_than_secs*."""
        try:
            cutoff = time.time() - max(0, older_than_secs)
            deleted = self._db.execute(
                f'DELETE FROM {_T} WHERE done_at IS NOT NULL AND done_at < ?', (cutoff,))
            self._db.commit()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0


def create(db: BaseConnector) -> ServiceCommandsStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return ServiceCommandsStore(db)
