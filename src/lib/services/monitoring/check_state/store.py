#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Database-backed check-state store — the single source of truth that
replaces ``status.json``.

Holds exactly one row per check with its full working state: current status,
the last status message, the ``other_data`` metrics snapshot and the
consecutive-failure counter (``fail_count``).  This is both:

* the modules' per-cycle working state (``fail_streak`` counters, ``other_data``,
  ``module_state``, message-change detection), and
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
    severity        — '' (OK), 'error' or 'warning'
    module_state    — JSON, a module's own working state for this check: what it
                      needs to produce the NEXT answer, never a result and never
                      shown.  Reached as ``status.set_conf([mod, key,
                      'module_state', …])``, which is what the SNMP sampler keeps
                      its counter baselines in.

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
from lib.db.store_base import BaseStore

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
        # A module's OWN working state for this check — not a result, never shown. The
        # columns above are the answer; this is what the module needs to produce the NEXT
        # one, and a counter is the case that made it necessary: a rate is the difference
        # between two readings, so the previous reading has to outlive the cycle.
        # Kept LAST because a missing column can only be added by ADD COLUMN when it is
        # trailing — anything earlier means rebuilding the table on every existing install.
        Column('module_state',   'TEXT'),
    ),
    # The (module, key, metric) natural key stays the unique lookup for a check row.
    unique_constraints=(('module', 'key', 'metric'),),
)

_T = _SCHEMA.name  # table name — single source of truth


# The severity rule is defined ONCE, beside the structure that carries the field. This was
# a second identical copy: two statements of the same rule, in the layer that decides how a
# non-OK result is routed. Adding a third level to one of them would have left the other
# flattening it to 'error'.
from lib.modules.dict_return_check import norm_severity as _norm_severity  # noqa: E402


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


class CheckStateStore(BaseStore):
    """Backend-agnostic current-state store (one row per check)."""

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        # ``key`` is a reserved word in MySQL — quote it (dialect-aware) in every raw query
        # so runtime SQL works on MySQL/MariaDB, not just SQLite.
        self._qk = db.quote_ident('key')
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_all(self, module: str | None = None) -> dict:
        """Return ``{(module, key, metric): {uid, item_uid, status, message,
        other_data, fail_count, last_change_ts}}`` (flat, keyed by tuple).

        *module* narrows it to one watchful's rows. A whole-table read is what the monitor
        does once, at the top of a cycle; a save is about ONE module and reading the other
        eleven to write one is the shape that made a collection slow.
        """
        out: dict = {}
        try:
            sql = (f'SELECT uid, module, {self._qk}, item_uid, metric, status, message, '
                   f'other_data, fail_count, last_change_ts, severity, module_state '
                   f'FROM {_T}')
            rows = (self._db.fetchall(sql + ' WHERE module = ?', (module,)) if module
                    else self._db.fetchall(sql))
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
                    'module_state':   _load_json(r[11]),
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
                'module_state': rec.get('module_state') or {},
            }
        return out

    # ── Write ─────────────────────────────────────────────────────────────────

    def set(self, module: str, key: str, status: bool, **kw) -> bool:
        """Insert or replace the current state of one check (portable upsert).

        Keyword args: ``message``, ``item_uid``, ``metric``, ``other_data``,
        ``fail_count``, ``ts``, ``severity``, ``module_state``.  The row's own
        ``uid`` is preserved — and so is its ``module_state`` unless the caller
        passes one: this is the one-row upsert seeds and tests use, and a seed
        that silently erased a module's counter baselines would be a device that
        goes quiet for a cycle for a reason nothing reports.
        """
        metric = kw.get('metric') or ''
        severity = _norm_severity(kw.get('severity'), status)
        try:
            existing = self._db.fetchone(
                f'SELECT uid, module_state FROM {_T} '
                f'WHERE module=? AND {self._qk}=? AND metric=?',
                (module, key, metric),
            )
            row_uid = (existing[0] if existing and existing[0] else None) \
                or str(uuid.uuid4())
            keep = (existing[1] if existing is not None and len(existing) > 1 else None)
            mod_state = (json.dumps(kw['module_state'] or {}, ensure_ascii=False)
                         if 'module_state' in kw else (keep or '{}'))
            with self._db.transaction():
                self._db.execute(
                    f'DELETE FROM {_T} WHERE module=? AND {self._qk}=? AND metric=?',
                    (module, key, metric),
                )
                self._db.execute(
                    f'INSERT INTO {_T}(uid, module, {self._qk}, item_uid, metric, '
                    'status, message, other_data, fail_count, last_change_ts, severity, '
                    'module_state) '
                    'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        row_uid, module, key, kw.get('item_uid'), metric,
                        1 if status else 0,
                        kw.get('message'),
                        json.dumps(kw.get('other_data') or {}, ensure_ascii=False),
                        int(kw.get('fail_count') or 0),
                        kw.get('ts') if kw.get('ts') is not None else time.time(),
                        severity,
                        mod_state,
                    ),
                )
            return True
        except Exception as exc:  # pylint: disable=broad-except
            print(f'[check_state] set() FAILED {module}/{key}: '
                  f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return False

    def persist_module(self, module: str, checks: dict, *, item_uid_resolver=None) -> bool:
        """Replace the rows of ONE watchful, leaving every other module's alone.

        Measured on a fleet-sized table (1400 rows, twelve modules): a whole-table save is
        ~60 ms, and the collection path did one PER MODULE — three quarters of a second of
        `DELETE FROM check_state` per run, with a reader waiting three times longer for every
        page while it happened. A module's own rows are a fraction of that, and the eleven it
        is not about are neither read nor rewritten.

        Same rules as the whole-table version, applied to one module: a row keeps its `uid`
        and its `last_change_ts` while its status is unchanged, and a row this module no
        longer reports is gone — which is what the whole-table write was for.
        """
        mod = str(module or '').strip()
        if not mod:
            return False
        rows = self._rows_for(mod, checks if isinstance(checks, dict) else {},
                              self.get_all(mod), item_uid_resolver)
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE module = ?', (mod,))
                if rows:
                    self._db.executemany(self._insert_sql(), list(rows.values()))
            return True
        except Exception as exc:  # pylint: disable=broad-except
            print(f'[check_state] persist_module({mod!r}) FAILED: '
                  f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return False

    def _insert_sql(self) -> str:
        return (f'INSERT INTO {_T}(uid, module, {self._qk}, item_uid, metric, '
                'status, message, other_data, fail_count, last_change_ts, severity, '
                'module_state) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')

    def _rows_for(self, module: str, checks: dict, existing: dict,
                  item_uid_resolver) -> dict:
        """One module's result dict as insertable tuples, keyed by the composite PK.

        Keyed by ``(module, key, metric)`` so two result keys that resolve to the same row
        (a stale bare ``<item>`` left beside a fresh ``<item>/site``) collapse to one entry —
        last write wins — instead of tripping the UNIQUE constraint and aborting the write.
        """
        now = time.time()
        rows: dict = {}
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
                json.dumps(rec.get('module_state') or {}, ensure_ascii=False),
            )
        return rows

    def persist_status(self, data: dict, *, item_uid_resolver=None) -> bool:
        """Replace the whole table from the nested ``{module: {result_key: rec}}``
        dict.  Each result key is split into ``key`` + ``metric`` (via
        *item_uid_resolver*), preserving each row's ``uid`` and ``last_change_ts``
        while the status is unchanged.
        """
        existing = self.get_all()
        rows: dict = {}
        # Snapshot to avoid "dict changed size during iteration" if a worker
        # thread mutates the live status dict while we persist.
        for module, checks in list(data.items()):
            if not isinstance(checks, dict):
                continue
            rows.update(self._rows_for(module, checks, existing, item_uid_resolver))
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T}')
                if rows:
                    self._db.executemany(self._insert_sql(), list(rows.values()))
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

    def count(self) -> int:
        """How many rows the table holds; ``0`` if it cannot be read.

        Asked before a wipe so the audit entry can say how much was erased. "State cleared"
        with nothing under it is a record that a thing happened, not a record of what — and
        the difference between clearing four rows and four thousand is the whole question
        somebody has when they find that entry.
        """
        try:
            row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:  # pylint: disable=broad-except
            return 0

    def clear(self) -> bool:
        """Forget all current state."""
        try:
            self._db.execute(f'DELETE FROM {_T}')
            self._db.commit()
            return True
        except Exception:  # pylint: disable=broad-except
            return False



# ── Module-level helper ────────────────────────────────────────────────────────

def create(db_config: dict | None = None, *, sqlite_path: str) -> 'CheckStateStore':
    """Build a CheckStateStore backed by a connector from *db_config*."""
    connector = get_connector(db_config or None, default_sqlite_path=sqlite_path)
    return CheckStateStore(connector)
