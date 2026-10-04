#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backed store for received syslog messages, in rsyslog's own table.

The table is ``SystemEvents``, column for column the one rsyslog's ``createDB.sql`` builds for
``ommysql``/``ompgsql`` (and LogAnalyzer reads). That is the point of it: rsyslog can write to
the same table with its stock template, the panel shows those rows beside the ones its own
receiver stored, and ``syslog_db`` can be pointed at a database rsyslog already fills. Its
companion ``SystemEventsProperties`` is declared too, so a database the panel creates is the
one rsyslog expects; nothing here writes to it.

What rsyslog has no column for — the sender's IP, the program name and PID apart from the
tag, the RFC 5424 MSGID, the raw line — goes in columns of our own appended AFTER rsyslog's,
all of them nullable and without a default: an insert that names only rsyslog's columns
still works, and adding them to a table rsyslog created is an ``ADD COLUMN``, never a
rebuild of a table that may hold millions of rows.

Times are ``DATETIME`` with no zone, because that is what rsyslog writes. Which zone they are
in is a setting (``syslog|time_zone``: ``UTC`` or ``local``), applied both ways — rsyslog's
stock template writes the local time of the machine it runs on.

Rows come out as they always did (``ts``, ``received_at``, ``source``, ``hostname``, ``app``,
…): the API, the UI and the event rules never see rsyslog's column names.

Retention is enforced by age (days) and by a hard row cap, whichever hits first.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.services.syslog.parser import SEVERITIES, FACILITIES

_SCHEMA = TableSpec(
    name='SystemEvents',
    columns=(
        # ── rsyslog's createDB.sql, in its order ─────────────────────────────
        Column('ID',                 'AUTOINCREMENT', primary_key=True),
        Column('CustomerID',         'INTEGER'),
        Column('ReceivedAt',         'DATETIME'),
        Column('DeviceReportedTime', 'DATETIME'),
        Column('Facility',           'INTEGER'),
        Column('Priority',           'INTEGER'),     # the SEVERITY (rsyslog's %syslogpriority%)
        Column('FromHost',           'TEXT'),
        Column('Message',            'TEXT'),
        Column('NTSeverity',         'INTEGER'),
        Column('Importance',         'INTEGER'),
        Column('EventSource',        'TEXT'),
        Column('EventUserID',        'TEXT'),
        Column('EventCategory',      'INTEGER'),
        Column('EventID',            'INTEGER'),
        Column('EventBinaryData',    'TEXT'),
        Column('MaxAvailable',       'INTEGER'),
        Column('CurrUsage',          'INTEGER'),
        Column('MinUsage',           'INTEGER'),
        Column('MaxUsage',           'INTEGER'),
        Column('InfoUnitID',         'INTEGER'),     # 1 = syslog
        Column('SysLogTag',          'TEXT'),        # "app[pid]:"
        Column('EventLogType',       'TEXT'),
        Column('GenericFileName',    'TEXT'),
        Column('SystemID',           'INTEGER'),
        # ── ours, after rsyslog's: nullable, no default (see the module docstring) ──
        Column('FromHostIP',         'TEXT'),
        Column('ProgramName',        'TEXT'),
        Column('ProcessID',          'TEXT'),
        Column('MsgID',              'TEXT'),
        Column('RawMessage',         'TEXT'),
    ),
    indexes=(
        Index('idx_systemevents_received', ('ReceivedAt',)),
        Index('idx_systemevents_prio',     ('Priority', 'ReceivedAt')),
        Index('idx_systemevents_host',     ('FromHost', 'ReceivedAt')),
        # The facets' DISTINCT and the stats' GROUP BY on program/facility were full table
        # scans — the main cause of a slow Syslog tab.
        Index('idx_systemevents_program',  ('ProgramName', 'ReceivedAt')),
        Index('idx_systemevents_facility', ('Facility', 'ReceivedAt')),
    ),
)

# rsyslog's companion table (createDB.sql): name/value pairs per event. Declared so the
# database matches what rsyslog expects; the panel neither writes nor reads it beyond pruning.
_PROPS = TableSpec(
    name='SystemEventsProperties',
    columns=(
        Column('ID',            'AUTOINCREMENT', primary_key=True),
        Column('SystemEventID', 'INTEGER'),
        Column('ParamName',     'TEXT'),
        Column('ParamValue',    'TEXT'),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth
_P = _PROPS.name

# What our receiver writes. rsyslog's stock template names the first eight of these.
_COLS = ('ReceivedAt', 'DeviceReportedTime', 'Facility', 'Priority', 'FromHost', 'Message',
         'InfoUnitID', 'SysLogTag', 'FromHostIP', 'ProgramName', 'ProcessID', 'MsgID',
         'RawMessage')
_INSERT = f'INSERT INTO {_T} ({", ".join(_COLS)}) VALUES ({",".join("?" * len(_COLS))})'
# What a row is read from, in `_to_dict`'s order.
_READ = ('ID', 'ReceivedAt', 'FromHostIP', 'FromHost', 'ProgramName', 'SysLogTag', 'ProcessID',
         'Priority', 'Facility', 'MsgID', 'Message', 'RawMessage')

# rsyslog sizes these varchar(60); a longer value fails the insert on a strict MySQL or on
# PostgreSQL, and a table rsyslog created is exactly that shape.
_RSYSLOG_VARCHAR = 60

_INFO_UNIT_SYSLOG = 1

_DT_FMT = '%Y-%m-%d %H:%M:%S'
# "sshd[123]:" → ("sshd", "123"); "kernel:" → ("kernel", "").
_TAG_RE = re.compile(r'^\s*([^\[:\s]+)(?:\[([^\]]*)\])?:?')
# How long a time-zone setting is trusted before the store asks for it again.
_ZONE_TTL = 30.0
# How long a read-only store trusts what it saw of somebody else's table. Somebody else can
# change it — add our columns, or create the table at all — and the store notices this late.
_COLS_TTL = 60.0


class ReadOnlyStore(RuntimeError):
    """A write to a message table this panel only reads (an external source)."""


def _t(v) -> str:
    # No NUL in a text value: PostgreSQL rejects it outright.
    return str(v or '').replace('\x00', '')


def split_tag(tag: str) -> tuple[str, str]:
    """``(program, pid)`` from an rsyslog ``SysLogTag`` such as ``sshd[123]:``."""
    m = _TAG_RE.match(tag or '')
    if not m:
        return '', ''
    return m.group(1), m.group(2) or ''


class SyslogStore:
    """Backend-agnostic store for received syslog messages."""

    def __init__(self, db: BaseConnector, time_zone=None, read_only: bool = False) -> None:
        """*time_zone* is ``'UTC'`` (the default) or ``'local'``, or a callable returning one
        — the owner's config, read again every ``_ZONE_TTL`` seconds so a change in the panel
        reaches a running receiver.

        *read_only* is a table that belongs to somebody else — rsyslog's own database, as an
        external source (``lib.services.syslog.sources``) or as the syslog database itself
        (``syslog_db|mode = external``). Its schema is never touched (no column, no index, no
        companion table: the account may only be allowed to SELECT, and the DBA did not ask
        for any of it), nothing is written, pruned or emptied, and it is read with the
        columns it HAS: ours that are missing come back empty."""
        self._db = db
        self._tz_src = time_zone
        self._tz_cache: tuple[float, bool] | None = None
        self.read_only = bool(read_only)
        self._x_cache: tuple[float, dict] | None = None
        self._bootstrap()

    def _bootstrap(self) -> None:
        if self.read_only:
            return
        self._db.reconcile_table(_SCHEMA)
        self._db.reconcile_table(_PROPS)

    # ── The columns the table has ────────────────────────────────────────────
    def _x(self) -> dict:
        """The SQL pieces every read is built from, against the columns the table has.

        Our own table has all of them. Somebody else's may lack ours (`FromHostIP`,
        `ProgramName`…) or not exist yet; a missing column reads as NULL — never as an error
        — and a missing table as an empty one."""
        now = time.monotonic()
        if self._x_cache and (not self.read_only or now - self._x_cache[0] < _COLS_TTL):
            return self._x_cache[1]
        have = None
        if self.read_only:
            try:
                have = {c.name.lower() for c in self._db.describe_table(_T)}
            except Exception:  # pylint: disable=broad-except
                have = set()

        def c(name: str) -> str:
            return name if have is None or name.lower() in have else 'NULL'

        x = {
            'table': have is None or bool(have),
            'select': ', '.join(c(n) for n in _READ),
            # "Effective host": the parsed hostname, or the sender IP when none was parsed.
            # Used everywhere a host is shown/filtered (table, facet dropdown, chart, filter)
            # so they all agree — a message with no hostname is grouped by its source IP.
            'host': f"COALESCE(NULLIF({c('FromHost')}, ''), {c('FromHostIP')})",
            # The program: ours, or rsyslog's whole tag when a row came through its stock
            # template.
            'app': f"COALESCE(NULLIF({c('ProgramName')}, ''), {c('SysLogTag')})",
            # rsyslog's columns are nullable; a breakdown must not hand the UI a None.
            'sev': f"COALESCE({c('Priority')}, 5)",
            'fac': f"COALESCE({c('Facility')}, 1)",
            'col': {n: c(n) for n in _READ},
        }
        self._x_cache = (now, x)
        return x

    def _writable(self) -> None:
        if self.read_only:
            raise ReadOnlyStore('the syslog table belongs to another program '
                                '(an external source): nothing is written to it')

    # ── Time ─────────────────────────────────────────────────────────────────
    def _local(self) -> bool:
        """True when the table's times are the machine's local time, False for UTC."""
        now = time.monotonic()
        if self._tz_cache and now - self._tz_cache[0] < _ZONE_TTL:
            return self._tz_cache[1]
        src = self._tz_src
        try:
            val = src() if callable(src) else src
        except Exception:  # pylint: disable=broad-except
            val = None
        local = str(val or '').strip().lower() == 'local'
        self._tz_cache = (now, local)
        return local

    def _to_db(self, epoch: float) -> str:
        """A unix time as the table writes it: ``YYYY-MM-DD HH:MM:SS`` in the table's zone."""
        if self._local():
            return datetime.fromtimestamp(float(epoch)).strftime(_DT_FMT)
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime(_DT_FMT)

    def _from_db(self, value) -> float | None:
        """A stored time back to unix time. The driver hands a ``datetime`` (MySQL,
        PostgreSQL) or the text (SQLite) — in rsyslog's MySQL form too, ``YYYYMMDDHHMMSS``."""
        if value is None or value == '':
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip().replace('T', ' ')
            dt = None
            for fmt in (_DT_FMT, '%Y-%m-%d %H:%M:%S.%f', '%Y%m%d%H%M%S'):
                try:
                    dt = datetime.strptime(text[:26], fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                return None
        if dt.tzinfo is not None:
            return dt.timestamp()
        if self._local():
            return dt.timestamp()
        return dt.replace(tzinfo=timezone.utc).timestamp()

    def _reported(self, rec: dict, received: float) -> str:
        """The sender's own time as the table writes it, or the received one without it.

        RFC 5424 carries a zone; RFC 3164 carries neither zone nor year, and is taken — as
        rsyslog takes it — as the table's zone, in the year that keeps it from the future."""
        ts = str(rec.get('timestamp') or '').strip()
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if dt.tzinfo is not None:
                    return self._to_db(dt.timestamp())
                return dt.strftime(_DT_FMT)
            except ValueError:
                pass
            try:
                ref = datetime.fromtimestamp(received)
                dt = datetime.strptime(f'{ref.year} {" ".join(ts.split())}', '%Y %b %d %H:%M:%S')
                if (dt - ref).days > 1:
                    dt = dt.replace(year=dt.year - 1)
                return dt.strftime(_DT_FMT)
            except ValueError:
                pass
        return self._to_db(received)

    # ── Write ─────────────────────────────────────────────────────────────────
    def _row_values(self, rec: dict) -> tuple:
        received = float(rec.get('ts') or time.time())
        app, procid = _t(rec.get('app')), _t(rec.get('procid'))
        tag = (f'{app}[{procid}]:' if procid else f'{app}:') if app else ''
        return (
            self._to_db(received),
            self._reported(rec, received),
            int(rec.get('facility', 1)),
            int(rec.get('severity', 5)),
            _t(rec.get('hostname'))[:_RSYSLOG_VARCHAR],
            _t(rec.get('message'))[:16384],
            _INFO_UNIT_SYSLOG,
            tag[:_RSYSLOG_VARCHAR],
            _t(rec.get('source')),
            app,
            procid,
            _t(rec.get('msgid')),
            _t(rec.get('raw'))[:16384],
        )

    def add(self, rec: dict) -> None:
        """Insert one parsed message (the dict from ``parse_message``)."""
        self._writable()
        self._db.execute(_INSERT, self._row_values(rec))
        self._db.commit()

    def add_many(self, recs: list[dict]) -> int:
        """Insert a batch of messages in one transaction (listener buffering).

        If the batch fails, it is retried row by row so one bad record costs itself and
        not the up-to-500 messages around it. Returns how many rows were stored; raises
        only when not one could be."""
        self._writable()
        if not recs:
            return 0
        try:
            with self._db.transaction():
                for rec in recs:
                    self._db.execute(_INSERT, self._row_values(rec))
            return len(recs)
        except Exception:  # pylint: disable=broad-except
            if len(recs) == 1:
                raise
        stored, last_exc = 0, None
        for rec in recs:
            try:
                with self._db.transaction():
                    self._db.execute(_INSERT, self._row_values(rec))
                stored += 1
            except Exception as exc:  # pylint: disable=broad-except
                last_exc = exc
        if stored == 0 and last_exc is not None:
            raise last_exc
        return stored

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

    def _where(self, filters: dict) -> tuple[str, list]:
        """Build a parameterised WHERE clause from optional filters.

        ``hostname`` / ``app`` / ``facility`` / ``severity`` accept either a single
        value or a list (the dashboard's Ctrl+click multi-select → ``IN (...)``)."""
        clauses, params = [], []
        f = filters or {}
        x = self._x()
        c = x['col']
        if f.get('source'):
            clauses.append(f"{c['FromHostIP']} = ?"); params.append(str(f['source']))
        # host: match a server by either its parsed hostname OR its sender IP
        # (used by the per-server Logs tab, where the address may be either).
        if f.get('host'):
            clauses.append(f"({c['FromHost']} = ? OR {c['FromHostIP']} = ?)")
            params.extend([str(f['host']), str(f['host'])])
        for col, key, cast in ((x['host'], 'hostname', str), (x['app'], 'app', str),
                               (c['Facility'], 'facility', int), (c['Priority'], 'severity', int)):
            cl, pa = self._multi(col, f.get(key), cast)
            if cl:
                clauses.append(cl); params.extend(pa)
        # severity_max: include messages at this severity or MORE severe (lower number)
        if f.get('severity_max') is not None and f['severity_max'] != '':
            clauses.append(f"{c['Priority']} <= ?"); params.append(int(f['severity_max']))
        if f.get('since') is not None and f['since'] != '':
            clauses.append(f"{c['ReceivedAt']} >= ?"); params.append(self._to_db(float(f['since'])))
        if f.get('until') is not None and f['until'] != '':
            clauses.append(f"{c['ReceivedAt']} <= ?"); params.append(self._to_db(float(f['until'])))
        if f.get('q'):
            clauses.append(f"{c['Message']} LIKE ?"); params.append(f"%{f['q']}%")
        return ((' WHERE ' + ' AND '.join(clauses)) if clauses else ''), params

    def _to_dict(self, row) -> dict:
        (rid, received, source, hostname, program, tag, procid,
         severity, facility, msgid, message, raw) = row
        if not program and tag:
            program, tag_pid = split_tag(tag)
            procid = procid or tag_pid
        severity = 5 if severity is None else int(severity)
        facility = 1 if facility is None else int(facility)
        ts = self._from_db(received)
        return {
            'id': rid, 'ts': ts,
            'received_at': (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))
                            if ts is not None else ''),
            'source': source or '', 'hostname': hostname or '', 'app': program or '',
            'procid': procid or '',
            'severity': severity,
            'severity_name': SEVERITIES[severity] if 0 <= severity < len(SEVERITIES) else str(severity),
            'facility': facility,
            'facility_name': FACILITIES[facility] if 0 <= facility < len(FACILITIES) else str(facility),
            'msgid': msgid or '', 'message': message or '', 'raw': raw or '',
        }

    # Columns the API may sort by → physical column (whitelist; safe to inline).
    _SORTABLE = {
        'ts': 'ReceivedAt', 'received_at': 'ReceivedAt', 'source': 'FromHostIP',
        'hostname': 'FromHost', 'app': 'ProgramName', 'procid': 'ProcessID',
        'severity': 'Priority', 'facility': 'Facility', 'msgid': 'MsgID', 'message': 'Message',
    }

    def query(self, filters: dict | None = None, *, limit: int = 200, offset: int = 0,
              sort: str = 'ts', order: str = 'desc') -> list[dict]:
        """Return matching messages (newest first by default, or per *sort*/*order*)."""
        x = self._x()
        if not x['table']:
            return []
        where, params = self._where(filters or {})
        limit = max(1, min(5000, int(limit)))
        offset = max(0, int(offset))
        col = x['col'].get(self._SORTABLE.get(sort, 'ReceivedAt'), 'NULL')
        if col == 'NULL':
            # A column the table does not have. PostgreSQL refuses `ORDER BY NULL` outright
            # (a constant there is a position), and the order would be no order anyway.
            col = 'ID'
        direction = 'ASC' if str(order).lower() == 'asc' else 'DESC'
        rows = self._db.fetchall(
            f'SELECT {x["select"]} FROM {_T}{where} ORDER BY {col} {direction}, ID {direction} '
            'LIMIT ? OFFSET ?',
            (*params, limit, offset))
        return [self._to_dict(r) for r in rows]

    def query_since(self, last_id: int, limit: int = 500) -> list[dict]:
        """Rows with id > *last_id*, oldest first — for the event worker cursor."""
        x = self._x()
        if not x['table']:
            return []
        rows = self._db.fetchall(
            f'SELECT {x["select"]} FROM {_T} WHERE ID > ? ORDER BY ID ASC LIMIT ?',
            (int(last_id), max(1, min(5000, int(limit)))))
        return [self._to_dict(r) for r in rows]

    def max_id(self) -> int:
        """Highest row id (0 when empty) — used to seed the worker cursor at the tail."""
        if not self._x()['table']:
            return 0
        row = self._db.fetchone(f'SELECT MAX(ID) FROM {_T}')
        return int(row[0]) if row and row[0] is not None else 0

    def count(self, filters: dict | None = None) -> int:
        if not self._x()['table']:
            return 0
        where, params = self._where(filters or {})
        row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}{where}', tuple(params))
        return row[0] if row else 0

    def _group_counts(self, column: str, where: str, params: list, top: int) -> list[dict]:
        """``[{value, count}]`` for the top *column* values matching the filter."""
        rows = self._db.fetchall(
            f'SELECT {column} AS v, COUNT(*) AS c FROM {_T}{where} '
            f'GROUP BY {column} ORDER BY c DESC, v ASC LIMIT ?',
            (*params, int(top)))
        return [{'value': r[0], 'count': r[1]} for r in rows]

    def stats(self, filters: dict | None = None, *, top: int = 10,
              only: tuple[str, ...] | None = None) -> dict:
        """Aggregate counts for the dashboard charts: total + breakdowns by host,
        severity, facility (family) and app.

        Faceted: each breakdown applies every *other* filter but NOT its own, so
        all of a dimension's options stay visible even after one is selected —
        that's what lets the UI multi-select several values of the same type.

        *only* restricts which breakdowns are computed (``None`` = all of them). Each one
        is a separate ``GROUP BY`` over the message table, so asking for the four when the
        caller reads one makes the query four times as expensive on a large store — the
        Overview card wants just the total and the severity split. Omitted breakdowns come
        back as empty lists, never missing keys."""
        base = filters or {}
        x = self._x()
        want = set(only) if only else {'host', 'app', 'severity', 'facility'}
        if not x['table']:
            want = set()
        total = self.count(base)

        def grp(column: str, own_key: str, limit: int, name: str) -> list:
            if name not in want:
                return []
            sub = {k: v for k, v in base.items() if k != own_key}
            where, params = self._where(sub)
            return self._group_counts(column, where, params, limit)

        by_device = grp(x['host'], 'hostname', top, 'host')
        by_app = grp(x['app'], 'app', top, 'app')
        by_sev = grp(x['sev'], 'severity', len(SEVERITIES), 'severity')
        by_fac = grp(x['fac'], 'facility', len(FACILITIES), 'facility')
        return {
            'total': total,
            'by_device': by_device,
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
        x = self._x()
        expr = {'source': x['col']['FromHostIP'], 'hostname': x['host'],
                'app': x['app']}.get(column)
        if expr is None or expr == 'NULL' or not x['table']:
            return []
        rows = self._db.fetchall(
            f"SELECT DISTINCT {expr} AS v FROM {_T} WHERE {expr} <> '' ORDER BY v")
        return [r[0] for r in rows]

    # ── Retention ───────────────────────────────────────────────────────────────
    # Neither runs on a table this panel only reads: what rsyslog's database keeps, and for how
    # long, is decided by whoever owns it. Both answer 0 rather than raise, because the
    # retention loop calls `prune` on every store and has no business knowing whose it is.

    def prune(self, *, retention_days: int = 0, max_rows: int = 0) -> int:
        """Drop messages older than *retention_days* and beyond *max_rows* (newest
        kept).  0 disables that limit.  Returns the number of rows deleted."""
        if self.read_only:
            return 0
        deleted = 0
        if retention_days and retention_days > 0:
            cutoff = self._to_db(time.time() - retention_days * 86400)
            deleted += self._db.execute(f'DELETE FROM {_T} WHERE ReceivedAt < ?', (cutoff,)) or 0
            self._db.commit()
        if max_rows and max_rows > 0:
            # Find the id just past the newest max_rows, delete everything <= it.
            row = self._db.fetchone(
                f'SELECT ID FROM {_T} ORDER BY ID DESC LIMIT 1 OFFSET ?', (int(max_rows),))
            if row:
                deleted += self._db.execute(f'DELETE FROM {_T} WHERE ID <= ?', (row[0],)) or 0
                self._db.commit()
        if deleted:
            # rsyslog's properties of the events just dropped (none, with its stock template).
            first = self._db.fetchone(f'SELECT MIN(ID) FROM {_T}')
            if first and first[0] is not None:
                self._db.execute(f'DELETE FROM {_P} WHERE SystemEventID < ?', (first[0],))
            else:
                self._db.execute(f'DELETE FROM {_P}')
            self._db.commit()
        return deleted

    def delete_all(self) -> int:
        if self.read_only:
            return 0
        deleted = self._db.execute(f'DELETE FROM {_T}') or 0
        self._db.execute(f'DELETE FROM {_P}')
        self._db.commit()
        return deleted


def is_read_only(syslog_db_cfg: dict | None) -> bool:
    """True when ``syslog_db`` points at somebody else's database and the panel only reads it
    (``syslog_db|mode = external``).

    Only with the dedicated database switched on: ``mode`` describes THAT database, and
    without it the messages live in the panel's own — which is always the panel's to write."""
    sdb = syslog_db_cfg or {}
    return bool(sdb.get('enabled')) and str(sdb.get('mode') or '').strip().lower() == 'external'


def create(db: BaseConnector, time_zone=None, read_only: bool = False) -> SyslogStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return SyslogStore(db, time_zone, read_only)
