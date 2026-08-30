#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The copies and restores somebody is standing there waiting for.

Every one of these takes minutes — the syslog table alone is six figures of rows — and a
request held open for that long is one a browser or a reverse proxy eventually gives up on,
leaving the operator unable to tell whether it worked. So the work goes on a thread and the
answer is a job id the browser polls.

ONE shape for all three: a hand-made copy, a scheduled task run by hand, and a restore differ
in what they are named and who is told about them, not in how long they take.

Split from `runner.py`, which is about WHEN a copy is due — a thread, a tick and a lease.
Nothing here is scheduled: it all starts because somebody pressed a button. The mixin needs
`run_now` from the class that inherits it, which is where the schedule's own path lives.
"""

from __future__ import annotations

import threading
import time
import uuid

from lib import __version__
from lib.core.backup import create as _create
from lib.core.backup import parts as _parts
from lib.core.backup import restore as _restore
from lib.core.backup.archive import _log
from lib.debug.debug_level import DebugLevel

# Runs started from the UI, by job id. In memory on purpose: a job is about THIS
# process — it dies with it, and a browser polling a job whose process is gone gets
# a 404, which is the truth.
_JOBS: dict = {}


def _connectors(wa) -> dict:
    """The databases a copy has to reach beyond the system one.

    Only `syslog` today, and only when `syslog_db|enabled` actually sent that feed somewhere
    else — with it off the web admin hands back the main connector for both, and a map that
    named it anyway would be true but noisy. Built HERE and not in the service, which is
    Flask-free and is given its connectors rather than going looking for them.
    """
    main = getattr(wa, '_db_connector', None)
    syslog = getattr(wa, '_syslog_db_connector', None)
    return {'syslog': syslog} if (syslog is not None and syslog is not main) else {}


def job_status(job_id: str) -> dict | None:
    return _JOBS.get(str(job_id or ''))


class _JobsMixin:
    """What `BackupRunner` does when a person asks for it now.

    A mixin and not a class of its own because the three entry points need the runner's own
    `run_now` (a scheduled task run by hand has to go through the schedule's path, or it would
    produce a copy the task does not own) and its `_wa`.
    """

    def _start_job(self, label: str, work, manual: bool = False,
                   kind: str = 'backup') -> str:
        """Begin a copy in the background and hand back a job id to ask about.

        A copy of a large install takes minutes — the syslog table alone is six figures of rows
        — and a request that holds the connection for that long is one the browser or a reverse
        proxy eventually gives up on, leaving the operator with no idea whether it worked.

        The job dict is the same shape the MIB compile already uses, so the browser's polling
        loop is a shape this panel already has. ONE shape for both kinds of copy, too: a manual
        one and a scheduled one differ in what they are named and who is told about them, not in
        how long they take — and a hand-made copy that showed nothing until it finished was
        exactly the complaint that made the scheduled one report at all.
        """
        job_id = uuid.uuid4().hex[:12]
        job = _JOBS[job_id] = {
            # When it began. Private (a leading underscore) like every other working
            # key here: it is for the jobs screen to say "running for 4 min", not part
            # of what this job's own poller answers.
            '_started': time.time(),
            'done': False, 'task': label, 'manual': bool(manual), 'kind': kind,
            'table': '', 'step': 0, 'total': 0, 'created': '', 'error': '',
            # Per-part outcome, filled in as the copy goes. The bar says how far;
            # this says what actually made it, which is the question afterwards.
            'steps': [], 'status': '',
        }

        def _work():
            _log(f'> Backup > job {job_id} >> {kind} {label!r} started')
            try:
                work(job)
            except Exception as exc:      # pylint: disable=broad-except
                job['error'] = str(exc)[:500]
                _log(f'> Backup > job {job_id} >> {kind} {label!r} raised: {exc}',
                     DebugLevel.error)
            finally:
                _log(f'> Backup > job {job_id} >> {kind} {label!r} finished'
                     + (f' with an error: {job["error"]}' if job['error'] else ''),
                     DebugLevel.warning if job['error'] else DebugLevel.info)
                # Last, and always: `done` is what stops the browser polling, so a job that
                # raised before setting it is one the screen waits on for an hour.
                job['done'] = True
                # …and the note about it, for the history. In the `finally` with `done`, so
                # a copy that raised is filed exactly like one that did not: the row saying
                # it failed is the one somebody comes looking for.
                from lib.core.jobs import record as _record       # noqa: PLC0415
                _record.record({
                    'id': job_id, 'kind': str(job.get('kind') or 'backup'),
                    'source': 'backup', 'label': str(job.get('task') or ''),
                    'state': 'failed' if job.get('error') else 'done',
                    'started': float(job.get('_started') or 0), 'ended': time.time(),
                    'done': int(job.get('step') or 0), 'total': int(job.get('total') or 0),
                    'error': str(job.get('error') or ''),
                }, [_step_line(s) for s in (job.get('steps') or ())])

        threading.Thread(target=_work, daemon=True, name='ss-backup-run').start()
        return job_id

    def start_run(self, task: dict) -> str:
        """Start a scheduled task's copy in the background."""
        def _work(job):
            out = self.run_now(task, progress_cb=job.update)
            job.update({'created': (out['created'] or [''])[0], 'pruned': out['pruned'],
                        'status': out.get('status', '')})

        return self._start_job(task.get('name', ''), _work)

    def start_manual(self, name: str, parts, include_secrets: bool,
                     actor: str, ip: str) -> str:
        """Start a copy asked for by hand, with the parts the form chose.

        Not `run_now`: there is no task, so there is no `auto-<task>-` name and no retention to
        apply afterwards — a hand-made copy belongs to the person who made it and is deleted by
        them.

        `actor` and `ip` are read from the request and carried in, because the work happens on a
        thread where there is none. Auditing it as `system` would be losing the one fact this
        line exists to record.
        """
        wa = self._wa

        def _work(job):
            res = _create.create_backup(
                wa._db_connector, name,
                var_dir=wa._var_dir or '', config_dir=getattr(wa, '_config_dir', '') or '',
                backup_dir=str(getattr(wa, '_BACKUP_DIR', '') or ''),
                parts=list(parts or []), include_secrets=bool(include_secrets),
                actor=actor, app_version=__version__, progress_cb=job.update,
                engine=str(getattr(wa._db_connector, 'driver', '') or ''),
                connectors=_connectors(wa), dirs=_parts.configured_dirs(wa),
            )
            if not res.get('ok'):
                job['error'] = str(res.get('message', ''))[:500]
                wa._audit_write('backup_created', actor, ip,
                                {'name': name, 'ok': False, 'message': job['error']})
                return
            man = res['manifest']
            job.update({'created': name, 'status': man.get('status', 'ok'),
                        'steps': man.get('steps', [])})
            wa._audit_write('backup_created', actor, ip, {
                'name': name, 'parts': man.get('parts', []), 'secrets': man.get('secrets'),
                'tables': man.get('tables', {}), 'size': man.get('size', 0),
                'status': man.get('status', 'ok'),
            })

        return self._start_job(name, _work, manual=True)

    def start_restore(self, name: str, parts, actor: str, ip: str,
                      after=None, tables=None) -> str:
        """Put a copy back in the background, reporting which table it is on.

        The same treatment the copies get, and for a stronger reason: a restore rewrites every
        table in one transaction, so it is the longest thing this section does — and the one
        where a screen that says nothing is most alarming, because what it is silent about is
        the install being overwritten.

        `after` is run once it has worked: the caches this process holds describe rows that no
        longer exist. Passed in rather than reached for, because what needs dropping is the web
        admin's business and this file is not the place that knows it.

        `tables` is the advanced half of the form: named tables inside the chosen parts, or None
        for all of them. It travels as it arrived — the service decides what an empty list means
        (nothing), and a second opinion here is a second thing to keep in step.
        """
        wa = self._wa

        def _work(job):
            res = _restore.restore_backup(
                wa._db_connector, wa._var_dir or '', name,
                parts=parts if isinstance(parts, list) else None,
                tables=tables if isinstance(tables, list) else None,
                config_dir=getattr(wa, '_config_dir', '') or '',
                backup_dir=str(getattr(wa, '_BACKUP_DIR', '') or ''),
                progress_cb=job.update, connectors=_connectors(wa),
                dirs=_parts.configured_dirs(wa),
            )
            job.update({'tables': res.get('tables', {}), 'skipped': res.get('skipped', {}),
                        # So the dialog can say "these tables, the rest left as they are"
                        # instead of a row count that reads as the whole install coming back.
                        'partial': bool(res.get('partial')),
                        # The final word on the checklist. It was being filled in as the
                        # restore went, but a run that failed leaves it half written and the
                        # answer is the one the function returned.
                        'steps': res.get('steps', []),
                        'from_version': res.get('app_version', '')})
            if not res.get('ok'):
                job['error'] = str(res.get('message', ''))[:500]
            # Audited either way, with the actor read in the request: a restore that failed
            # half way is the most important line in the log, not the least.
            wa._audit_write('backup_restored', actor, ip, {
                'name': name, 'ok': bool(res.get('ok')),
                'parts': sorted(parts) if isinstance(parts, list) else 'all',
                # WHICH tables were asked for, beside how many rows each took. The rowcounts
                # say what came back; only this says what was deliberately left alone, and
                # "why is half this install older than the other half" is asked months later.
                'only_tables': sorted(tables) if isinstance(tables, list) else 'all',
                'tables': res.get('tables', {}),
                # Which build made the copy, and what this schema could not take from it. In
                # the LOG and not only in the answer on screen: a restore is the moment nobody
                # is looking ten minutes later, and "which columns went" is exactly the
                # question that gets asked months afterwards.
                'from_version': res.get('app_version', ''),
                'skipped': res.get('skipped', {}),
                'message': res.get('message', ''),
            })
            if res.get('ok') and after:
                after()

        return self._start_job(name, _work, manual=True, kind='restore')

def live(_wa) -> list:
    """What this package is running now, for the background-jobs screen."""
    out = []
    for jid, job in list(_JOBS.items()):
        out.append({
            'id': jid,
            'kind': str(job.get('kind') or 'backup'),
            'label': str(job.get('task') or ''),
            'detail': str(job.get('table') or job.get('status') or ''),
            'state': ('failed' if job.get('error') else 'done') if job.get('done')
                     else 'running',
            'started': float(job.get('_started') or 0),
            'done': int(job.get('step') or 0), 'total': int(job.get('total') or 0),
            'error': str(job.get('error') or ''),
            # Per-part outcome, which is what this job already keeps: the bar says how far,
            # this says what actually made it — the question afterwards.
            'steps': [_step_row(x) for x in (job.get('steps') or ())],
        })
    return out


#: What one part of a copy came out as, for the screens that show it. A step is a dict this
#: package composes (`{'part', 'ok', 'tables', 'rows', 'error'}`) and only this package knows
#: what those fields mean — handed over raw it reached the jobs screen as a printed Python
#: dict, which is what the reader actually saw. Reported exactly that way.
def _step_row(step) -> dict:
    """One part, in the columns the jobs screen draws."""
    if not isinstance(step, dict):
        return {'state': '', 'text': str(step or '')}
    return {'state': 'ok' if step.get('ok') else 'failed',
            'text': str(step.get('part') or ''),
            'note': _step_note(step),
            'sub': True}


def _step_line(step) -> str:
    """…and the same thing as one line, for the history, which keeps text."""
    if not isinstance(step, dict):
        return str(step or '')
    mark = 'ok' if step.get('ok') else 'ERROR'
    note = _step_note(step)
    return f"{step.get('part') or ''} — {mark}" + (f' · {note}' if note else '')


def _step_note(step: dict) -> str:
    """The counts, and the reason where there is one. Nothing that is zero: a part with no
    tables is not a part with "0 tables", it is a part that is not made of tables."""
    bits = []
    if step.get('tables'):
        bits.append(f"{step['tables']} tables")
    if step.get('rows'):
        bits.append(f"{step['rows']} rows")
    if step.get('error'):
        bits.append(str(step['error'])[:200])
    return ' · '.join(bits)
