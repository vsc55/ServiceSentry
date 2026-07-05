#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for the fail2ban never-ban whitelist (with descriptions).

Each row is one trusted IP or CIDR the internal fail2ban must never count nor
block, plus a free-text description of what it is (a monitoring box, an office
range, the reverse proxy…).  The manager loads these values (union with loopback
and the programmatic ``ipban_whitelist`` CSV) into its in-memory allowlist.  Lives
on the general connector so web + syslog share one authoritative whitelist.
"""

from __future__ import annotations

import ipaddress
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='ip_whitelist',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('value',       'TEXT', nullable=False, default="''", unique=True),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at',  'REAL', nullable=False, default='0'),
        Column('created_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_ip_whitelist_value', ('value',)),),
)

_T = _SCHEMA.name
_SELECT = 'uid, value, description, created_at, created_by'
_MAX_ROWS = 2000


def normalize_cidr(value: str) -> str | None:
    """Return the canonical IP/CIDR string for *value*, or None if it is not a
    valid address/network (so the API can reject bad input)."""
    s = str(value or '').strip()
    if not s:
        return None
    try:
        return str(ipaddress.ip_network(s, strict=False))
    except ValueError:
        return None


class IpWhitelistStore:
    """Per-entry never-ban list (IP/CIDR + description), backend-agnostic."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_SCHEMA)

    def list(self) -> list[dict]:
        rows = self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T} ORDER BY created_at ASC LIMIT ?', (_MAX_ROWS,))
        return [{'uid': r[0], 'value': r[1], 'description': r[2], 'created_at': r[3],
                 'created_by': r[4] or ''} for r in rows]

    def values(self) -> list[str]:
        """Just the IP/CIDR strings — what the ban manager needs for its allowlist."""
        return [r[0] for r in self._db.fetchall(f'SELECT value FROM {_T}')]

    def add(self, value: str, description: str, ts: float, created_by: str = '') -> dict | None:
        """Insert a normalized IP/CIDR with a description.  Returns the row, or None
        when the value is invalid or already present."""
        canon = normalize_cidr(value)
        if canon is None:
            return None
        desc = str(description or '').strip()
        by = str(created_by or '').strip()
        try:
            if self._db.fetchone(f'SELECT 1 FROM {_T} WHERE value = ?', (canon,)):
                return None
            uid = str(uuid.uuid4())
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO {_T} ({_SELECT}) VALUES (?,?,?,?,?)',
                    (uid, canon, desc, ts, by))
            return {'uid': uid, 'value': canon, 'description': desc,
                    'created_at': ts, 'created_by': by}
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
            return None

    def delete(self, uid: str) -> bool:
        try:
            if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
                return False
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
            return True
        except Exception:  # pylint: disable=broad-except
            return False


def create(db: BaseConnector) -> IpWhitelistStore:
    return IpWhitelistStore(db)
