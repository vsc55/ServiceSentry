#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for the internal fail2ban — the jail plus the shared offense
counters and attempt log.

Three tables, all on the general connector so **every process** (web workers,
the syslog service…) reads and writes the SAME state — the counters and bans are
therefore shared across a multi-process / microservice deployment and survive a
restart, instead of living in one process's memory:

  * ``ip_bans``             — one row per jailed address (the authoritative jail).
  * ``ip_offense_counters`` — a fixed-window counter per (ip, track): the running
                              "how close to a ban" tally, incremented on each offense.
  * ``ip_offense_log``      — a bounded per-IP attempt log for the detail modal.

Written by :class:`lib.security.ipban.IpBanManager`.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='ip_bans',
    columns=(
        Column('uid',        'TEXT',    primary_key=True),
        Column('ip',         'TEXT',    nullable=False, default="''", unique=True),
        Column('reason',     'TEXT',    nullable=False, default="''"),
        Column('category',   'TEXT',    nullable=False, default="''"),
        Column('level',      'INTEGER', nullable=False, default='1'),
        Column('offenses',   'INTEGER', nullable=False, default='0'),
        Column('banned_at',  'REAL',    nullable=False, default='0'),
        # NULL banned_until ⇒ permanent ban.
        Column('banned_until', 'REAL',  nullable=True),
        Column('first_seen', 'REAL',    nullable=False, default='0'),
        Column('created_by', 'TEXT',    nullable=False, default="'system'"),
        Column('detail',     'TEXT',    nullable=False, default="''"),
        # Per-ban block-action override ('' = use the global ipban_block_action).
        Column('block_action', 'TEXT',  nullable=False, default="''"),
    ),
    indexes=(Index('idx_ip_bans_until', ('banned_until',)),),
)

# Fixed-window offense counter, shared across processes. One row per (ip, track);
# incremented on each offense, reset when the trailing window elapses.
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

# Per-service block-action choice (fail2ban service registry), one row per service.
_SVC = TableSpec(
    name='ip_service_action',
    columns=(
        Column('uid',     'TEXT', primary_key=True),   # stable row id
        Column('service', 'TEXT', nullable=False, default="''", unique=True),
        Column('action',  'TEXT', nullable=False, default="''"),
    ),
)

# Bounded per-IP attempt log (for the history modal). Trimmed globally.
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

# Append-only ban history: one row per ban lifecycle event (banned / escalated /
# unbanned), kept as an audit trail of what was banned, why and for how long — even
# after the ban itself expires and drops off the active jail.
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

_T = _SCHEMA.name
_TC = _COUNTERS.name
_TL = _LOG.name
_TS = _SVC.name
_TH = _HIST.name
_SELECT = ('uid, ip, reason, category, level, offenses, banned_at, banned_until, '
           'first_seen, created_by, detail, block_action')
_MAX_ROWS = 5000        # cap distinct jailed IPs (a rotating-IP flood can't grow forever)
_MAX_COUNTERS = 20000   # cap distinct counter rows
_MAX_LOG = 20000        # cap total attempt-log rows
_MAX_HIST = 20000       # cap total ban-history rows


class IpBanStore:
    """Persistent, cross-process fail2ban state: jail + offense counters + log."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_SCHEMA)
        self._db.reconcile_table(_COUNTERS)
        self._db.reconcile_table(_LOG)
        self._db.reconcile_table(_SVC)
        self._db.reconcile_table(_HIST)

    def upsert(self, ip: str, rec: dict) -> None:
        """Insert or replace the ban row for *ip* from a manager record."""
        if not ip:
            return
        try:
            with self._db.transaction():
                row = self._db.fetchone(f'SELECT uid FROM {_T} WHERE ip = ?', (ip,))
                vals = (rec.get('reason', ''), rec.get('category', ''),
                        int(rec.get('level', 1)), int(rec.get('offenses', 0)),
                        float(rec.get('banned_at', 0) or 0), rec.get('until'),
                        float(rec.get('first_seen', 0) or 0),
                        rec.get('by', 'system'), rec.get('detail', ''),
                        rec.get('block_action', '') or '')
                if row:
                    self._db.execute(
                        f'UPDATE {_T} SET reason=?, category=?, level=?, offenses=?, '
                        'banned_at=?, banned_until=?, first_seen=?, created_by=?, detail=?, '
                        'block_action=? WHERE ip=?', (*vals, ip))
                else:
                    self._db.execute(
                        f'INSERT INTO {_T} ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (str(uuid.uuid4()), ip, *vals))
                    cnt = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
                    if cnt and cnt[0] > _MAX_ROWS:
                        self._db.execute(
                            f'DELETE FROM {_T} WHERE ip IN '
                            f'(SELECT ip FROM {_T} ORDER BY banned_at ASC LIMIT ?)',
                            (cnt[0] - _MAX_ROWS,))
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass

    def delete(self, ip: str) -> bool:
        """Remove *ip*'s ban row (on unban).  True if a row was deleted."""
        if not ip:
            return False
        try:
            if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE ip = ?', (ip,)):
                return False
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE ip = ?', (ip,))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def delete_by_uid(self, uid: str) -> str | None:
        """Delete one ban by its row uid; return the freed IP (or None)."""
        try:
            row = self._db.fetchone(f'SELECT ip FROM {_T} WHERE uid = ?', (uid,))
            if not row:
                return None
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
            return row[0]
        except Exception:  # pylint: disable=broad-except
            return None

    def load_active(self, now: float) -> list[dict]:
        """Rows whose ban is still in force (permanent or not yet expired) — seeds the
        in-memory jail on boot.  Expired rows are pruned in passing."""
        try:
            self._db.execute(
                f'DELETE FROM {_T} WHERE banned_until IS NOT NULL AND banned_until <= ?',
                (now,))
        except Exception:  # pylint: disable=broad-except
            pass
        rows = self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T} '
            'WHERE banned_until IS NULL OR banned_until > ? ORDER BY banned_at DESC',
            (now,))
        return [self._row(r) for r in rows]

    def query(self, *, limit: int = 500) -> list[dict]:
        limit = max(1, min(_MAX_ROWS, int(limit)))
        rows = self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T} ORDER BY banned_at DESC LIMIT ?', (limit,))
        return [self._row(r) for r in rows]

    def get_ban(self, ip: str) -> dict | None:
        """The current ban row for *ip* (or None) — used to read the escalation level."""
        row = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE ip = ?', (ip,))
        return self._row(row) if row else None

    def active_bans(self, now: float) -> list[dict]:
        """Every still-in-force ban (permanent or not yet expired). Read fresh by the
        manager (with a short cache) so a ban made by ANY process is enforced here too."""
        rows = self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T} '
            'WHERE banned_until IS NULL OR banned_until > ? ORDER BY banned_at DESC', (now,))
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> dict:
        return {'uid': r[0], 'ip': r[1], 'reason': r[2], 'category': r[3],
                'level': r[4], 'offenses': r[5], 'banned_at': r[6],
                # 'until' key mirrors the manager record shape for load()
                'until': r[7], 'banned_until': r[7], 'first_seen': r[8],
                'by': r[9], 'created_by': r[9], 'detail': r[10],
                'block_action': r[11] if len(r) > 11 else ''}

    # ── shared offense counters (fixed window) ──────────────────────────────────
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

    def reset_counters(self, ip: str) -> None:
        """Drop just the offense counters for *ip* (keep its attempt log) — called
        after a ban so the now-jailed IP starts fresh if the ban later expires."""
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_TC} WHERE ip = ?', (ip,))
        except Exception:  # pylint: disable=broad-except
            pass

    def clear_offenses(self, ip: str) -> bool:
        """Forget an IP's counters + attempt log (watchlist removal). True if any existed."""
        if not ip:
            return False
        try:
            had = self._db.fetchone(f'SELECT 1 FROM {_TC} WHERE ip = ?', (ip,)) is not None
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_TC} WHERE ip = ?', (ip,))
                self._db.execute(f'DELETE FROM {_TL} WHERE ip = ?', (ip,))
            return had
        except Exception:  # pylint: disable=broad-except
            return False

    # ── attempt log (bounded, for the modal) ────────────────────────────────────
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

    # ── per-service block-action choices (service registry) ─────────────────────
    def service_actions(self) -> dict:
        """``{service_id: action}`` — the persisted per-service block-action choices."""
        try:
            rows = self._db.fetchall(f'SELECT service, action FROM {_TS}')
            return {r[0]: r[1] for r in rows if r[1]}
        except Exception:  # pylint: disable=broad-except
            return {}

    def set_service_action(self, service: str, action: str) -> None:
        """Upsert (or, on an empty action, delete) a service's block-action choice."""
        if not service:
            return
        try:
            with self._db.transaction():
                if not action:
                    self._db.execute(f'DELETE FROM {_TS} WHERE service = ?', (service,))
                    return
                row = self._db.fetchone(f'SELECT 1 FROM {_TS} WHERE service = ?', (service,))
                if row:
                    self._db.execute(f'UPDATE {_TS} SET action = ? WHERE service = ?',
                                     (action, service))
                else:
                    self._db.execute(
                        f'INSERT INTO {_TS} (uid, service, action) VALUES (?,?,?)',
                        (str(uuid.uuid4()), service, action))
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass

    # ── ban history (append-only audit trail) ───────────────────────────────────
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

    def prune(self, now: float, *, max_age: float = 86400) -> None:
        """Housekeeping (called periodically): drop stale counters and trim the log."""
        try:
            self._db.execute(f'DELETE FROM {_TC} WHERE updated_at < ?', (now - max_age,))
            row = self._db.fetchone(f'SELECT MAX(id) FROM {_TL}')
            if row and row[0] and row[0] > _MAX_LOG:
                self._db.execute(f'DELETE FROM {_TL} WHERE id <= ?', (row[0] - _MAX_LOG,))
            hrow = self._db.fetchone(f'SELECT MAX(id) FROM {_TH}')
            if hrow and hrow[0] and hrow[0] > _MAX_HIST:
                self._db.execute(f'DELETE FROM {_TH} WHERE id <= ?', (hrow[0] - _MAX_HIST,))
        except Exception:  # pylint: disable=broad-except
            pass


def create(db: BaseConnector) -> IpBanStore:
    return IpBanStore(db)
