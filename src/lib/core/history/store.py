#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Time-series history store for ServiceSentry check results.

Backed by a pluggable :class:`lib.db.BaseConnector` (SQLite by default;
PostgreSQL/MySQL supported through the same interface).

Schema
------
Table ``history`` — one row per monitored item per check cycle:

    id        — auto-increment primary key
    ts        — Unix timestamp (float)
    module    — watchful module name  (e.g. "service_status")
    item_uid  — stable UUID for the item (null when not yet assigned)
    key       — display name at recording time  (e.g. "AnyDesk")
    status    — 1 = OK, 0 = error
    data      — JSON snapshot of other_data from the check result
"""

from __future__ import annotations

import json
import re
import time

from lib.db import BaseConnector, get_connector
from lib.db.schema import Column, Index, TableSpec

_PREFERRED_FIELDS = (
    'temp', 'used', 'count', 'code', 'response_time',
    'latency_ms', 'latency', 'value', 'rate', 'level',
)

# Whitelist for JSON field names used in get_stats (prevents SQL/JSON-path injection).
_FIELD_RE = re.compile(r'^[A-Za-z0-9_]+$')

_SCHEMA = TableSpec(
    name='history',
    columns=(
        Column('id',       'AUTOINCREMENT', primary_key=True),
        Column('ts',       'REAL', nullable=False),
        Column('module',   'TEXT', nullable=False),
        Column('item_uid', 'TEXT'),
        Column('key',      'TEXT', nullable=False),
        Column('status',   'INTEGER', nullable=False),
        Column('data',     'TEXT'),
    ),
    indexes=(
        Index('idx_history_uid_ts', ('item_uid', 'ts')),
        Index('idx_history_mkts',   ('module', 'key', 'ts')),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth


class HistoryStore:
    """Backend-agnostic time-series store."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema bootstrap ──────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        module: str,
        key: str,
        status: bool,
        data: dict | None = None,
        *,
        item_uid: str | None = None,
    ) -> None:
        """Insert one sample."""
        try:
            self._db.execute(
                f'INSERT INTO {_T}(ts, module, item_uid, key, status, data) '
                'VALUES(?, ?, ?, ?, ?, ?)',
                (
                    time.time(),
                    module,
                    item_uid,
                    key,
                    1 if status else 0,
                    json.dumps(data or {}, ensure_ascii=False),
                ),
            )
            self._db.commit()
        except Exception as exc:  # pylint: disable=broad-except
            import sys  # noqa: PLC0415
            print(
                f'[history] record() FAILED {module}/{key}: '
                f'{type(exc).__name__}: {exc}',
                file=sys.stderr, flush=True,
            )

    def delete_series(
        self, module: str, key: str, *, item_uid: str | None = None
    ) -> int:
        """Delete all records for one series (by UID when available)."""
        try:
            with self._db.transaction():
                if item_uid:
                    deleted = self._db.execute(
                        f'DELETE FROM {_T} WHERE item_uid = ?', (item_uid,)
                    )
                else:
                    deleted = self._db.execute(
                        f'DELETE FROM {_T} WHERE module = ? AND key = ?',
                        (module, key),
                    )
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    def delete_all(self) -> int:
        """Delete all rows and reclaim disk space."""
        try:
            deleted = self._db.execute(f'DELETE FROM {_T}')
            self._db.commit()
            self._db.vacuum()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    def prune(self, retention_days: int) -> int:
        """Delete records older than *retention_days* (0 = keep all)."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        try:
            deleted = self._db.execute(f'DELETE FROM {_T} WHERE ts < ?', (cutoff,))
            self._db.commit()
            self._db.checkpoint()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Read ──────────────────────────────────────────────────────────────────

    def latest_ts(self) -> float | None:
        """Unix timestamp of the most recent recorded check, or None if empty.

        Used to detect an external monitoring worker: if the web's own scheduler
        is stopped yet checks keep landing here, a separate worker is running."""
        try:
            row = self._db.fetchone(f'SELECT MAX(ts) FROM {_T}')
        except Exception:  # pylint: disable=broad-except
            return None
        return row[0] if row and row[0] is not None else None

    def get_index(self) -> list[dict]:
        """Return metadata for every recorded series.

        One table scan: a window function picks each series' latest row (for
        ``last_data`` / ``last_status`` / current ``key``) while a grouped
        aggregate gives count / first / last / uptime.  This replaces the two
        correlated subqueries per series the previous version ran — those keyed
        on ``COALESCE(item_uid, module||':'||key)``, an expression no index can
        serve, so each rescanned the whole table (O(series x rows), which got
        slow as the history grew).
        """
        try:
            rows = self._db.fetchall(f'''
                WITH ranked AS (
                    SELECT
                        module, item_uid, key, ts, status, data,
                        COALESCE(item_uid, module || ':' || key) AS grp,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(item_uid, module || ':' || key)
                            ORDER BY ts DESC, id DESC
                        ) AS rn
                    FROM {_T}
                ),
                agg AS (
                    SELECT
                        COALESCE(item_uid, module || ':' || key) AS grp,
                        COUNT(*)      AS cnt,
                        MAX(ts)       AS last_ts,
                        MIN(ts)       AS first_ts,
                        AVG(status)   AS uptime
                    FROM {_T}
                    GROUP BY COALESCE(item_uid, module || ':' || key)
                )
                SELECT
                    r.module, r.item_uid, r.key,
                    a.cnt, a.last_ts, a.first_ts, a.uptime,
                    r.data   AS last_data,
                    r.status AS last_status
                FROM ranked r
                JOIN agg a ON a.grp = r.grp
                WHERE r.rn = 1
                ORDER BY r.module, r.key
            ''')
        except Exception:  # pylint: disable=broad-except
            return []
        return [
            {
                'module':      r[0],
                'item_uid':    r[1],
                'key':         r[2],
                'count':       r[3],
                'last_ts':     r[4],
                'first_ts':    r[5],
                'uptime':      round((r[6] or 0) * 100, 1),
                'last_data':   _load_json(r[7]),
                'last_status': None if r[8] is None else bool(r[8]),
            }
            for r in rows
        ]

    def query(
        self,
        module: str,
        key: str,
        from_ts: float,
        to_ts: float,
        max_points: int = 500,
        *,
        item_uid: str | None = None,
    ) -> list[dict]:
        """Return (possibly time-bucketed) samples ordered by time."""
        if item_uid:
            where  = 'item_uid = ? AND ts >= ? AND ts <= ?'
            w_args: tuple = (item_uid, from_ts, to_ts)
        else:
            where  = 'module = ? AND key = ? AND ts >= ? AND ts <= ?'
            w_args = (module, key, from_ts, to_ts)
        try:
            row = self._db.fetchone(
                f'SELECT COUNT(*) FROM {_T} WHERE {where}', w_args
            )
            count = row[0] if row else 0
            if count == 0:
                return []

            bucket = (to_ts - from_ts) / max_points if max_points > 0 else 0
            if count <= max_points or bucket <= 0:
                rows = self._db.fetchall(
                    f'SELECT ts, status, data FROM {_T} '
                    f'WHERE {where} ORDER BY ts',
                    w_args,
                )
            else:
                rows = self._db.fetchall(
                    f'''SELECT
                        CAST((ts - ?) / ? AS INTEGER) * ? + ? AS bts,
                        CAST(ROUND(AVG(status)) AS INTEGER),
                        data
                    FROM {_T} WHERE {where}
                    GROUP BY CAST((ts - ?) / ? AS INTEGER)
                    ORDER BY bts''',
                    (from_ts, bucket, bucket, from_ts) + w_args + (from_ts, bucket),
                )

            return [
                {'ts': r[0], 'status': r[1], 'data': _load_json(r[2])}
                for r in rows
            ]
        except Exception:  # pylint: disable=broad-except
            return []

    def get_stats(
        self,
        module: str,
        key: str,
        from_ts: float,
        to_ts: float,
        field: str | None = None,
        *,
        item_uid: str | None = None,
    ) -> dict:
        """Return aggregate statistics for a series in a time range."""
        if item_uid:
            where  = 'item_uid = ? AND ts >= ? AND ts <= ?'
            w_args: tuple = (item_uid, from_ts, to_ts)
        else:
            where  = 'module = ? AND key = ? AND ts >= ? AND ts <= ?'
            w_args = (module, key, from_ts, to_ts)
        try:
            row = self._db.fetchone(
                f'SELECT COUNT(*), AVG(status), MIN(ts), MAX(ts) '
                f'FROM {_T} WHERE {where}',
                w_args,
            )
            if not row or not row[0]:
                return {}
            result: dict = {
                'count':    row[0],
                'uptime':   round((row[1] or 0) * 100, 1),
                'first_ts': row[2],
                'last_ts':  row[3],
            }
            # Only chart fields matching a strict whitelist (no SQL/JSON-path injection).
            if field and _FIELD_RE.match(field):
                path = f'$.{field}'
                num = self._db.fetchone(
                    "SELECT MIN(CAST(json_extract(data, ?) AS REAL)),"
                    "       MAX(CAST(json_extract(data, ?) AS REAL)),"
                    "       AVG(CAST(json_extract(data, ?) AS REAL)) "
                    f"FROM {_T} WHERE {where} "
                    "AND json_extract(data, ?) IS NOT NULL",
                    (path, path, path) + w_args + (path,),
                )
                if num and num[0] is not None:
                    result['min'] = num[0]
                    result['max'] = num[1]
                    result['avg'] = num[2]
            return result
        except Exception:  # pylint: disable=broad-except
            return {}

    @staticmethod
    def suggest_field(points: list[dict]) -> str | None:
        """Return the best numeric field name to chart from a sample set."""
        sample: dict = {}
        for p in points[:20]:
            sample.update(p.get('data') or {})
        for f in _PREFERRED_FIELDS:
            if isinstance(sample.get(f), (int, float)):
                return f
        for k, v in sample.items():
            if isinstance(v, (int, float)):
                return k
        return None

    def close(self) -> None:
        """No-op: the connector owns the connection lifecycle."""


# ── Module-level helpers ──────────────────────────────────────────────────────

def create(
    db_config: dict | None = None,
    *,
    sqlite_path: str,
) -> 'HistoryStore':
    """Build a HistoryStore backed by a connector from *db_config*.

    When *db_config* is None or has no ``driver``, a SQLite connector is used
    at *sqlite_path*.
    """
    connector = get_connector(db_config or None, default_sqlite_path=sqlite_path)
    return HistoryStore(connector)


def _load_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}
