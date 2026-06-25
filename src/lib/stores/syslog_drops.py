#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for syslog senders dropped by the allowlist.

When ``allowed_sources`` is set, packets/connections from any other address are
rejected by the receiver.  This store keeps a small, web-visible tally — one row
per source, with a running drop count and first/last-seen timestamps — so an
operator can tell *what* is being dropped (a misconfigured sender, a scanner…)
without reading debug logs.  Lives on the syslog connector (the dedicated DB when
configured), written by both the embedded listener and the standalone receiver.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='syslog_drops',
    columns=(
        Column('uid',        'TEXT',    primary_key=True),
        Column('source',     'TEXT',    nullable=False, default="''", unique=True),
        Column('transport',  'TEXT',    nullable=False, default="''"),
        Column('count',      'INTEGER', nullable=False, default='0'),
        Column('first_seen', 'REAL',    nullable=False, default='0'),
        Column('last_seen',  'REAL',    nullable=False, default='0'),
    ),
    indexes=(Index('idx_syslog_drops_last', ('last_seen',)),),
)

_T = _SCHEMA.name
_SELECT = 'uid, source, transport, count, first_seen, last_seen'
_MAX_ROWS = 500          # cap distinct sources (a spoofed flood can't grow forever)


class SyslogDropsStore:
    """Per-source tally of allowlist-rejected syslog senders (backend-agnostic)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_SCHEMA)

    def record(self, source: str, transport: str, delta: int, ts: float) -> None:
        """Add *delta* drops for *source* (accumulates across restarts)."""
        if delta <= 0:
            return
        try:
            with self._db.transaction():
                row = self._db.fetchone(f'SELECT 1 FROM {_T} WHERE source = ?', (source,))
                if row:
                    self._db.execute(
                        f'UPDATE {_T} SET count = count + ?, transport = ?, last_seen = ? '
                        'WHERE source = ?', (int(delta), transport or '', ts, source))
                else:
                    self._db.execute(
                        f'INSERT INTO {_T} ({_SELECT}) VALUES (?,?,?,?,?,?)',
                        (str(uuid.uuid4()), source, transport or '', int(delta), ts, ts))
                    # Trim the oldest sources if the table grew past the cap.
                    cnt = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
                    if cnt and cnt[0] > _MAX_ROWS:
                        self._db.execute(
                            f'DELETE FROM {_T} WHERE source IN '
                            f'(SELECT source FROM {_T} ORDER BY last_seen ASC LIMIT ?)',
                            (cnt[0] - _MAX_ROWS,))
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass

    def query(self, *, limit: int = 500) -> list[dict]:
        limit = max(1, min(_MAX_ROWS, int(limit)))
        rows = self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T} ORDER BY last_seen DESC LIMIT ?', (limit,))
        return [{'uid': r[0], 'source': r[1], 'transport': r[2], 'count': r[3],
                 'first_seen': r[4], 'last_seen': r[5]} for r in rows]

    def totals(self) -> dict:
        row = self._db.fetchone(f'SELECT COUNT(*), COALESCE(SUM(count), 0) FROM {_T}')
        return {'sources': row[0] if row else 0, 'dropped': row[1] if row else 0}

    def delete(self, uid: str) -> bool:
        """Remove one source's tally by its uid.  Returns True if a row was deleted."""
        try:
            if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
                return False
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_all(self) -> int:
        try:
            row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
            n = row[0] if row else 0
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T}')
            return n
        except Exception:  # pylint: disable=broad-except
            return 0


def create(db: BaseConnector) -> SyslogDropsStore:
    return SyslogDropsStore(db)
