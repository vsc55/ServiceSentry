#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``ip_bans`` — the authoritative jail: one row per jailed address.

On the general connector so **every process** (web workers, the syslog service…)
reads/writes the SAME jail — bans are shared across a multi-process / microservice
deployment and survive a restart.  Written by
:class:`lib.services.ipban.jail.IpBanManager` via the :class:`~lib.services.ipban.store.IpBanStore`
facade.
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

_T = _SCHEMA.name
_SELECT = ('uid, ip, reason, category, level, offenses, banned_at, banned_until, '
           'first_seen, created_by, detail, block_action')
_MAX_ROWS = 5000        # cap distinct jailed IPs (a rotating-IP flood can't grow forever)


class BansStore:
    """Persistent, cross-process jail (``ip_bans``)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_SCHEMA)

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
