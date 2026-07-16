#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``ip_offense_counters`` — the fixed-window offense counter, shared across processes.

One row per ``(ip, track)``: the running "how close to a ban" tally, incremented on
each offense and reset when the trailing window elapses.  On the general connector so
all processes count against the SAME total.  Written via the
:class:`~lib.services.ipban.store.IpBanStore` facade.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_COUNTERS = TableSpec(
    name='ip_offense_counters',
    columns=(
        Column('uid',          'TEXT',    primary_key=True),   # stable row id
        Column('ip',           'TEXT',    nullable=False, default="''"),
        Column('track',        'TEXT',    nullable=False, default="''"),
        Column('count',        'INTEGER', nullable=False, default='0'),
        Column('window_start', 'REAL',    nullable=False, default='0'),
        Column('updated_at',   'REAL',    nullable=False, default='0'),
    ),
    unique_constraints=(('ip', 'track'),),                     # natural key stays unique
    indexes=(Index('idx_ip_offc_updated', ('updated_at',)),),
)

_TC = _COUNTERS.name
_MAX_COUNTERS = 20000   # cap distinct counter rows


class OffenseCountersStore:
    """Shared fixed-window offense counters (``ip_offense_counters``)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_COUNTERS)

    def bump_offense(self, ip: str, track: str, now: float, window: float) -> int:
        """Increment the (ip, track) counter and return its new in-window count.

        Fixed window: the count accumulates until *window* seconds pass since the
        window opened, then resets. One row read + write per offense, in the shared
        DB, so all processes count against the SAME total."""
        try:
            with self._db.transaction():
                row = self._db.fetchone(
                    f'SELECT count, window_start FROM {_TC} WHERE ip = ? AND track = ?',
                    (ip, track))
                if row is None:
                    self._db.execute(
                        f'INSERT INTO {_TC} (uid, ip, track, count, window_start, updated_at) '
                        'VALUES (?,?,?,?,?,?)', (str(uuid.uuid4()), ip, track, 1, now, now))
                    return 1
                if now - float(row[1] or 0) >= window:
                    self._db.execute(
                        f'UPDATE {_TC} SET count = 1, window_start = ?, updated_at = ? '
                        'WHERE ip = ? AND track = ?', (now, now, ip, track))
                    return 1
                count = int(row[0]) + 1
                self._db.execute(
                    f'UPDATE {_TC} SET count = ?, updated_at = ? WHERE ip = ? AND track = ?',
                    (count, now, ip, track))
                return count
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
            return 0

    def counters(self) -> list[dict]:
        """All offense counter rows (for the watchlist): ``{ip, track, count, window_start}``."""
        rows = self._db.fetchall(
            f'SELECT ip, track, count, window_start FROM {_TC} '
            f'ORDER BY updated_at DESC LIMIT ?', (_MAX_COUNTERS,))
        return [{'ip': r[0], 'track': r[1], 'count': int(r[2]), 'window_start': r[3]}
                for r in rows]

    def reset(self, ip: str) -> None:
        """Drop just the offense counters for *ip* (keep its attempt log) — called
        after a ban so the now-jailed IP starts fresh if the ban later expires."""
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_TC} WHERE ip = ?', (ip,))
        except Exception:  # pylint: disable=broad-except
            pass

    def clear(self, ip: str) -> bool:
        """Delete *ip*'s counters. True if any existed (drives the watchlist-removal result)."""
        try:
            had = self._db.fetchone(f'SELECT 1 FROM {_TC} WHERE ip = ?', (ip,)) is not None
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_TC} WHERE ip = ?', (ip,))
            return had
        except Exception:  # pylint: disable=broad-except
            return False

    def prune_stale(self, now: float, max_age: float) -> None:
        """Drop counter rows untouched for longer than *max_age* seconds."""
        try:
            with self._db.transaction():   # commit so the prune persists on PG/MySQL
                self._db.execute(f'DELETE FROM {_TC} WHERE updated_at < ?', (now - max_age,))
        except Exception:  # pylint: disable=broad-except
            pass
