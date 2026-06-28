#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Store for the notification-send log (event-rule notifications).

Each row records one notification attempt fired by an event rule: when, which
rule, the channels targeted, whether it succeeded, and any error.  Capped by a
row limit (newest kept) so it never grows unbounded.

Schema::

    event_rules_notifications(id PK AUTOINCREMENT, ts REAL, rule_id, rule_name,
                              source, channels, ok INTEGER, message)
"""

from __future__ import annotations

import time

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='event_rules_notifications',
    columns=(
        Column('id',        'AUTOINCREMENT', primary_key=True),
        Column('ts',        'REAL',    nullable=False, default='0'),
        Column('rule_id',   'TEXT',    nullable=False, default="''"),
        Column('rule_name', 'TEXT',    nullable=False, default="''"),
        Column('source',    'TEXT',    nullable=False, default="''"),
        Column('channels',  'TEXT',    nullable=False, default="''"),
        Column('ok',        'INTEGER', nullable=False, default='0'),
        Column('message',   'TEXT',    nullable=False, default="''"),
    ),
    indexes=(Index('idx_notiflog_ts', ('ts',)),),
)

_T = _SCHEMA.name
_MAX_ROWS = 1000


class NotificationLogStore:
    """Append-only log of notification sends (with a row cap)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    def add(self, *, rule_id: str = '', rule_name: str = '', source: str = '',
            channels='', ok: bool = False, message: str = '') -> None:
        if isinstance(channels, (list, tuple)):
            channels = ','.join(str(c) for c in channels)
        try:
            self._db.execute(
                f'INSERT INTO {_T} (ts, rule_id, rule_name, source, channels, ok, message) '
                'VALUES (?,?,?,?,?,?,?)',
                (time.time(), str(rule_id), str(rule_name), str(source),
                 str(channels), 1 if ok else 0, str(message)[:1000]))
            # Trim to the newest _MAX_ROWS rows.
            row = self._db.fetchone(
                f'SELECT id FROM {_T} ORDER BY id DESC LIMIT 1 OFFSET ?', (_MAX_ROWS,))
            if row and row[0]:
                self._db.execute(f'DELETE FROM {_T} WHERE id <= ?', (row[0],))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass

    def query(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        limit = max(1, min(2000, int(limit)))
        offset = max(0, int(offset))
        rows = self._db.fetchall(
            f'SELECT id, ts, rule_id, rule_name, source, channels, ok, message '
            f'FROM {_T} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?', (limit, offset))
        out = []
        for r in rows:
            out.append({'id': r[0], 'ts': r[1], 'rule_id': r[2], 'rule_name': r[3],
                        'source': r[4], 'channels': r[5], 'ok': bool(r[6]), 'message': r[7]})
        return out

    def count(self) -> int:
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return row[0] if row else 0

    def delete_all(self) -> int:
        try:
            n = self._db.execute(f'DELETE FROM {_T}')
            self._db.commit()
            return n
        except Exception:  # pylint: disable=broad-except
            return 0


def create(db: BaseConnector) -> NotificationLogStore:
    return NotificationLogStore(db)
