#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Time-series history store for ServiceSentry check results.

Uses SQLite directly (stdlib ``sqlite3``) so there are no extra dependencies.
WAL journal mode allows concurrent reads from the web admin while the daemon
writes check results.

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
import os
import sqlite3
import threading
import time


_PREFERRED_FIELDS = (
    'temp', 'used', 'count', 'code', 'response_time',
    'latency_ms', 'latency', 'value', 'rate', 'level',
)


class HistoryStore:
    """Thread-safe SQLite-backed time-series store.

    Each thread maintains its own connection via ``threading.local`` so
    concurrent daemon workers and Flask request handlers never share a
    connection object.
    """

    def __init__(self, db_path: str) -> None:
        self._path  = db_path
        self._local = threading.local()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._bootstrap()

    # ── Internal connection ───────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30, isolation_level=None)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=-4096')
            self._local.conn = conn
        return conn

    def _reset_conn(self) -> None:
        """Close the current thread's connection and discard it."""
        conn = getattr(self._local, 'conn', None)
        if conn:
            try:
                conn.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._local.conn = None

    # ── Schema bootstrap ──────────────────────────────────────────────────────

    def _bootstrap(self) -> None:
        """Create table + indices; add item_uid column to legacy databases."""
        conn = self._conn()

        # 1. Create table if missing
        conn.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       REAL    NOT NULL,
                module   TEXT    NOT NULL,
                item_uid TEXT,
                key      TEXT    NOT NULL,
                status   INTEGER NOT NULL,
                data     TEXT
            )
        ''')
        conn.commit()

        # 2. Add item_uid column to databases created before UIDs were added
        existing = {r[1] for r in conn.execute('PRAGMA table_info(history)').fetchall()}
        if 'item_uid' not in existing:
            conn.execute('ALTER TABLE history ADD COLUMN item_uid TEXT')
            conn.commit()

        # 3. Create indices AFTER the column migration so the uid index is safe
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_history_uid_ts '
            'ON history(item_uid, ts)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_history_mkts '
            'ON history(module, key, ts)'
        )
        conn.commit()

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
            self._conn().execute(
                'INSERT INTO history(ts, module, item_uid, key, status, data) '
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
            self._conn().commit()
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
            if item_uid:
                cur = self._conn().execute(
                    'DELETE FROM history WHERE item_uid = ?', (item_uid,)
                )
            else:
                cur = self._conn().execute(
                    'DELETE FROM history WHERE module = ? AND key = ?',
                    (module, key),
                )
            deleted = cur.rowcount
            self._conn().commit()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    def delete_all(self) -> int:
        """Delete all rows and reclaim disk space."""
        try:
            cur = self._conn().execute('DELETE FROM history')
            deleted = cur.rowcount
            self._conn().commit()
            # VACUUM must run outside a transaction; reset connection after.
            self._conn().execute('VACUUM')
            self._reset_conn()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    def prune(self, retention_days: int) -> int:
        """Delete records older than *retention_days* (0 = keep all)."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        try:
            cur = self._conn().execute(
                'DELETE FROM history WHERE ts < ?', (cutoff,)
            )
            deleted = cur.rowcount
            self._conn().execute('PRAGMA wal_checkpoint(PASSIVE)')
            self._conn().commit()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_index(self) -> list[dict]:
        """Return metadata for every recorded series."""
        try:
            rows = self._conn().execute('''
                SELECT
                    h.module,
                    h.item_uid,
                    h.key,
                    COUNT(*)          AS cnt,
                    MAX(h.ts)         AS last_ts,
                    MIN(h.ts)         AS first_ts,
                    AVG(h.status)     AS uptime,
                    (
                        SELECT h2.data FROM history h2
                        WHERE COALESCE(h2.item_uid, h2.module || ':' || h2.key)
                            = COALESCE(h.item_uid, h.module || ':' || h.key)
                        ORDER BY h2.ts DESC LIMIT 1
                    ) AS last_data
                FROM history h
                GROUP BY COALESCE(h.item_uid, h.module || ':' || h.key)
                ORDER BY h.module, h.key
            ''').fetchall()
        except Exception:  # pylint: disable=broad-except
            return []
        return [
            {
                'module':    r[0],
                'item_uid':  r[1],
                'key':       r[2],
                'count':     r[3],
                'last_ts':   r[4],
                'first_ts':  r[5],
                'uptime':    round(r[6] * 100, 1),
                'last_data': _load_json(r[7]),
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
            count = self._conn().execute(
                f'SELECT COUNT(*) FROM history WHERE {where}', w_args
            ).fetchone()[0]

            if count == 0:
                return []

            if count <= max_points:
                rows = self._conn().execute(
                    f'SELECT ts, status, data FROM history '
                    f'WHERE {where} ORDER BY ts',
                    w_args,
                ).fetchall()
            else:
                bucket = (to_ts - from_ts) / max_points
                rows = self._conn().execute(
                    f'''SELECT
                        CAST((ts - ?) / ? AS INTEGER) * ? + ? AS bts,
                        CAST(ROUND(AVG(status)) AS INTEGER),
                        data
                    FROM history WHERE {where}
                    GROUP BY CAST((ts - ?) / ? AS INTEGER)
                    ORDER BY bts''',
                    (from_ts, bucket, bucket, from_ts)
                    + w_args + (from_ts, bucket),
                ).fetchall()

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
            row = self._conn().execute(
                f'SELECT COUNT(*), AVG(status), MIN(ts), MAX(ts) '
                f'FROM history WHERE {where}',
                w_args,
            ).fetchone()
            if not row or not row[0]:
                return {}
            result: dict = {
                'count':    row[0],
                'uptime':   round((row[1] or 0) * 100, 1),
                'first_ts': row[2],
                'last_ts':  row[3],
            }
            if field:
                num = self._conn().execute(
                    f"SELECT MIN(CAST(json_extract(data,'$.{field}') AS REAL)),"
                    f"       MAX(CAST(json_extract(data,'$.{field}') AS REAL)),"
                    f"       AVG(CAST(json_extract(data,'$.{field}') AS REAL)) "
                    f"FROM history WHERE {where} "
                    f"AND json_extract(data,'$.{field}') IS NOT NULL",
                    w_args,
                ).fetchone()
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
        """Close the current thread's connection."""
        self._reset_conn()


# ── Module-level helpers ──────────────────────────────────────────────────────

def create(
    _db_config: dict | None = None,
    *,
    sqlite_path: str,
) -> 'HistoryStore':
    """Factory kept for API compatibility.

    *_db_config* is reserved for future multi-backend support.
    Currently always creates a SQLite-backed store at *sqlite_path*.
    """
    del _db_config  # reserved — not used yet
    return HistoryStore(sqlite_path)


def _load_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}
