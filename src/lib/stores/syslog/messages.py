#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backed store for received syslog messages.

High-volume, append-mostly time-series: one row per message, keyed by an
auto-increment id (cheaper and naturally ordered vs a UUID).  Retention is
enforced by age (days) and by a hard row cap, whichever hits first.

Schema ``syslog``:
    id, ts(real, received unix), received_at(iso), source(ip), hostname, app,
    procid, severity(int 0..7), facility(int 0..23), msgid, message, raw
"""

from __future__ import annotations

import time

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.services.syslog.parser import SEVERITIES, FACILITIES

_SCHEMA = TableSpec(
    name='syslog',
    columns=(
        Column('id',          'AUTOINCREMENT', primary_key=True),
        Column('ts',          'REAL',    nullable=False),
        Column('received_at', 'TEXT',    nullable=False, default="''"),
        Column('source',      'TEXT',    nullable=False, default="''"),
        Column('hostname',    'TEXT',    nullable=False, default="''"),
        Column('app',         'TEXT',    nullable=False, default="''"),
        Column('procid',      'TEXT',    nullable=False, default="''"),
        Column('severity',    'INTEGER', nullable=False, default='5'),
        Column('facility',    'INTEGER', nullable=False, default='1'),
        Column('msgid',       'TEXT',    nullable=False, default="''"),
        Column('message',     'TEXT',    nullable=False, default="''"),
        Column('raw',         'TEXT',    nullable=False, default="''"),
    ),
    indexes=(
        Index('idx_syslog_ts',       ('ts',)),
        Index('idx_syslog_sev_ts',   ('severity', 'ts')),
        Index('idx_syslog_host_ts',  ('hostname', 'ts')),
        # Speed the facets DISTINCT + stats GROUP BY on app/facility (were full
        # table scans — the main cause of the slow Syslog tab load).
        Index('idx_syslog_app_ts',   ('app', 'ts')),
        Index('idx_syslog_fac_ts',   ('facility', 'ts')),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth
_COLS = ('ts', 'received_at', 'source', 'hostname', 'app', 'procid',
         'severity', 'facility', 'msgid', 'message', 'raw')
_SELECT = 'id, ' + ', '.join(_COLS)

# "Effective host": the parsed hostname, or the sender IP when none was parsed.
# Used everywhere a host is shown/filtered (table, facet dropdown, chart, filter)
# so they all agree — a message with no hostname is grouped by its source IP.
_HOST_EXPR = "COALESCE(NULLIF(hostname, ''), source)"


class SyslogStore:
    """Backend-agnostic store for received syslog messages."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Write ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _row_values(rec: dict) -> tuple:
        return (
            float(rec.get('ts') or time.time()),
            str(rec.get('received_at') or ''),
            str(rec.get('source') or ''),
            str(rec.get('hostname') or ''),
            str(rec.get('app') or ''),
            str(rec.get('procid') or ''),
            int(rec.get('severity', 5)),
            int(rec.get('facility', 1)),
            str(rec.get('msgid') or ''),
            str(rec.get('message') or '')[:16384],
            str(rec.get('raw') or '')[:16384],
        )

    def add(self, rec: dict) -> None:
        """Insert one parsed message (the dict from ``parse_message``)."""
        self._db.execute(
            f'INSERT INTO {_T} ({", ".join(_COLS)}) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            self._row_values(rec))
        self._db.commit()

    def add_many(self, recs: list[dict]) -> None:
        """Insert a batch of messages in one transaction (listener buffering)."""
        if not recs:
            return
        with self._db.transaction():
            for rec in recs:
                self._db.execute(
                    f'INSERT INTO {_T} ({", ".join(_COLS)}) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    self._row_values(rec))

    # ── Read ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _multi(col: str, val, cast=None) -> tuple[str, list]:
        """Clause for an exact filter accepting a single value OR a list of values
        (``col = ?`` for one, ``col IN (?,?,…)`` for several). Empty → no clause."""
        if val is None or val == '':
            return '', []
        vals = list(val) if isinstance(val, (list, tuple)) else [val]
        vals = [v for v in vals if v not in ('', None)]
        if cast:
            vals = [cast(v) for v in vals]
        if not vals:
            return '', []
        if len(vals) == 1:
            return f'{col} = ?', vals
        return f'{col} IN ({",".join("?" * len(vals))})', vals

    @classmethod
    def _where(cls, filters: dict) -> tuple[str, list]:
        """Build a parameterised WHERE clause from optional filters.

        ``hostname`` / ``app`` / ``facility`` / ``severity`` accept either a single
        value or a list (the dashboard's Ctrl+click multi-select → ``IN (...)``)."""
        clauses, params = [], []
        f = filters or {}
        if f.get('source'):
            clauses.append('source = ?'); params.append(str(f['source']))
        # host: match a server by either its parsed hostname OR its sender IP
        # (used by the per-server Logs tab, where the address may be either).
        if f.get('host'):
            clauses.append('(hostname = ? OR source = ?)')
            params.extend([str(f['host']), str(f['host'])])
        for col, key, cast in ((_HOST_EXPR, 'hostname', str), ('app', 'app', str),
                               ('facility', 'facility', int), ('severity', 'severity', int)):
            cl, pa = cls._multi(col, f.get(key), cast)
            if cl:
                clauses.append(cl); params.extend(pa)
        # severity_max: include messages at this severity or MORE severe (lower number)
        if f.get('severity_max') is not None and f['severity_max'] != '':
            clauses.append('severity <= ?'); params.append(int(f['severity_max']))
        if f.get('since') is not None and f['since'] != '':
            clauses.append('ts >= ?'); params.append(float(f['since']))
        if f.get('until') is not None and f['until'] != '':
            clauses.append('ts <= ?'); params.append(float(f['until']))
        if f.get('q'):
            clauses.append('message LIKE ?'); params.append(f"%{f['q']}%")
        return ((' WHERE ' + ' AND '.join(clauses)) if clauses else ''), params

    @staticmethod
    def _to_dict(row) -> dict:
        (rid, ts, received_at, source, hostname, app, procid,
         severity, facility, msgid, message, raw) = row
        return {
            'id': rid, 'ts': ts, 'received_at': received_at, 'source': source,
            'hostname': hostname, 'app': app, 'procid': procid,
            'severity': severity,
            'severity_name': SEVERITIES[severity] if 0 <= severity < len(SEVERITIES) else str(severity),
            'facility': facility,
            'facility_name': FACILITIES[facility] if 0 <= facility < len(FACILITIES) else str(facility),
            'msgid': msgid, 'message': message, 'raw': raw,
        }

    # Columns the API may sort by → physical column (whitelist; safe to inline).
    _SORTABLE = {
        'ts': 'ts', 'received_at': 'received_at', 'source': 'source', 'hostname': 'hostname',
        'app': 'app', 'procid': 'procid', 'severity': 'severity', 'facility': 'facility',
        'msgid': 'msgid', 'message': 'message',
    }

    def query(self, filters: dict | None = None, *, limit: int = 200, offset: int = 0,
              sort: str = 'ts', order: str = 'desc') -> list[dict]:
        """Return matching messages (newest first by default, or per *sort*/*order*)."""
        where, params = self._where(filters or {})
        limit = max(1, min(5000, int(limit)))
        offset = max(0, int(offset))
        col = self._SORTABLE.get(sort, 'ts')
        direction = 'ASC' if str(order).lower() == 'asc' else 'DESC'
        rows = self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T}{where} ORDER BY {col} {direction}, id {direction} '
            'LIMIT ? OFFSET ?',
            (*params, limit, offset))
        return [self._to_dict(r) for r in rows]

    def query_since(self, last_id: int, limit: int = 500) -> list[dict]:
        """Rows with id > *last_id*, oldest first — for the event worker cursor."""
        rows = self._db.fetchall(
            f'SELECT {_SELECT} FROM {_T} WHERE id > ? ORDER BY id ASC LIMIT ?',
            (int(last_id), max(1, min(5000, int(limit)))))
        return [self._to_dict(r) for r in rows]

    def max_id(self) -> int:
        """Highest row id (0 when empty) — used to seed the worker cursor at the tail."""
        row = self._db.fetchone(f'SELECT MAX(id) FROM {_T}')
        return int(row[0]) if row and row[0] is not None else 0

    def count(self, filters: dict | None = None) -> int:
        where, params = self._where(filters or {})
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}{where}', tuple(params))
        return row[0] if row else 0

    def _group_counts(self, column: str, where: str, params: list, top: int) -> list[dict]:
        """``[{value, count}]`` for the top *column* values matching the filter."""
        rows = self._db.fetchall(
            f'SELECT {column}, COUNT(*) AS c FROM {_T}{where} '
            f'GROUP BY {column} ORDER BY c DESC, {column} ASC LIMIT ?',
            (*params, int(top)))
        return [{'value': r[0], 'count': r[1]} for r in rows]

    def stats(self, filters: dict | None = None, *, top: int = 10) -> dict:
        """Aggregate counts for the dashboard charts: total + breakdowns by host,
        severity, facility (family) and app.

        Faceted: each breakdown applies every *other* filter but NOT its own, so
        all of a dimension's options stay visible even after one is selected —
        that's what lets the UI multi-select several values of the same type."""
        base = filters or {}
        total = self.count(base)

        def grp(column: str, own_key: str, limit: int) -> list:
            sub = {k: v for k, v in base.items() if k != own_key}
            where, params = self._where(sub)
            return self._group_counts(column, where, params, limit)

        by_host = grp(_HOST_EXPR, 'hostname', top)
        by_app = grp('app', 'app', top)
        by_sev = grp('severity', 'severity', len(SEVERITIES))
        by_fac = grp('facility', 'facility', len(FACILITIES))
        return {
            'total': total,
            'by_host': by_host,
            'by_app':  by_app,
            'by_severity': [
                {'value': s['value'],
                 'name': SEVERITIES[s['value']] if 0 <= s['value'] < len(SEVERITIES) else str(s['value']),
                 'count': s['count']} for s in by_sev],
            'by_facility': [
                {'value': f['value'],
                 'name': FACILITIES[f['value']] if 0 <= f['value'] < len(FACILITIES) else str(f['value']),
                 'count': f['count']} for f in by_fac],
        }

    def distinct(self, column: str) -> list[str]:
        """Distinct non-empty values of *source*/*hostname*/*app* (for filters).

        For ``hostname`` the *effective host* (hostname, or source when none was
        parsed) is returned, so the dropdown matches the table/chart/filter."""
        if column not in ('source', 'hostname', 'app'):
            return []
        expr = _HOST_EXPR if column == 'hostname' else column
        rows = self._db.fetchall(
            f"SELECT DISTINCT {expr} AS v FROM {_T} WHERE {expr} <> '' ORDER BY v")
        return [r[0] for r in rows]

    # ── Retention ───────────────────────────────────────────────────────────────
    def prune(self, *, retention_days: int = 0, max_rows: int = 0) -> int:
        """Drop messages older than *retention_days* and beyond *max_rows* (newest
        kept).  0 disables that limit.  Returns the number of rows deleted."""
        deleted = 0
        if retention_days and retention_days > 0:
            cutoff = time.time() - retention_days * 86400
            deleted += self._db.execute(f'DELETE FROM {_T} WHERE ts < ?', (cutoff,)) or 0
            self._db.commit()
        if max_rows and max_rows > 0:
            # Find the id just past the newest max_rows, delete everything <= it.
            row = self._db.fetchone(
                f'SELECT id FROM {_T} ORDER BY id DESC LIMIT 1 OFFSET ?', (int(max_rows),))
            if row:
                deleted += self._db.execute(f'DELETE FROM {_T} WHERE id <= ?', (row[0],)) or 0
                self._db.commit()
        return deleted

    def delete_all(self) -> int:
        deleted = self._db.execute(f'DELETE FROM {_T}') or 0
        self._db.commit()
        return deleted


def create(db: BaseConnector) -> SyslogStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return SyslogStore(db)
