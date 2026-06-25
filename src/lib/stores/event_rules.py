#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for event-notification rules.

An *event rule* matches events from a source (audit log / syslog) and, when it
fires, sends a notification through the chosen channels (telegram/email/webhook,
via lib.web_admin.notification_dispatcher).  Like webhooks/hosts/credentials,
rules live in their own DB table (not config.json).

Like the credentials/roles/groups stores, the frequently-displayed/queried
fields (``name``, ``enabled``, ``description``) are first-class columns; the
matching configuration that varies per source lives in the ``data`` JSON blob.
The store's public dict is flat (``{id, name, enabled, description, source,
events, …, last_fired, last_ok}``) so routes/mixin/frontend stay column-agnostic.

Schema::

    event_rules(uid PK, name, enabled, description,
                data(json {source, events[], severity_max, host, app,
                           match_type, match_text, channels[], cooldown,
                           last_fired, last_ok}),
                created_at, updated_at, updated_by)
"""

from __future__ import annotations

import json
import time
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='event_rules',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''"),
        # When 0 the rule is inactive: it is skipped during evaluation.
        Column('enabled',     'INTEGER', nullable=False, default="1"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('data',        'TEXT', nullable=False, default="'{}'"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_event_rules_name', ('name',)),),
)

_T = _SCHEMA.name
_SELECT = 'uid, name, enabled, description, data, created_at, updated_at, updated_by'

# Fields promoted to columns (kept out of the ``data`` JSON blob).
_PROMOTED = ('name', 'enabled', 'description')


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class EventRulesStore:
    """Backend-agnostic store for event→notification rules (one row per rule)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    @staticmethod
    def _row_to_rule(row) -> dict:
        uid, name, enabled, description, data, c_at, u_at, u_by = row
        try:
            d = json.loads(data) if data else {}
        except (ValueError, TypeError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        # Promoted columns win; fall back to legacy values still in `data`
        # (rows written before the columns existed) for a seamless migration.
        rule = {'id': uid, **d}
        rule['name'] = name or d.get('name', '')
        rule['enabled'] = bool(d['enabled']) if 'enabled' in d else bool(enabled)
        rule['description'] = description or d.get('description', '')
        rule['created_at'] = c_at or ''
        rule['updated_at'] = u_at or ''
        rule['updated_by'] = u_by or ''
        return rule

    # ── Read ──────────────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        return [self._row_to_rule(r)
                for r in self._db.fetchall(
                    f'SELECT {_SELECT} FROM {_T} ORDER BY created_at, uid')]

    def get(self, uid: str) -> dict | None:
        row = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE uid = ?', (uid,))
        return self._row_to_rule(row) if row else None

    def count(self) -> int:
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
        return row[0] if row else 0

    # ── Write ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _split(rule: dict) -> tuple[str, str, int, str, dict]:
        """Return (uid, name, enabled, description, data) — promoted fields out
        of the JSON blob, everything else (source/match/last_fired…) into it."""
        r = dict(rule or {})
        uid = str(r.pop('id', None) or uuid.uuid4())
        name = str(r.pop('name', '') or '').strip()
        enabled = 0 if r.pop('enabled', True) is False else 1
        description = str(r.pop('description', '') or '')
        # Never let promoted or store-managed columns leak into the JSON blob.
        for k in (*_PROMOTED, 'created_at', 'updated_at', 'updated_by'):
            r.pop(k, None)
        return uid, name, enabled, description, r

    def upsert(self, rule: dict, *, actor: str = '') -> str:
        """Insert or replace a rule (keyed by its ``id``).  Returns the uid."""
        uid, name, enabled, description, data = self._split(rule)
        now = _now()
        vj = json.dumps(data, ensure_ascii=False)
        with self._db.transaction():
            if self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
                self._db.execute(
                    f'UPDATE {_T} SET name=?, enabled=?, description=?, data=?, '
                    'updated_at=?, updated_by=? WHERE uid=?',
                    (name, enabled, description, vj, now, actor or '', uid))
            else:
                self._db.execute(
                    f'INSERT INTO {_T} ({_SELECT}) VALUES (?,?,?,?,?,?,?,?)',
                    (uid, name, enabled, description, vj, now, now, actor or ''))
        return uid

    def delete(self, uid: str) -> bool:
        if not self._db.fetchone(f'SELECT 1 FROM {_T} WHERE uid = ?', (uid,)):
            return False
        with self._db.transaction():
            self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (uid,))
        return True

    def touch(self, uid: str, *, ts: float, ok: bool) -> None:
        """Record the last-fired time/result on the rule (no updated_by change)."""
        import json as _json  # noqa: PLC0415
        row = self._db.fetchone(f'SELECT data FROM {_T} WHERE uid = ?', (uid,))
        if not row:
            return
        try:
            d = _json.loads(row[0]) if row[0] else {}
        except (ValueError, TypeError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d['last_fired'] = ts
        d['last_ok'] = bool(ok)
        try:
            self._db.execute(f'UPDATE {_T} SET data=? WHERE uid=?',
                             (_json.dumps(d, ensure_ascii=False), uid))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass


def create(db: BaseConnector) -> EventRulesStore:
    return EventRulesStore(db)
