#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The collection somebody pressed a button for, and is standing there watching.

A device's checks take as long as they take. The ordinary probes answer in seconds; a NAS
sampled by a full SNMP profile answers about a thousand values and takes minutes. A request
held open for that long is one a browser or a reverse proxy eventually gives up on, and the
operator is left unable to tell whether it worked — which is the same reason the backup
copies and the MIB compile are shaped this way. So the work goes on a thread and the answer
is a job id the browser polls.

**What the job knows is what the executor tells it.** The bar is per MODULE, because that is
the only boundary the executor can honestly measure, and it is therefore not linear in TIME:
nine fast modules and one SNMP profile go to 90 % in two seconds and stay there for four
minutes. A bar on its own would look like a hang, so the job also carries a CHECKLIST — the
phases a module names for itself while it works, each with its counter. The core names none of
them (see ``ModuleBase.report_progress``): a vocabulary of steps written here would fit
whichever module was in front of whoever wrote it and be a lie for the other twenty. What
arrives is drawn, in the order it arrives.

**A run is over when it is over.** A module that outlives the batch deadline is not finished:
it is still walking the device, and it writes its own state and history when it lands. The job
used to declare itself done at that moment anyway and warn that "some modules are still
working" — a screen announcing an ending it then has to take back, reported exactly that way.
It now stays open until the straggler reports (the executor tells it), or until ``_LATE_GRACE``
passes and it says plainly that it stopped watching.

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

#: How long a job keeps waiting for a module that overran the batch deadline, before it stops
#: watching and says so. The module is not cancelled by this — nothing can cancel it — and it
#: still writes its own state and history whenever it lands. This is only how long the SCREEN
#: is prepared to keep the run open, and it is generous because the case it exists for is a
#: NAS that answers a thousand values in five minutes.
_LATE_GRACE = 20 * 60

#: A phase reports at whatever rate the module chooses. This is the ceiling on how many lines
#: one module may fill, so a module working on forty machines cannot grow the polled answer
#: without bound. Over the cap, a line that has FINISHED is dropped to make room — the list is
#: a window on what is happening now, and the module's own row carries the summary. With
#: nothing finished to drop, the last line keeps updating rather than the list growing.
_MAX_STEPS = 10


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
                  actor: str = '', ip: str = '', lang: str = '') -> str:
    """Run *modules* in the background and hand back a job id to ask about.

    The caller has already taken ``wa._check_lock`` — taking it here would be a window in
    which two collections could both believe they were the only one. **This function releases
    it**, in the worker's ``finally``, and that asymmetry is deliberate: the lock has to be
    held from the moment the decision is made until the work is over, and the decision is made
    in the request while the work is not.

    ``actor`` and ``ip`` are read from the request and carried in, because the audit entry is
    written from a thread where there is no request to read them from. Recording it as
    ``system`` would lose the one fact the entry exists to keep — who asked.

    ``lang`` travels for the same reason and is the same kind of fact: the words a module
    writes into the checklist are read by the person who pressed the button, and a worker
    thread has no session to ask which language that is.
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
        # `awaiting`: the batch is over and a module is still out. `gave_up`: it was still
        # out when the panel stopped waiting — the one case where "it carries on in the
        # background" is a true thing to say rather than an excuse for ending early.
        'done': False, 'awaiting': False, 'gave_up': False,
        'error': '', 'answered': [], 'errors': [],
        '_started': now, '_ended': 0.0,
        # The history row, opened NOW: a collection interrupted by a restart never reaches
        # `_finish`, and a note written only at the end is the note that machine never gets.
        '_hist': '',
    }
    index = {m: i for i, m in enumerate(modules)}

    def _progress(state: str, module: str, detail: str = '',
                  extra: dict | None = None) -> None:
        """One module moved. Called from the executor's worker threads.

        No lock. Every write here is a single assignment to a dict entry or a list slot,
        which the GIL makes atomic, and the reader is a poll that is allowed to see a
        half-updated picture — it asks again in a second. A lock around this would put the
        progress display in the path of the work it is describing.
        """
        i = index.get(module)
        if i is None or job.get('done'):
            return               # a finished job takes no more reports, ever
        row = job['modules'][i]
        # A module that overran keeps reporting — it is still working — and those reports are
        # what keeps the checklist moving while the job waits for it. What they must NOT do is
        # take the row back out of `timeout`: that state is what says "still out", and losing
        # it would end the run the moment the straggler said anything.
        if not (row['state'] == 'timeout' and state == 'running'):
            row['state'] = state
        row['detail'] = detail
        _step(row, state, detail, extra)
        # `completed` counts modules that have SAID how they ended. A timeout has not: the
        # module is still walking the device. It used to be counted anyway, so the bar would
        # not stop short — and the result was "100 %" over the words "one module is still
        # working", which is the screen contradicting itself in one glance. The bar stopping
        # short is not a problem now that the run waits for the straggler and the line turns
        # into a tick on its own; and if the panel does give up, a bar that never reached the
        # end is the honest picture of what happened.
        job['completed'] = sum(1 for r in job['modules']
                               if r['state'] in ('ok', 'error'))
        # A straggler landing is what ends a run that overran: the batch returned minutes
        # ago and this is the only place that hears about it.
        if job.get('_awaiting') and not _still_out(job):
            _finish(job)

    def _work():
        try:
            # `only_host`: this is a collection OF A DEVICE. It used to run each module
            # with its whole configuration — so asking for one NAS walked every other machine
            # that module watches, which on an SNMP fleet is minutes of other people's
            # equipment and, when one of them is not answering, a run that never lands.
            # Reported from the screen as a dialog stuck on "still working" with six devices
            # in it, only one of which had been asked about.
            results, errors = wa._run_checks(
                modules, timeout=_timeout_of(wa), progress_cb=_progress, lang=lang,
                only_host=uid)
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
            # A module that overran is still working, and saying "finished" over the top
            # of it is the screen announcing something it has to take back — reported
            # exactly that way: a run that ends with a warning while the device is still
            # being walked. So the job stays open until the straggler lands (the executor
            # calls `_progress` again when it does) or until the panel gives up waiting.
            if job['error'] or not _still_out(job):
                _finish(job)
            else:
                job['awaiting'] = True
                job['_awaiting'] = True
                timer = threading.Timer(_LATE_GRACE, lambda: _finish(job, gave_up=True))
                timer.daemon = True
                timer.start()

    # The history row, opened before the work does. A collection interrupted by a
    # restart never reaches `_finish`, and a note written only at the end is the note
    # that machine never gets — it did not end and it did not appear to have started.
    from lib.core.jobs import record as _record         # noqa: PLC0415
    job['_hist'] = _record.start({
        'id': job_id, 'kind': 'collect', 'source': 'infra',
        'label': host_name, 'started': now, 'total': len(modules)})
    threading.Thread(target=_work, daemon=True, name='ss-infra-collect').start()
    return job_id


def _still_out(job: dict) -> bool:
    """Whether any module of *job* is known to be still working.

    `timeout` and only `timeout`. That state is the executor saying "this one overran its
    deadline and is still going", which is a specific claim about a live thread. A row left
    `pending` or `running` when the batch returns is not a straggler — the executor reports
    every module it starts, one way or the other — so treating those as "still out" would
    hang the job for the whole grace period on a run where something else went wrong.
    """
    return any(r.get('state') == 'timeout' for r in job.get('modules') or ())


def _finish(job: dict, gave_up: bool = False) -> None:
    """Close the job. Idempotent on purpose: the straggler and the watchdog race."""
    if job.get('done'):
        return
    job['awaiting'] = False
    job['_awaiting'] = False
    job['gave_up'] = bool(gave_up)
    job['_ended'] = time.time()
    # Last, and always: `done` is what stops the browser polling, so a job that raised
    # before setting it is one the screen waits on forever.
    job['done'] = True
    _archive(job)


def _archive(job: dict) -> None:
    """Close the note about what this collection did.

    Here and not from the screen: these are pruned from memory half an hour after they end,
    so archiving when somebody happens to look would mean a collection nobody opened is one
    that never happened. The row itself was opened when the collection started.
    """
    from lib.core.jobs import record as _record       # noqa: PLC0415
    rows = job.get('modules') or []
    done = len([r for r in rows if r.get('state') in ('done', 'failed', 'timeout')])
    bad = [r for r in rows if r.get('state') in ('failed', 'timeout')]
    _record.finish(job.get('_hist') or '', {
        'id': job.get('id') or '', 'kind': 'collect', 'source': 'infra',
        'label': str(job.get('host_name') or ''),
        'state': 'failed' if (job.get('error') or bad) else 'done',
        'started': float(job.get('_started') or 0),
        'ended': float(job.get('_ended') or time.time()),
        'done': done, 'total': len(rows), 'error': str(job.get('error') or ''),
    }, _log_of(job))


def _log_of(job: dict) -> list:
    """What the collection said, one line per step of every module.

    Every step and not a summary: "which module was it on when it stopped" and "what did the
    one that timed out actually get through" are the questions afterwards, and a summary
    answers neither. The cap that keeps this from filling a database is the installation's
    (`web_admin|jobs_history_lines`) and is applied where it is written.
    """
    out = []
    for row in job.get('modules') or ():
        name = str(row.get('label') or row.get('module') or '')
        state = str(row.get('state') or '')
        for step in row.get('steps') or ():
            detail = str((step or {}).get('detail') or (step or {}).get('step') or '')
            scope = str((step or {}).get('scope') or '')
            out.append(' · '.join(x for x in (name, scope, detail) if x))
        if not (row.get('steps') or ()):
            out.append(f'{name} · {state}')
    return out


def _step(row: dict, state: str, detail: str, extra: dict | None) -> None:
    """Fold one report into the module's checklist.

    A line is identified by the THING it is about and the WORDS the module used for the phase,
    because those two are all there is: the core names no steps (see
    ``ModuleBase.report_progress``). Repeating a phase for the same thing keeps its line and
    moves its counter — twenty-four profiles are one line reading "3/24", not twenty-four
    lines — while a second machine gets a line of its own, which is the whole point: this
    module samples its devices in a pool, and one shared line was four threads overwriting
    each other's counter.
    """
    if state in ('ok', 'error', 'timeout'):
        for st in row.get('steps') or ():
            if st['state'] != 'run':
                continue
            if state == 'timeout':
                continue                     # still working: leave the line as it is
            st['state'] = 'done' if state == 'ok' else 'fail'
            # …and the counter goes. It measured progress and progress is over; a module that
            # stopped reporting where it did would otherwise leave "3/24" beside a green tick,
            # which is a number that means nothing and reads as a run that lost its place.
            st['n'] = st['total'] = 0
        return
    name = str((extra or {}).get('step') or '').strip()[:80]
    if not name:
        return
    scope = str((extra or {}).get('scope') or '').strip()[:80]
    # The module saying how this phase ENDED. Before it, a phase ended only when the same
    # scope started another one — so the last phase of every device spun for ever, at N/N,
    # minutes after it had finished, and a device that answered nothing looked identical to
    # one still working. Reported from the screen as both.
    ended = str((extra or {}).get('state') or '').strip()
    if ended in ('done', 'fail'):
        for st in row.get('steps') or ():
            if st['state'] == 'run' and st.get('scope', '') == scope \
                    and (st['key'] == name or not name):
                st['state'] = ended
                st['n'] = st['total'] = 0
        return
    steps = row.setdefault('steps', [])
    cur = next((s for s in steps if s['key'] == name and s.get('scope', '') == scope), None)
    if cur is None:
        if len(steps) >= _MAX_STEPS:
            # Room is made by forgetting something that has ENDED, oldest first. Only if
            # nothing has: a list of forty machines all mid-walk keeps its last line moving
            # rather than growing, and the module's own row still says how the run is going.
            spare = next((s for s in steps if s['state'] != 'run'), None)
            if spare is not None:
                steps.remove(spare)
                cur = None
            else:
                cur = steps[-1]
        if cur is None and len(steps) < _MAX_STEPS:
            # The previous phase OF THE SAME THING ended when this one began. Another
            # machine's line is none of this one's business.
            for st in steps:
                if st['state'] == 'run' and st.get('scope', '') == scope:
                    st['state'] = 'done'
                    st['n'] = st['total'] = 0
            cur = {'key': name, 'scope': scope, 'state': 'run', 'n': 0, 'total': 0, 'note': ''}
            steps.append(cur)
    cur['key'] = name
    cur['scope'] = scope
    cur['state'] = 'run'
    cur['n'] = int((extra or {}).get('n') or 0)
    cur['total'] = int((extra or {}).get('total') or 0)
    cur['note'] = str(detail or '')[:200]


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

def live(_wa) -> list:
    """What this package is running now, for the background-jobs screen.

    Declared in the manifest (`BACKGROUND_JOBS`) rather than the screen reaching in here: a
    core that imported four job registries by name would be a core that has to be edited to
    learn about a fifth.

    Finished ones travel too, for as long as this module keeps them (`_KEEP_FINISHED`) — a
    collection that ended two minutes ago is exactly what somebody who looked away came back
    to find out about.
    """
    now = time.time()
    out = []
    for jid, job in list(_JOBS.items()):
        rows = job.get('modules') or []
        # `timeout` is NOT one of these. It means the batch's deadline passed and the module
        # is still working — it keeps reporting, and this screen keeps showing it. Counting it
        # as finished put the bar at 1/1 under the words "running", which is the jobs screen
        # contradicting the collection screen about the same module at the same moment.
        done = len([r for r in rows if r.get('state') in ('done', 'failed')])
        out.append({
            'id': jid,
            'kind': 'collect',
            'label': str(job.get('host_name') or ''),
            'detail': _live_detail(rows),
            'state': ('done' if not job.get('error') else 'failed') if job.get('done')
                     else 'running',
            'started': float(job.get('_started') or job.get('started') or now),
            'done': done, 'total': len(rows),
            'error': str(job.get('error') or ''),
            'steps': _live_steps(rows),
        })
    return out


#: A module's state, as the words the jobs screen colours. Its own vocabulary does not
#: travel — a screen cannot colour a word it has never heard of.
#:
#: `timeout` is NOT a failure. Reported from the screen: a switch's collection showed the SNMP
#: module in red on the jobs list while the collection dialog, at that same moment, said "still
#: working" — and the collection dialog was right. The batch's deadline passed; the module did
#: not stop, and nothing here can stop it. It is still running, and it is drawn as what it is.
#: What it means at the END is a different question, and `_archive` answers that one.
_LIVE_STATE = {'pending': 'pending', 'running': 'running', 'done': 'ok',
               'failed': 'failed', 'timeout': 'running'}


#: A step's own state, as the words the jobs screen colours. `timeout` is `running` here for
#: the same reason it is on a module: the deadline passed and the work did not stop.
_STEP_STATE = {'run': 'running', 'ok': 'ok', 'error': 'failed', 'timeout': 'running'}


def _live_steps(rows: list) -> list:
    """The checklist behind the one line a list row has room for.

    The SAME lines the collection dialog draws, with the same columns: which device, what is
    being done to it, and how far through. Reported from the screen — the jobs dialog showed
    "0 / 1  0 %" and a single red word while the collection dialog, at that moment, was
    listing five machines and what each was reading.
    """
    out = []
    for row in rows or ():
        state = str(row.get('state') or '')
        out.append({'state': _LIVE_STATE.get(state, ''),
                    'text': str(row.get('label') or row.get('module') or ''),
                    'note': str(row.get('detail') or '')})
        if state not in ('running', 'timeout'):
            continue
        for step in row.get('steps') or ():
            text = str((step or {}).get('key') or '')
            if not text:
                continue
            out.append({
                'state': _STEP_STATE.get(str((step or {}).get('state') or ''), 'running'),
                'text': text,
                # The device this step is about. Its own column, because forty steps of one
                # module differ by exactly this and nothing else.
                'scope': str((step or {}).get('scope') or ''),
                'n': (step or {}).get('n') or 0, 'total': (step or {}).get('total') or 0,
                'note': str((step or {}).get('note') or ''),
                'sub': True,
            })
    return out


def _live_detail(rows: list) -> str:
    """The module that is working, and what it said it was doing — one line.

    The row that is RUNNING, because that is the answer to "what is it doing"; with none
    running the job is between modules or over, and a stale step would read as current.
    """
    for row in rows or ():
        if row.get('state') == 'running':
            step = str(row.get('step') or '').strip()
            name = str(row.get('label') or row.get('module') or '')
            return f'{name} — {step}' if step else name
    return ''
