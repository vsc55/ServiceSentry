#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``ip_ban_history`` — append-only ban history: one row per ban lifecycle event
(banned / escalated / unbanned).

An audit trail of what was banned, why and for how long — kept even after the ban
itself expires and drops off the active jail.  Trimmed globally to a row cap.
Written via the :class:`~lib.services.ipban.store.IpBanStore` facade.
"""

from __future__ import annotations

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_HIST = TableSpec(
    name='ip_ban_history',
    columns=(
        Column('id',           'AUTOINCREMENT', primary_key=True),
        Column('ip',           'TEXT', nullable=False, default="''"),
        Column('event',        'TEXT', nullable=False, default="''"),   # banned/escalated/unbanned
        Column('reason',       'TEXT', nullable=False, default="''"),
        Column('category',     'TEXT', nullable=False, default="''"),
        Column('level',        'INTEGER', nullable=False, default='0'),
        Column('offenses',     'INTEGER', nullable=False, default='0'),
        Column('banned_at',    'REAL', nullable=False, default='0'),
        Column('banned_until', 'REAL'),                                 # NULL = permanent
        Column('created_by',   'TEXT', nullable=False, default="'system'"),
        Column('ts',           'REAL', nullable=False, default='0'),    # when the event happened
    ),
    indexes=(Index('idx_ip_banhist_ip', ('ip', 'id')),),
)

_TH = _HIST.name
_MAX_HIST = 20000       # cap total ban-history rows


class BanHistoryStore:
    """Append-only ban lifecycle history (``ip_ban_history``)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_HIST)

    def log_ban_event(self, ip: str, event: str, rec: dict, ts: float) -> None:
        """Append a ban lifecycle event (banned / escalated / unbanned) to the history."""
        if not ip:
            return
        try:
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO {_TH} (ip, event, reason, category, level, offenses, '
                    'banned_at, banned_until, created_by, ts) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (ip, event, rec.get('reason', ''), rec.get('category', ''),
                     int(rec.get('level', 0) or 0), int(rec.get('offenses', 0) or 0),
                     float(rec.get('banned_at', 0) or 0), rec.get('until'),
                     rec.get('by', 'system'), ts))
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass

    def ban_history(self, *, limit: int = 500, ip: str | None = None) -> list[dict]:
        """Recent ban lifecycle events (most recent first), optionally for one IP."""
        limit = max(1, min(_MAX_HIST, int(limit)))
        if ip:
            rows = self._db.fetchall(
                f'SELECT id, ip, event, reason, category, level, offenses, banned_at, '
                f'banned_until, created_by, ts FROM {_TH} WHERE ip = ? '
                'ORDER BY id DESC LIMIT ?', (ip, limit))
        else:
            rows = self._db.fetchall(
                f'SELECT id, ip, event, reason, category, level, offenses, banned_at, '
                f'banned_until, created_by, ts FROM {_TH} ORDER BY id DESC LIMIT ?', (limit,))
        return [{'id': r[0], 'ip': r[1], 'event': r[2], 'reason': r[3], 'category': r[4],
                 'level': r[5], 'offenses': r[6], 'banned_at': r[7], 'banned_until': r[8],
                 'by': r[9], 'ts': r[10]} for r in rows]

    def trim(self) -> None:
        """Trim the history to its most recent ``_MAX_HIST`` rows."""
        try:
            hrow = self._db.fetchone(f'SELECT MAX(id) FROM {_TH}')
            if hrow and hrow[0] and hrow[0] > _MAX_HIST:
                with self._db.transaction():   # commit so the trim persists on PG/MySQL
                    self._db.execute(f'DELETE FROM {_TH} WHERE id <= ?', (hrow[0] - _MAX_HIST,))
        except Exception:  # pylint: disable=broad-except
            pass
