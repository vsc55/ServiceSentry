#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The collection somebody pressed a button for, and is standing there watching.

A device's checks take as long as they take. The ordinary probes answer in seconds; a NAS
sampled by a full SNMP profile answers about a thousand values and takes minutes. A request
held open for that long is one a browser or a reverse proxy eventually gives up on, and the
operator is left unable to tell whether it worked — which is the same reason the backup
copies and the MIB compile are shaped this way. So the work goes on a thread and the answer
is a job id the browser polls.

**What the job knows is what the executor tells it.** The progress is per MODULE, because the
executor runs modules and that is the only boundary it can honestly report — a module is not
subdivided into steps and inventing some would be a bar that moves smoothly and means nothing.
It also means the bar is not linear in TIME: nine fast modules and one SNMP profile go to 90 %
in two seconds and stay there for four minutes. That is why the job carries which module is
running and not only a number: "snmp — running" is the sentence that makes the pause legible,
and a bar on its own would look like a hang.

**In memory on purpose.** A job is about THIS process: it dies with it, and a browser polling
a job whose process is gone gets a 404, which is the truth. Nothing about a collection is
worth persisting — what it produces is written by the checks themselves, into check state and
history, which is where it belongs and where it survives.
"""

from __future__ import annotations

import threading
import time
import uuid

#: Runs in flight and recently finished, by job id.
_JOBS: dict = {}

#: How long a finished job stays around to be asked about. Long enough that a browser which
#: was closed over lunch still gets its answer instead of a 404 that reads like a failure,
#: short enough that a panel left running for a month is not holding a hundred of them.
_KEEP_FINISHED = 30 * 60


def job_status(job_id: str) -> dict | None:
    """The job, or ``None``. The private keys (the ones starting with ``_``) never leave."""
    job = _JOBS.get(str(job_id or ''))
    if job is None:
        return None
    return {k: v for k, v in job.items() if not k.startswith('_')}


def running_job() -> dict | None:
    """The collection in flight, if there is one — for a browser that has just been reloaded.

    F5 does not stop anything: the work is a thread on the server and nothing about it depends
    on somebody watching. What a reload DOES lose is the job id, which lived in a variable in
    a page that no longer exists — so the bar and the dialog vanish while the device is still
    being polled, and the screen looks idle in the middle of a five-minute run.

    Asking "is one running" and not remembering an id in the browser, because the answer is
    the SERVER's: it is the same answer for a second tab, for a colleague's laptop, and for
    the person who closed the browser and came back. A `localStorage` copy would be one
    browser's opinion, right until the run ended somewhere else.

    At most one can be in flight — the route takes the same lock the Status screen's run takes
    — so "the" running job is a well-formed question rather than a first-of-many.
    """
    for job in _JOBS.values():
        if not job.get('done'):
            return {k: v for k, v in job.items() if not k.startswith('_')}
    return None


def _prune(now: float) -> None:
    """Forget the finished jobs nobody came back for."""
    for jid, job in list(_JOBS.items()):
        if job.get('done') and (now - job.get('_ended', now)) > _KEEP_FINISHED:
            _JOBS.pop(jid, None)


def start_collect(wa, uid: str, host_name: str, modules: list,
                  actor: str = '', ip: str = '') -> str:
    """Run *modules* in the background and hand back a job id to ask about.

    The caller has already taken ``wa._check_lock`` — taking it here would be a window in
    which two collections could both believe they were the only one. **This function releases
    it**, in the worker's ``finally``, and that asymmetry is deliberate: the lock has to be
    held from the moment the decision is made until the work is over, and the decision is made
    in the request while the work is not.

    ``actor`` and ``ip`` are read from the request and carried in, because the audit entry is
    written from a thread where there is no request to read them from. Recording it as
    ``system`` would lose the one fact the entry exists to keep — who asked.
    """
    now = time.time()
    _prune(now)
    job_id = uuid.uuid4().hex[:12]
    job = _JOBS[job_id] = {
        'id': job_id, 'host': uid, 'host_name': host_name,
        'total': len(modules), 'completed': 0,
        # One row per module, in the order they were started, each with the state it is in.
        # A list and not a dict: the screen draws it as a list, and the order a dict of
        # module names iterates in is not one anybody chose.
        'modules': [{'module': m, 'state': 'pending', 'detail': ''} for m in modules],
        'done': False, 'error': '', 'answered': [], 'errors': [],
        '_started': now, '_ended': 0.0,
    }
    index = {m: i for i, m in enumerate(modules)}

    def _progress(state: str, module: str, detail: str = '') -> None:
        """One module moved. Called from the executor's worker threads.

        No lock. Every write here is a single assignment to a dict entry or a list slot,
        which the GIL makes atomic, and the reader is a poll that is allowed to see a
        half-updated picture — it asks again in a second. A lock around this would put the
        progress display in the path of the work it is describing.
        """
        i = index.get(module)
        if i is None:
            return
        row = job['modules'][i]
        row['state'] = state
        row['detail'] = detail
        # `completed` counts modules that will not move again. A timeout is not one of them
        # in spirit — the module is still running — but it IS one for the bar, or the bar
        # stops at 90 % forever on the fleet this was written for.
        job['completed'] = sum(1 for r in job['modules']
                               if r['state'] in ('ok', 'error', 'timeout'))

    def _work():
        try:
            results, errors = wa._run_checks(
                modules, timeout=_timeout_of(wa), progress_cb=_progress)
            job['answered'] = sorted(results.keys())
            job['errors'] = list(errors or [])
        except Exception as exc:      # pylint: disable=broad-except
            job['error'] = f'{type(exc).__name__}: {exc}'[:500]
        finally:
            try:
                wa._audit_write('infra_collect', actor or 'system', ip or 'internal', {
                    'uid': uid, 'name': host_name, 'modules': modules,
                    'answered': job['answered'], 'errors': job['errors'],
                    'error': job['error'],
                })
            except Exception:         # pylint: disable=broad-except
                pass                  # an audit that fails must not lose the job's result
            try:
                wa._check_lock.release()
            except RuntimeError:      # pylint: disable=broad-except
                pass                  # already released — the run is over either way
            job['_ended'] = time.time()
            # Last, and always: `done` is what stops the browser polling, so a job that
            # raised before setting it is one the screen waits on forever.
            job['done'] = True

    threading.Thread(target=_work, daemon=True, name='ss-infra-collect').start()
    return job_id


def _timeout_of(wa) -> int:
    """How long this installation waits for one module — the operator's setting.

    Not the 45 s the Status button uses: that number is a browser's patience, and nothing is
    waiting on a request here. ``monitoring|module_timeout`` is the one home for "how long is
    a module given", which is the fleet's property and not this screen's — a rack whose NAS
    answers in five minutes needs a different answer from one whose devices answer in two
    seconds, and there is already a place to say so.

    Asked of the monitoring service rather than re-derived: the property already folds in the
    environment override and the floor, and a second reading of one setting is a second answer
    that gets to disagree with the scheduler about how long a module has.
    """
    svc = (getattr(wa, '_embedded_services', None) or {}).get('monitoring')
    try:
        return int(svc._monitoring_module_timeout)
    except Exception:                 # pylint: disable=broad-except
        # No embedded scheduler in this process (a slimmed panel, a test). The browser's
        # number is the wrong one here but it is a number, and a collection that ran with a
        # short deadline is better than one that did not run.
        from lib.services.monitoring.checks_mixin import _MODULE_CHECK_TIMEOUT  # noqa: PLC0415
        return _MODULE_CHECK_TIMEOUT
