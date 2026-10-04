#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for external syslog sources — other programs' message databases.

A *source* is a connection to a database rsyslog (or LogAnalyzer) fills: its `SystemEvents`
table is read, never written or altered (see :mod:`lib.services.syslog.sources`, which opens
them). The panel's own table is not a row here: it is always there, as the source the UI
calls "internal".

Lives in the main database, beside the rest of the configuration-like data. The connection
travels in ``data`` as JSON and its password is encrypted at rest, the same value-level
Fernet scheme as the stored credentials.

Schema::

    syslog_sources(uid PK, name UNIQUE, enabled, watch, time_zone,
                   data(json {driver, host, port, name, user, password, path, cred_uid}),
                   created_at, updated_at, updated_by)
"""

from __future__ import annotations

import json
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore, EncryptedPayloadMixin
from lib.security import secret_manager

_SCHEMA = TableSpec(
    name='syslog_sources',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('name',       'TEXT', nullable=False, default="''", unique=True),
        # 0 = kept but not offered: not in the selector, not read, not watched.
        Column('enabled',    'INTEGER', nullable=False, default='1'),
        # 1 = the event rules evaluate its new rows (one cursor per source).
        Column('watch',      'INTEGER', nullable=False, default='0'),
        # The zone of ITS dates (rsyslog's stock template writes the local time of the
        # machine it runs on): 'UTC' or 'local'.
        Column('time_zone',  'TEXT', nullable=False, default="'UTC'"),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_syslog_sources_name', ('name',)),),
)

_T = _SCHEMA.name
_COLS = ('uid', 'name', 'enabled', 'watch', 'time_zone', 'data',
         'created_at', 'updated_at', 'updated_by')
_SELECT = ', '.join(_COLS)

#: The connection keys a source keeps; anything else in a payload is dropped. `cred_uid`
#: names a stored "database" credential whose user and password are used instead of these.
CONN_KEYS = ('driver', 'host', 'port', 'name', 'user', 'password', 'path', 'cred_uid')
DRIVERS = ('mysql', 'mariadb', 'postgresql', 'sqlite')
TIME_ZONES = ('UTC', 'local')


def clean_conn(data: dict | None) -> dict:
    """The connection part of a payload, normalised: known keys only, a known driver, an
    integer port or none."""
    d = data if isinstance(data, dict) else {}
    out = {k: d.get(k) for k in CONN_KEYS if k in d}
    drv = str(out.get('driver') or 'mysql').strip().lower()
    out['driver'] = drv if drv in DRIVERS else 'mysql'
    for k in ('host', 'name', 'user', 'path', 'cred_uid'):
        out[k] = str(out.get(k) or '').strip()
    try:
        port = int(out.get('port') or 0)
        out['port'] = port if 0 < port < 65536 else None
    except (TypeError, ValueError):
        out['port'] = None
    if out.get('password') is not None:
        out['password'] = str(out['password'])
    return out


class SyslogSourcesStore(EncryptedPayloadMixin, BaseStore):
    """The configured external syslog sources (backend-agnostic)."""

    _TABLE = _T

    def __init__(self, db: BaseConnector, *, fernet=None, secret_keys=None) -> None:
        super().__init__(db)
        self._fernet = fernet
        self._secret_keys = secret_keys or secret_manager.ENCRYPT_KEYS
        self._db.reconcile_table(_SCHEMA)

    # ── Row mapping ───────────────────────────────────────────────────────────
    def _row(self, row, decrypt: bool) -> dict:
        uid, name, enabled, watch, tz, data, c_at, u_at, u_by = row
        try:
            d = json.loads(data) if data else {}
        except (ValueError, TypeError):
            d = {}
        if decrypt:
            d = self._decrypt(d)
        return {
            'uid': uid, 'name': name or '', 'enabled': bool(enabled), 'watch': bool(watch),
            'time_zone': tz if tz in TIME_ZONES else 'UTC',
            'data': d if isinstance(d, dict) else {},
            'created_at': c_at or '', 'updated_at': u_at or '', 'updated_by': u_by or '',
        }

    # ── Read ──────────────────────────────────────────────────────────────────
    def list(self, *, decrypt: bool = True) -> list[dict]:
        return [self._row(r, decrypt)
                for r in self._db.fetchall(f'SELECT {_SELECT} FROM {_T} ORDER BY name')]

    def get(self, uid: str, *, decrypt: bool = True) -> dict | None:
        row = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE uid = ?', (uid,))
        return self._row(row, decrypt) if row else None

    # ── Write ─────────────────────────────────────────────────────────────────
    def _values(self, data: dict) -> tuple:
        tz = str(data.get('time_zone') or 'UTC')
        return (str(data.get('name') or '').strip(),
                0 if data.get('enabled') is False else 1,
                1 if data.get('watch') else 0,
                tz if tz in TIME_ZONES else 'UTC',
                json.dumps(self._encrypt(clean_conn(data.get('data'))), ensure_ascii=False))

    def _name_taken(self, name: str, uid: str = '') -> bool:
        return bool(self._db.fetchone(
            f'SELECT 1 FROM {_T} WHERE name = ? AND uid <> ?', (name, uid)))

    def create(self, data: dict, *, actor: str = '') -> str | None:
        """Insert a source. Its uid, or None for a missing or taken name."""
        vals = self._values(data)
        if not vals[0] or self._name_taken(vals[0]):
            return None
        uid = str(data.get('uid') or uuid.uuid4())
        now = self._now()
        with self._db.transaction():
            self._db.execute(f'INSERT INTO {_T} ({_SELECT}) VALUES (?,?,?,?,?,?,?,?,?)',
                             (uid, *vals, now, now, actor or ''))
        return uid

    def update(self, uid: str, data: dict, *, actor: str = '') -> bool:
        """Replace a source wholesale (the caller restored a masked password first)."""
        if not self.get(uid, decrypt=False):
            return False
        vals = self._values(data)
        if not vals[0] or self._name_taken(vals[0], uid):
            return False
        with self._db.transaction():
            self._db.execute(
                f'UPDATE {_T} SET name=?, enabled=?, watch=?, time_zone=?, data=?, '
                'updated_at=?, updated_by=? WHERE uid=?',
                (*vals, self._now(), actor or '', uid))
        return True

    def delete(self, uid: str) -> bool:
        if not self.get(uid, decrypt=False):
            return False
        with self._db.transaction():
            self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
        return True
