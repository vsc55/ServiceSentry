#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``health_alerts`` — what the expiry scanners have already announced.

The certificate and secret scanners alert **once per severity** (``expiring`` → ``expired``)
and re-arm when the thing is renewed. That memory used to be a dict in the scanner, and the
process that scans is not a fixed one: a web restart, a rolling deploy or the lease moving to
another replica started with an empty dict and announced every certificate inside the warning
window again. Same problem, same answer as ``dc_drift`` and ``event_cooldowns``: a row.

:class:`AlertState` is a small dict-like view (``get`` / ``[]=`` / ``pop`` / ``in``) over one
scanner's keys, so the scanners keep reading like they did. Without a database it is a plain
in-process dict (unit tests, a store that could not be built); a database read that fails
falls back to the last value this process knew, so a hiccup does not re-announce everything.
"""

from __future__ import annotations

import threading
import uuid

from lib.db.schema import Column, TableSpec

#: `alert_key` and not `key`: `key` is a reserved word in MySQL.
SCHEMA = TableSpec(
    name='health_alerts',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        # `<scanner>:<target>` — e.g. `cert:web-1`, `secret:oidc`.
        Column('alert_key',  'TEXT', nullable=False, default="''", unique=True),
        # The severity last announced: `expiring` / `expired`.
        Column('severity',   'TEXT', nullable=False, default="''"),
        Column('alerted_at', 'REAL', nullable=False, default='0'),
    ),
)

_T = SCHEMA.name


class AlertState:
    """``{key: severity}`` already announced by one scanner (*scope*), kept in the database
    when one is given."""

    def __init__(self, db=None, scope: str = '') -> None:
        self._db = db
        self._scope = str(scope or '')
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        if db is not None:
            db.reconcile_table(SCHEMA)

    def _k(self, key) -> str:
        return f'{self._scope}:{key}' if self._scope else str(key)

    def get(self, key, default=None):
        key = str(key)
        if self._db is not None:
            try:
                row = self._db.fetchone(
                    f'SELECT severity FROM {_T} WHERE alert_key = ?', (self._k(key),))
                sev = str(row[0] or '') if row else ''
                with self._lock:
                    if sev:
                        self._cache[key] = sev
                    else:
                        self._cache.pop(key, None)
                return sev or default
            except Exception:  # pylint: disable=broad-except
                pass
        with self._lock:
            return self._cache.get(key, default)

    def __contains__(self, key) -> bool:
        return self.get(key) is not None

    def __setitem__(self, key, severity) -> None:
        self.set(key, severity)

    def set(self, key, severity: str, now: float = 0.0) -> None:
        key, severity = str(key), str(severity or '')
        with self._lock:
            self._cache[key] = severity
        if self._db is None:
            return
        try:
            n = self._db.execute(
                f'UPDATE {_T} SET severity = ?, alerted_at = ? WHERE alert_key = ?',
                (severity, float(now or 0), self._k(key)))
            if not n:
                self._db.execute(
                    f'INSERT INTO {_T}(uid, alert_key, severity, alerted_at) VALUES(?, ?, ?, ?)',
                    (str(uuid.uuid4()), self._k(key), severity, float(now or 0)))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            pass

    def pop(self, key, default=None):
        """Forget *key* (re-arm its alert). Returns the severity it had, or *default*."""
        key = str(key)
        prev = self.get(key, default)
        with self._lock:
            self._cache.pop(key, None)
        if self._db is not None and prev is not default:
            try:
                self._db.execute(f'DELETE FROM {_T} WHERE alert_key = ?', (self._k(key),))
                self._db.commit()
            except Exception:  # pylint: disable=broad-except
                pass
        return prev
