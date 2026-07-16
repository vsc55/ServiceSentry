#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Database-backed check-state store — the single source of truth that
replaces ``status.json``.

Holds exactly one row per check with its full working state: current status,
the last status message, the ``other_data`` metrics snapshot and the
consecutive-failure counter (``fail_count``).  This is both:

* the modules' per-cycle working state (``fail_streak`` counters, ``other_data``,
  message-change detection), and
* the durable change-detection baseline (survives restarts, so an ongoing
  OK/DOWN state is not re-announced), and
* the read model for the UI (``/status`` page, overview, host "Latest data").

Schema — table ``check_state`` (composite PK ``module`` + ``key`` + ``metric``):

    uid             — own per-row id (project convention)
    module          — watchful module name
    key             — the item UID (clean, no derived suffix)
    item_uid        — relation to the configured item (== key when resolved)
    metric          — sub-metric of a 1-to-many check (e.g. "ram"/"swap" for
                      ram_swap, the md name for raid, the disk for hddtemp);
                      empty for ordinary 1-to-1 checks
    status          — 1 = OK, 0 = error
    message         — last status message
    other_data      — JSON snapshot of the check's other_data
    fail_count      — consecutive-failure counter (fail_streak)
    last_change_ts  — Unix timestamp of the last status change

A watchful's *result key* (what the module emits, e.g. ``<uid>_ram``) is split
on persist into ``key`` (the item UID) + ``metric`` (the suffix), and
reconstructed on read so modules and the monitor's change detection are
unchanged.  The split only happens when an item-UID resolver is supplied (the
monitor); direct seeds without one keep the key verbatim.
"""

from __future__ import annotations

import json
import sys
import time
import uuid

from lib.config import ConfigControl
from lib.db import BaseConnector, get_connector
from lib.db.schema import Column, TableSpec

_SCHEMA = TableSpec(
    name='check_state',
    columns=(
        Column('uid',            'TEXT', primary_key=True),   # synthetic row id (PK)
        Column('module',         'TEXT', nullable=False),
        Column('key',            'TEXT', nullable=False),
        Column('item_uid',       'TEXT'),
        Column('metric',         'TEXT', nullable=False, default="''"),
        Column('status',         'INTEGER', nullable=False),
        Column('message',        'TEXT'),
        Column('other_data',     'TEXT'),
        Column('fail_count',     'INTEGER', nullable=False, default='0'),
        Column('last_change_ts', 'REAL', nullable=False, default='0'),
        # Severity of a non-OK status: '' (OK), 'error' (default for status=0) or
        # 'warning'. Lets the UI show avisos (yellow) distinctly from errors (red).
        Column('severity',       'TEXT', nullable=False, default="''"),
    ),
    # The (module, key, metric) natural key stays the unique lookup for a check row.
    unique_constraints=(('module', 'key', 'metric'),),
)

_T = _SCHEMA.name  # table name — single source of truth


def _norm_severity(severity, status) -> str:
    """Normalise a check's severity: OK → ''; a non-OK status defaults to 'error'
    unless the module explicitly marks it 'warning'."""
    if status:
        return ''
    return 'warning' if str(severity).lower() == 'warning' else 'error'


def _load_json(raw):
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


def _split_key(module, result_key, resolver):
    """Split a watchful *result_key* into ``(key, metric, item_uid)``.

    A 1-to-many check derives several result keys from one item by either
    convention, and we store the clean item UID in ``key`` + the derived part in
    ``metric`` (so the composite PK ``module+key+metric`` keeps them apart):

    * ``/``-composite ``<item>/<metric>`` (e.g. m365 ``<item>/site`` /
      ``<item>/tenant``, or a cluster ``<uid>/node/pve04``) — the metric may hold
      further ``/``.  Stored WITH its leading ``/`` so it reconstructs with ``/``.
    * ``_``-suffix ``<item>_<metric>`` (e.g. ``<uid>_ram`` / ``<uid>_swap``) —
      stored bare (the ``_`` is re-added on reconstruction).

    The split only applies when *resolver* ``(module, key) -> uid`` is given and
    the item part still resolves to the SAME item — so an item key that merely
    contains ``/`` or ``_`` is never split.  Without a resolver (direct seeds)
    the key is kept verbatim.
    """
    full = resolver(module, result_key) if resolver else None
    if not full:
        return result_key, '', None
    # '/'-composite: the item is the part before the first '/'; the rest (which
    # may contain more '/') is the metric, kept with its leading '/'.
    if '/' in result_key:
        head, _, tail = result_key.partition('/')
        if tail and resolver(module, head) == full:
            return full, '/' + tail, full
    # '_'-suffix: the item is everything before the last '_'; the suffix is the
    # metric, stored bare.
    base = result_key.rsplit('_', 1)[0]
    if base != result_key and resolver(module, base) == full:
        return full, result_key.rsplit('_', 1)[1], full
    return full, '', full


def _join_key(key, metric):
    """Reconstruct a watchful result key from stored ``key`` + ``metric``.

    Inverse of :func:`_split_key`: a metric with a leading ``/`` came from a
    ``/``-composite key (re-joined verbatim), any other non-empty metric is an
    ``_``-suffix, and an empty metric is a plain 1-to-1 key.
    """
    if not metric:
        return key
    return f'{key}{metric}' if metric.startswith('/') else f'{key}_{metric}'


class CheckStateStore:
    """Backend-agnostic current-state store (one row per check)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        # ``key`` is a reserved word in MySQL — quote it (dialect-aware) in every raw query
        # so runtime SQL works on MySQL/MariaDB, not just SQLite.
        self._qk = db.quote_ident('key')
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_all(self) -> dict:
        """Return ``{(module, key, metric): {uid, item_uid, status, message,
        other_data, fail_count, last_change_ts}}`` (flat, keyed by tuple)."""
        out: dict = {}
        try:
            rows = self._db.fetchall(
                f'SELECT uid, module, {self._qk}, item_uid, metric, status, message, '
                f'other_data, fail_count, last_change_ts, severity FROM {_T}'
            )
            for r in rows:
                out[(r[1], r[2], r[4] or '')] = {
                    'uid':            r[0],
                    'item_uid':       r[3],
                    'metric':         r[4] or '',
                    'status':         bool(r[5]),
                    'message':        r[6],
                    'other_data':     _load_json(r[7]),
                    'fail_count':     int(r[8] or 0),
                    'last_change_ts': r[9],
                    'severity':       r[10] or '',
                }
        except Exception:  # pylint: disable=broad-except
            pass
        return out

    def as_status_dict(self) -> dict:
        """Return the nested ``{module: {result_key: {...}}}`` shape that the
        monitor working state and the UI consume.  The watchful *result key* is
        reconstructed from ``key`` + ``metric`` (``<key>_<metric>`` for a
        sub-metric), so modules and change detection see the same key they emit."""
        out: dict = {}
        for (module, key, metric), rec in self.get_all().items():
            result_key = _join_key(key, metric)
            out.setdefault(module, {})[result_key] = {
                'status':     rec['status'],
                'severity':   rec.get('severity', ''),
                'other_data': rec['other_data'],
                'fail_count': rec['fail_count'],
                'message':    rec['message'] or '',
                'ts':         rec['last_change_ts'],
                'item_uid':   rec['item_uid'],
                'metric':     metric,
                'uid':        rec['uid'],
            }
        return out

    # ── Write ─────────────────────────────────────────────────────────────────

    def set(self, module: str, key: str, status: bool, **kw) -> bool:
        """Insert or replace the current state of one check (portable upsert).

        Keyword args: ``message``, ``item_uid``, ``metric``, ``other_data``,
        ``fail_count``, ``ts``, ``severity``.  The row's own ``uid`` is preserved.
        """
        metric = kw.get('metric') or ''
        severity = _norm_severity(kw.get('severity'), status)
        try:
            existing = self._db.fetchone(
                f'SELECT uid FROM {_T} WHERE module=? AND {self._qk}=? AND metric=?',
                (module, key, metric),
            )
            row_uid = (existing[0] if existing and existing[0] else None) \
                or str(uuid.uuid4())
            with self._db.transaction():
                self._db.execute(
                    f'DELETE FROM {_T} WHERE module=? AND {self._qk}=? AND metric=?',
                    (module, key, metric),
                )
                self._db.execute(
                    f'INSERT INTO {_T}(uid, module, {self._qk}, item_uid, metric, '
                    'status, message, other_data, fail_count, last_change_ts, severity) '
                    'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        row_uid, module, key, kw.get('item_uid'), metric,
                        1 if status else 0,
                        kw.get('message'),
                        json.dumps(kw.get('other_data') or {}, ensure_ascii=False),
                        int(kw.get('fail_count') or 0),
                        kw.get('ts') if kw.get('ts') is not None else time.time(),
                        severity,
                    ),
                )
            return True
        except Exception as exc:  # pylint: disable=broad-except
            print(f'[check_state] set() FAILED {module}/{key}: '
                  f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return False

    def persist_status(self, data: dict, *, item_uid_resolver=None) -> bool:
        """Replace the whole table from the nested ``{module: {result_key: rec}}``
        dict.  Each result key is split into ``key`` + ``metric`` (via
        *item_uid_resolver*), preserving each row's ``uid`` and ``last_change_ts``
        while the status is unchanged.
        """
        existing = self.get_all()
        now = time.time()
        # Keyed by the composite PK (module, key, metric) so two result keys that
        # resolve to the same row (e.g. a stale bare '<item>' left next to a fresh
        # '<item>/site') collapse to one entry — last write wins — instead of
        # tripping the UNIQUE constraint and aborting the whole table write.
        rows: dict = {}
        # Snapshot to avoid "dict changed size during iteration" if a worker
        # thread mutates the live status dict while we persist.
        for module, checks in list(data.items()):
            if not isinstance(checks, dict):
                continue
            for result_key, rec in list(checks.items()):
                if not isinstance(rec, dict):
                    continue
                key, metric, item_uid = _split_key(module, result_key, item_uid_resolver)
                if not item_uid:
                    item_uid = rec.get('item_uid')
                status = bool(rec.get('status'))
                ex = existing.get((module, key, metric))
                if ex and ex['status'] == status and ex.get('last_change_ts'):
                    ts = ex['last_change_ts']
                else:
                    ts = rec.get('last_change_ts') or now
                row_uid = (ex.get('uid') if ex else None) or str(uuid.uuid4())
                rows[(module, key, metric)] = (
                    row_uid, module, key, item_uid, metric,
                    1 if status else 0,
                    rec.get('message'),
                    json.dumps(rec.get('other_data') or {}, ensure_ascii=False),
                    int(rec.get('fail_count') or 0),
                    ts,
                    _norm_severity(rec.get('severity'), status),
                )
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T}')
                if rows:
                    self._db.executemany(
                        f'INSERT INTO {_T}(uid, module, {self._qk}, item_uid, metric, '
                        'status, message, other_data, fail_count, last_change_ts, severity) '
                        'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        list(rows.values()),
                    )
            return True
        except Exception as exc:  # pylint: disable=broad-except
            print(f'[check_state] persist_status() FAILED: '
                  f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return False

    def delete(self, module: str, key: str) -> bool:
        """Forget the current state of a check (all its metrics)."""
        try:
            self._db.execute(
                f'DELETE FROM {_T} WHERE module = ? AND {self._qk} = ?', (module, key))
            self._db.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def clear(self) -> bool:
        """Forget all current state."""
        try:
            self._db.execute(f'DELETE FROM {_T}')
            self._db.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""


# ── Module-level helper ────────────────────────────────────────────────────────

def create(db_config: dict | None = None, *, sqlite_path: str) -> 'CheckStateStore':
    """Build a CheckStateStore backed by a connector from *db_config*."""
    connector = get_connector(db_config or None, default_sqlite_path=sqlite_path)
    return CheckStateStore(connector)
