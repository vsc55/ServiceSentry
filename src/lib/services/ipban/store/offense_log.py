#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``ip_offense_log`` — a bounded per-IP attempt log for the detail modal.

Append-only, trimmed globally to a row cap.  Written via the
:class:`~lib.services.ipban.store.IpBanStore` facade.
"""

from __future__ import annotations

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_LOG = TableSpec(
    name='ip_offense_log',
    columns=(
        Column('id',       'AUTOINCREMENT', primary_key=True),
        Column('ip',       'TEXT', nullable=False, default="''"),
        Column('ts',       'REAL', nullable=False, default='0'),
        Column('category', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_ip_offlog_ip', ('ip', 'id')),),
)

_TL = _LOG.name
_MAX_LOG = 20000        # cap total attempt-log rows


class OffenseLogStore:
    """Bounded per-IP attempt log (``ip_offense_log``)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_LOG)

    def log_attempt(self, ip: str, ts: float, category: str) -> None:
        try:
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO {_TL} (ip, ts, category) VALUES (?,?,?)',
                    (ip, ts, category or ''))
        except Exception:  # pylint: disable=broad-except
            pass

    def history(self, ip: str, *, limit: int = 200) -> list[dict]:
        limit = max(1, min(1000, int(limit)))
        rows = self._db.fetchall(
            f'SELECT ts, category FROM {_TL} WHERE ip = ? ORDER BY id DESC LIMIT ?',
            (ip, limit))
        return [{'ts': r[0], 'category': r[1]} for r in rows]

    def clear(self, ip: str) -> None:
        """Forget *ip*'s attempt log (watchlist removal)."""
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_TL} WHERE ip = ?', (ip,))
        except Exception:  # pylint: disable=broad-except
            pass

    def trim(self) -> None:
        """Trim the log to its most recent ``_MAX_LOG`` rows."""
        try:
            row = self._db.fetchone(f'SELECT MAX(id) FROM {_TL}')
            if row and row[0] and row[0] > _MAX_LOG:
                self._db.execute(f'DELETE FROM {_TL} WHERE id <= ?', (row[0] - _MAX_LOG,))
        except Exception:  # pylint: disable=broad-except
            pass
