#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What each background job DID, after it stopped doing it.

The live list answers "what is happening". This answers "what happened" — and until it
existed, nothing did: every job lived in a dict in the process that ran it, the collections
were forgotten half an hour after they ended and the rest went with the next restart. "Did
last night's collection finish", "why did Tuesday's backup fail" and "how long does this
normally take" had no answer at all.

**Written when the work STARTS, and closed when it ends.** Two reasons, and the second one
was reported from the screen:

* archiving from the SCREEN would mean a job nobody happened to open was a job that never
  happened — the collections are pruned from memory on a timer, so it would not even be a
  small window;
* archiving at the END loses everything that never gets one. Restart the panel with a
  collection running and it vanished completely: gone from the live list, because that lives
  in the process that died, and never in the history, because it never finished. It did not
  end and it did not appear to have started.

So the row exists from the first moment, in state ``running`` — and a row in that state when
the process comes UP belongs to a process that is gone. Nothing can be running that this
process did not start: a job is threads in one process and dies with it. Those rows are
closed as ``interrupted``, which is a true thing to say and the one thing nobody could see.

Two decisions are the installation's and live in the config registry (``lib/config/spec.py``):
how much is kept, and how much of each job's own log. A collection of a Synology reports
hundreds of lines; keeping every line of every cycle for a month fills a database with the
part nobody reads. The cap is a cap on LINES and it says how many it dropped — a log that
silently stops is one you cannot trust the end of.
"""

from __future__ import annotations

import json
import time
import uuid

from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

_SCHEMA = TableSpec(
    name='job_history',
    columns=(
        Column('uid',       'TEXT', primary_key=True),
        # The id its own screen polled it by, kept so a row can still lead back there while
        # the job is in both places.
        Column('job_id',    'TEXT', nullable=False, default="''"),
        Column('source',    'TEXT', nullable=False, default="''"),
        Column('kind',      'TEXT', nullable=False, default="''"),
        Column('label',     'TEXT', nullable=False, default="''"),
        Column('state',     'TEXT', nullable=False, default="''"),
        Column('started_at', 'REAL', nullable=False, default='0'),
        Column('ended_at',  'REAL', nullable=False, default='0'),
        Column('done',      'INTEGER', nullable=False, default='0'),
        Column('total',     'INTEGER', nullable=False, default='0'),
        Column('error',     'TEXT', nullable=False, default="''"),
        # Which run of which process wrote it. Not used to decide anything today — a job dies
        # with the process that started it, so every `running` row found at start-up is
        # stale — but it is what would tell two panels sharing a database apart, and a column
        # added later could not be filled in for the rows that needed it.
        Column('owner',     'TEXT', nullable=False, default="''"),
        # What it did, as the lines it reported. JSON rather than a table of its own: a job's
        # log is read whole or not at all, and a second table would be a join for every row of
        # a list that does not show it.
        Column('log',       'TEXT', nullable=False, default="'[]'"),
        # …and how many lines were dropped to fit the cap. Said out loud, because a log that
        # silently stops is one nobody can trust the end of.
        Column('log_dropped', 'INTEGER', nullable=False, default='0'),
    ),
    indexes=(Index('idx_job_history_ended', ('ended_at',)),
             Index('idx_job_history_kind', ('kind',))),
)

_T = _SCHEMA.name
_COLS = ('uid', 'job_id', 'source', 'kind', 'label', 'state', 'started_at', 'ended_at',
         'done', 'total', 'error', 'owner', 'log', 'log_dropped')
_SELECT = ', '.join(_COLS)


class JobHistoryStore(BaseStore):
    """The finished jobs, newest first."""

    def __init__(self, db) -> None:
        super().__init__(db)
        self._db.reconcile_table(_SCHEMA)

    # ── Write ─────────────────────────────────────────────────────────────────
    def begin(self, job: dict, *, owner: str = '') -> str:
        """Open the row, at the moment the work starts. Returns its uid, or ``''``.

        Never raises. Failing to write the note about a job must not stop the job.
        """
        try:
            uid = str(uuid.uuid4())
            with self._db.transaction():
                self._db.execute(
                    f'INSERT INTO {_T}({_SELECT}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (uid, str(job.get('id') or ''), str(job.get('source') or ''),
                     str(job.get('kind') or ''), str(job.get('label') or ''),
                     'running',
                     float(job.get('started') or time.time()), 0.0,
                     0, int(job.get('total') or 0), '', str(owner or ''), '[]', 0))
            return uid
        except Exception:  # pylint: disable=broad-except
            return ''

    def complete(self, uid: str, job: dict, log: list | None = None, *,
                 cap: int = 200) -> bool:
        """Close a row that :meth:`begin` opened."""
        if not uid:
            return False
        try:
            lines = [str(x) for x in (log or []) if str(x or '').strip()]
            dropped = max(0, len(lines) - max(0, int(cap)))
            # The LAST lines and not the first: a log is read from the end, where whatever
            # went wrong is.
            kept = lines[dropped:] if dropped else lines
            with self._db.transaction():
                self._db.execute(
                    f'UPDATE {_T} SET state=?, ended_at=?, done=?, total=?, error=?, '
                    'label=?, log=?, log_dropped=? WHERE uid=?',
                    (str(job.get('state') or 'done'),
                     float(job.get('ended') or time.time()),
                     int(job.get('done') or 0), int(job.get('total') or 0),
                     str(job.get('error') or '')[:2000], str(job.get('label') or ''),
                     json.dumps(kept, ensure_ascii=False), dropped, str(uid)))
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def record(self, job: dict, log: list | None = None, *, cap: int = 200) -> str:
        """Open and close a row in one go — for work that was already over when it got here."""
        uid = self.begin(job)
        return uid if uid and self.complete(uid, job, log, cap=cap) else ''

    def reap(self, alive: set | None = None) -> int:
        """Close the open rows whose owner is gone. Returns how many.

        Called once as the process comes up. A job is threads in ONE process and dies with it,
        so a row still marked running belongs to a process that is not running it — and saying
        `interrupted` is the whole point: a collection halfway through a restart used to be
        visible NOWHERE, having neither ended nor appeared to begin.

        *alive* is the instance ids the service registry says are up. Given one, a row whose
        owner is on it is left alone — two panels sharing a database must not declare each
        other's work dead. Given nothing, every open row is closed, which is right for the one
        panel that is the normal case.
        """
        try:
            rows = self._db.fetchall(f'SELECT uid, owner FROM {_T} WHERE state = ?',
                                     ('running',))
            doomed = [r[0] for r in rows or ()
                      if not alive or str(r[1] or '') not in alive]
            if not doomed:
                return 0
            now = time.time()
            with self._db.transaction():
                for uid in doomed:
                    self._db.execute(
                        f'UPDATE {_T} SET state = ?, ended_at = ? WHERE uid = ?',
                        ('interrupted', now, uid))
            return len(doomed)
        except Exception:  # pylint: disable=broad-except
            return 0

    def prune(self, *, keep: int = 500, days: int = 30) -> int:
        """Forget what is past either limit. Returns how many rows went.

        Two limits and not one, because they answer different questions: *days* is how far
        back anybody looks, and *keep* is the ceiling a busy install hits inside a day.
        """
        gone = 0
        try:
            with self._db.transaction():
                if days > 0:
                    cutoff = time.time() - days * 86400
                    gone += int(self._db.execute(
                        f'DELETE FROM {_T} WHERE ended_at > 0 AND ended_at < ?',
                        (cutoff,)) or 0)
                if keep > 0:
                    rows = self._db.fetchall(
                        f'SELECT uid FROM {_T} ORDER BY ended_at DESC LIMIT -1 OFFSET ?',
                        (int(keep),))
                    for row in rows or ():
                        self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (row[0],))
                        gone += 1
        except Exception:  # pylint: disable=broad-except
            return gone
        return gone

    # ── Read ──────────────────────────────────────────────────────────────────
    def list(self, *, limit: int = 100, kind: str = '', state: str = '') -> list:
        """The finished jobs, newest first, without their logs.

        The log is left out on purpose: a hundred rows each carrying a couple of hundred
        lines is a megabyte of JSON to draw a list of names and dates.
        """
        # A row still open is the PRESENT — it is on the live list, from the memory of the
        # package running it, and having it in both places would be one job on two screens
        # disagreeing about which it belongs on.
        where, args = ["state <> 'running'"], []
        if kind:
            where.append('kind = ?')
            args.append(str(kind))
        if state:
            where.append('state = ?')
            args.append(str(state))
        sql = (f'SELECT {_SELECT} FROM {_T} WHERE ' + ' AND '.join(where)
               + ' ORDER BY ended_at DESC LIMIT ?')
        args.append(max(1, int(limit)))
        try:
            rows = self._db.fetchall(sql, tuple(args))
        except Exception:  # pylint: disable=broad-except
            return []
        return [self._row(r, with_log=False) for r in rows or ()]

    def get(self, uid: str) -> dict | None:
        """One job, with everything it said."""
        try:
            row = self._db.fetchone(f'SELECT {_SELECT} FROM {_T} WHERE uid = ?', (str(uid),))
        except Exception:  # pylint: disable=broad-except
            return None
        return self._row(row, with_log=True) if row else None

    def count(self) -> int:
        try:
            row = self._db.fetchone(f"SELECT COUNT(*) FROM {_T} WHERE state <> 'running'")
            return int(row[0]) if row else 0
        except Exception:  # pylint: disable=broad-except
            return 0

    @staticmethod
    def _row(r, with_log: bool) -> dict:
        try:
            log = json.loads(r[12]) if r[12] else []
        except (ValueError, TypeError):
            log = []
        out = {
            'uid': r[0], 'job_id': r[1], 'source': r[2], 'kind': r[3], 'label': r[4],
            'state': r[5], 'started_at': float(r[6] or 0), 'ended_at': float(r[7] or 0),
            'done': int(r[8] or 0), 'total': int(r[9] or 0), 'error': r[10] or '',
            # Which run of which process did it. `host:pid:role` — the same name the service
            # registry and the health screen call it, so it is one a person can look up.
            'owner': r[11] or '',
            'log_lines': len(log) if isinstance(log, list) else 0,
            'log_dropped': int(r[13] or 0),
        }
        if with_log:
            out['log'] = log if isinstance(log, list) else []
        return out
