#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The collection somebody pressed a button for, watched from outside.

Asking a device for fresh numbers takes as long as the device takes. The ordinary probes
answer in seconds; a NAS with a full SNMP profile answers about a thousand values and takes
minutes. So the work goes on a thread and the browser polls a job — and everything that can
go wrong with that shape is invisible until somebody is standing in front of it:

* a job that never sets ``done`` is a dialog that spins forever;
* a job that does not release the check lock is a panel where nothing can be run again —
  including the scheduler's own cycle, which takes the same lock;
* a job that writes the audit entry as ``system`` has lost the one fact it exists to keep;
* and a job that hands its internal bookkeeping to the browser is an API that grows a field
  nobody meant to publish.

No Flask, no database, no device: the job is handed a ``wa`` and calls two methods on it, so
the whole shape is testable with a fake that records what it was asked.
"""

import threading
import time

from lib.core.infra import jobs


class _WA:
    """The four things the job touches on its host, and nothing else."""

    def __init__(self, behaviour=None, timeout_seen=None):
        self._check_lock = threading.Lock()
        self._embedded_services = {}
        self.audited = []
        self.lang_seen = []
        self.scope_seen = []
        self._behaviour = behaviour or (lambda mods, cb: ({m: {} for m in mods}, []))
        self._timeout_seen = timeout_seen if timeout_seen is not None else []

    def _run_checks(self, mods, *, timeout, progress_cb, lang='', only_host=''):
        self._timeout_seen.append(timeout)
        self.lang_seen.append(lang)
        self.scope_seen.append(only_host)
        return self._behaviour(mods, progress_cb)

    def _audit_write(self, event, user, ip, detail):
        self.audited.append({'event': event, 'user': user, 'ip': ip, 'detail': detail})


def _start(wa, uid='u1', name='erebor', modules=('ping',), actor='javier', ip='10.0.0.2',
           lang='es_ES'):
    """Start a job with the lock held, exactly as the route does."""
    assert wa._check_lock.acquire(blocking=False)
    return jobs.start_collect(wa, uid, name, list(modules), actor=actor, ip=ip, lang=lang)


def _until(job_id, cond, wait=5.0):
    """The job once *cond* holds. Polled, because the work is on a thread of its own."""
    deadline = time.time() + wait
    while time.time() < deadline:
        job = jobs.job_status(job_id)
        if job and cond(job):
            return job
        time.sleep(0.02)
    raise AssertionError(f'never happened: {jobs.job_status(job_id)}')


def _finish(wa, uid='u1', name='erebor', modules=('ping',), actor='javier', ip='10.0.0.2',
            wait=5.0):
    """Start a job and wait for it to end."""
    job_id = _start(wa, uid, name, modules, actor, ip)
    return job_id, _until(job_id, lambda j: j['done'], wait=wait)


class TestItReportsWhileItRuns:

    def test_the_modules_start_as_pending_and_the_bar_at_zero(self):
        """Drawn before the first module has answered. A dialog that opens empty makes the
        first seconds of a five-minute run look like nothing happened."""
        started = threading.Event()
        release = threading.Event()

        def slow(mods, _cb):
            started.set()
            release.wait(5)
            return {m: {} for m in mods}, []

        wa = _WA(behaviour=slow)
        assert wa._check_lock.acquire(blocking=False)
        job_id = jobs.start_collect(wa, 'u1', 'erebor', ['ping', 'snmp'])
        assert started.wait(5)
        job = jobs.job_status(job_id)
        assert job['total'] == 2 and job['completed'] == 0
        assert [m['state'] for m in job['modules']] == ['pending', 'pending']
        release.set()

    def test_each_module_moves_the_count(self):
        """Read from OUTSIDE, one module at a time — which is what the browser does. The
        worker stops after each one until the test has looked, so the counts are the real
        sequence and not whatever the scheduler happened to interleave."""
        stepped, go = threading.Event(), threading.Event()

        def stepwise(mods, cb):
            for m in mods:
                cb('running', m)
                cb('ok', m, '3')
                go.clear()
                stepped.set()
                go.wait(5)
            return {m: {} for m in mods}, []

        wa = _WA(behaviour=stepwise)
        assert wa._check_lock.acquire(blocking=False)
        job_id = jobs.start_collect(wa, 'u1', 'erebor', ['a', 'b', 'c'])
        seen = []
        for _ in range(3):
            assert stepped.wait(5)
            stepped.clear()
            seen.append(jobs.job_status(job_id)['completed'])
            go.set()
        assert seen == [1, 2, 3], seen

    def test_a_module_the_job_never_heard_of_is_ignored(self):
        """The executor reports by module name. One that is not in this job's list is not a
        crash in a worker thread — it is a row that does not exist, and skipping it is the
        whole handling."""
        def stray(mods, cb):
            cb('ok', 'not-in-this-job', '1')
            return {m: {} for m in mods}, []

        _job_id, job = _finish(_WA(behaviour=stray), modules=('ping',))
        assert [m['module'] for m in job['modules']] == ['ping']

    def test_a_timeout_does_not_count_as_finished(self):
        """Reported from the screen: "100 %" over the words "one module is still working" —
        the same box contradicting itself in one glance. A module that overran has not said
        how it ended, so it is not counted; the bar reaches the end when the run does."""
        jid = _start(_WA(behaviour=_late), modules=('snmp',))
        job = _until(jid, lambda j: j['modules'][0]['state'] == 'timeout')
        assert job['completed'] == 0

    def test_the_watchers_language_is_carried_to_the_module(self):
        """The words a module writes into the checklist are read by the person who pressed the
        button. A worker thread has no session to ask, so the route reads it while there is
        still a request and it travels with the job — otherwise the module answers in the
        installation's NOTIFICATION language, which is how a Spanish dialog came to say
        "Reading the metrics"."""
        wa = _WA()
        _jid, _job = _finish(wa, modules=('snmp',))
        assert wa.lang_seen == ['es_ES']

    def test_a_module_reports_the_phases_it_names_for_itself(self):
        """The core names no steps: what arrives is drawn, in the order it arrives. A phase
        is identified by its WORDS, so reporting the same one again moves its counter instead
        of adding a line — twenty-four profiles are one line reading 7/24, not twenty-four."""
        def phased(mods, cb):
            cb('running', mods[0], 'nas', {'step': 'Resolviendo', 'n': 0, 'total': 0})
            cb('running', mods[0], 'nas — discos', {'step': 'Leyendo', 'n': 1, 'total': 24})
            cb('running', mods[0], 'nas — sistema', {'step': 'Leyendo', 'n': 7, 'total': 24})
            cb('ok', mods[0], '900')
            return {m: {} for m in mods}, []

        _jid, job = _finish(_WA(behaviour=phased), modules=('snmp',))
        steps = job['modules'][0]['steps']
        assert [x['key'] for x in steps] == ['Resolviendo', 'Leyendo'], steps
        assert steps[1]['note'] == 'nas — sistema'
        assert [x['state'] for x in steps] == ['done', 'done'], (
            'a phase left running under a module that finished is a spinner that never stops')
        assert (steps[1]['n'], steps[1]['total']) == (0, 0), (
            'a finished phase kept its counter — "3/24" beside a green tick is a number that '
            'means nothing, and it is what a run looks like when it lost its place')

    def test_two_things_at_once_get_a_line_each(self):
        """The bug this exists for. A module that works on several machines in a pool was
        writing all their progress into one line, because the line was identified by the
        phase alone: the counter jumped between machines and froze at whatever the last
        thread wrote. Reported as a finished run showing "3/24" of a device nobody asked
        about."""
        def pooled(mods, cb):
            cb('running', mods[0], 'sistema', {'step': 'Leyendo', 'scope': 'isen',
                                               'n': 3, 'total': 24})
            cb('running', mods[0], 'discos', {'step': 'Leyendo', 'scope': 'erebor',
                                              'n': 7, 'total': 24})
            cb('running', mods[0], 'SMART', {'step': 'Leyendo', 'scope': 'isen',
                                             'n': 4, 'total': 24})
            return {m: {} for m in mods}, []

        _jid, job = _finish(_WA(behaviour=pooled), modules=('snmp',))
        steps = job['modules'][0]['steps']
        assert [(x['scope'], x['note']) for x in steps] == [
            ('isen', 'SMART'), ('erebor', 'discos')], steps

    def test_a_phase_ending_does_not_close_another_machines(self):
        """Each machine's phases follow each other; another machine's line is none of their
        business, and closing it would tick a device that is still working."""
        def pooled(mods, cb):
            cb('running', mods[0], '', {'step': 'Resolviendo', 'scope': 'isen'})
            cb('running', mods[0], '', {'step': 'Resolviendo', 'scope': 'erebor'})
            cb('running', mods[0], '', {'step': 'Leyendo', 'scope': 'isen', 'n': 1, 'total': 9})
            return {m: {} for m in mods}, []

        jid = _start(_WA(behaviour=pooled), modules=('snmp',))
        job = _until(jid, lambda j: len(j['modules'][0].get('steps') or []) == 3)
        by = {(x['scope'], x['key']): x['state'] for x in job['modules'][0]['steps']}
        assert by[('isen', 'Resolviendo')] == 'done'
        assert by[('erebor', 'Resolviendo')] == 'run', 'the other machine was ticked off'

    def test_room_is_made_by_forgetting_something_that_ended(self):
        """A fleet of forty machines must not grow the polled answer without bound. The list
        is a window on what is happening now — so a finished line makes way, oldest first, and
        the module's own row still carries the summary."""
        def fleet(mods, cb):
            for i in range(jobs._MAX_STEPS + 5):
                cb('running', mods[0], '', {'step': 'Leyendo', 'scope': f'nas{i}',
                                            'n': 1, 'total': 2})
                cb('running', mods[0], '', {'step': 'Hecho', 'scope': f'nas{i}'})
            return {m: {} for m in mods}, []

        _jid, job = _finish(_WA(behaviour=fleet), modules=('snmp',))
        steps = job['modules'][0]['steps']
        assert len(steps) <= jobs._MAX_STEPS
        assert steps[-1]['scope'] == f'nas{jobs._MAX_STEPS + 4}', steps[-1]

    def test_a_phase_of_a_module_that_failed_reads_as_failed(self):
        def broke(mods, cb):
            cb('running', mods[0], '', {'step': 'Leyendo', 'n': 1, 'total': 9})
            cb('error', mods[0], 'no route to host')
            return {}, ['snmp: no route to host']

        _jid, job = _finish(_WA(behaviour=broke), modules=('snmp',))
        assert job['modules'][0]['steps'][0]['state'] == 'fail'

    def test_a_module_naming_a_phase_per_item_cannot_grow_the_payload(self):
        """A checklist is a handful of lines. A module reporting a new phase per row would
        make the polled answer grow all run, so past the cap the last line keeps moving."""
        def chatty(mods, cb):
            for i in range(40):
                cb('running', mods[0], '', {'step': f'paso {i}', 'n': i, 'total': 40})
            cb('ok', mods[0], '1')
            return {m: {} for m in mods}, []

        _jid, job = _finish(_WA(behaviour=chatty), modules=('snmp',))
        steps = job['modules'][0]['steps']
        assert len(steps) == jobs._MAX_STEPS
        assert steps[-1]['key'] == 'paso 39', 'the last line stopped following the module'

    def test_a_report_with_no_phase_is_still_a_sentence(self):
        """Most modules take a second and say nothing about phases. Their line is the module,
        and the sentence they do send belongs on it."""
        def plain(mods, cb):
            cb('running', mods[0], 'pinging 4 hosts')
            cb('ok', mods[0], '4')
            return {m: {} for m in mods}, []

        _jid, job = _finish(_WA(behaviour=plain), modules=('ping',))
        assert job['modules'][0].get('steps') in (None, [])


def _late(mods, cb):
    """A module that overran the batch deadline: the executor says so and returns."""
    cb('timeout', mods[0], '120')
    return {}, [f'{mods[0]}: timeout after 120s']


class TestARunIsOverWhenItIsOver:
    """A module that outlives the deadline has NOT finished.

    It is still walking the device and writes its own state and history when it lands. The job
    used to call itself done at that moment anyway and warn that "some modules are still
    working" — a screen announcing an ending it then has to take back, reported exactly that
    way from the panel. So it waits, and says which of the two things is true.
    """

    def test_it_does_not_call_itself_finished(self):
        jid = _start(_WA(behaviour=_late), modules=('snmp',))
        job = _until(jid, lambda j: j['modules'][0]['state'] == 'timeout')
        assert not job['done'] and job['awaiting']

    def test_the_straggler_landing_is_what_ends_it(self):
        """The executor calls the same progress channel again when the module returns —
        minutes after the batch did — and that is the only moment anything knows."""
        seen = {}

        def late(mods, cb):
            seen['cb'] = cb
            cb('timeout', mods[0], '120')
            return {}, [f'{mods[0]}: timeout after 120s']

        jid = _start(_WA(behaviour=late), modules=('snmp',))
        _until(jid, lambda j: j['awaiting'])
        seen['cb']('ok', 'snmp', '900')
        job = _until(jid, lambda j: j['done'])
        assert job['modules'][0]['state'] == 'ok' and not job['gave_up']

    def test_the_lock_is_released_while_it_waits(self):
        """The wait is the SCREEN's, not the panel's. Holding the check lock for twenty
        minutes because one module overran would stop the scheduler's own cycle."""
        wa = _WA(behaviour=_late)
        jid = _start(wa, modules=('snmp',))
        _until(jid, lambda j: j['awaiting'])
        assert wa._check_lock.acquire(blocking=False), 'the panel is locked out'
        wa._check_lock.release()

    def test_it_gives_up_eventually_and_says_so(self):
        """A module that never returns must not leave a bar spinning for ever. When the panel
        stops waiting, "it carries on in the background" is finally a true thing to say."""
        grace = jobs._LATE_GRACE
        jobs._LATE_GRACE = 0.15
        try:
            jid = _start(_WA(behaviour=_late), modules=('snmp',))
            job = _until(jid, lambda j: j['done'], wait=5.0)
        finally:
            jobs._LATE_GRACE = grace
        assert job['gave_up'] and job['modules'][0]['state'] == 'timeout'
        assert not job['awaiting']

    def test_a_run_that_broke_does_not_wait_for_anybody(self):
        """The executor itself raised: there is no straggler, only a job that has to end."""
        def boom(_mods, cb):
            cb('timeout', 'snmp', '120')
            raise RuntimeError('the executor exploded')

        _jid, job = _finish(_WA(behaviour=boom), modules=('snmp',))
        assert job['done'] and job['error'] and not job['awaiting']


class TestItAlwaysEnds:

    def test_it_finishes_and_says_what_answered(self):
        _job_id, job = _finish(_WA(), modules=('ping', 'snmp'))
        assert job['done'] and job['answered'] == ['ping', 'snmp'] and not job['error']

    def test_a_run_that_raises_still_ends(self):
        """`done` is what stops the browser polling. A job that raised before setting it is a
        dialog that spins until somebody reloads the page."""
        def boom(_mods, _cb):
            raise RuntimeError('the executor exploded')

        _job_id, job = _finish(_WA(behaviour=boom))
        assert job['done'] and 'RuntimeError' in job['error']

    def test_the_lock_is_released_even_when_it_raises(self):
        """The check lock is shared with the Status screen's run AND with the scheduler's own
        cycle, which takes it non-blocking and skips when it cannot. A job that keeps it is a
        panel that quietly stops monitoring."""
        def boom(_mods, _cb):
            raise RuntimeError('nope')

        wa = _WA(behaviour=boom)
        _finish(wa)
        assert wa._check_lock.acquire(blocking=False), 'the collection kept the check lock'

    def test_an_audit_that_fails_does_not_lose_the_result(self):
        wa = _WA()

        def angry(*_a, **_k):
            raise RuntimeError('the audit table is gone')
        wa._audit_write = angry
        _job_id, job = _finish(wa)
        assert job['done'] and job['answered'] == ['ping']


class TestWhatItRecords:

    def test_the_audit_names_who_asked(self):
        """Written from a thread where there is no request to read the actor from, so it is
        carried in. Recording it as `system` would lose the one fact the entry is for."""
        wa = _WA()
        _finish(wa, actor='javier', ip='10.0.0.2')
        entry = wa.audited[0]
        assert entry['event'] == 'infra_collect'
        assert entry['user'] == 'javier' and entry['ip'] == '10.0.0.2'

    def test_a_job_with_no_actor_is_recorded_as_the_system(self):
        wa = _WA()
        _finish(wa, actor='', ip='')
        assert wa.audited[0]['user'] == 'system' and wa.audited[0]['ip'] == 'internal'

    def test_the_entry_names_the_device_and_the_modules(self):
        wa = _WA()
        _finish(wa, uid='u9', name='erebor', modules=('ping', 'snmp'))
        detail = wa.audited[0]['detail']
        assert detail['uid'] == 'u9' and detail['name'] == 'erebor'
        assert detail['modules'] == ['ping', 'snmp']


class TestWhatLeavesTheProcess:

    def test_the_bookkeeping_stays_inside(self):
        """A poll response is an API. The timestamps the pruning uses are this module's own
        business, and a field published by accident is one somebody starts depending on."""
        _job_id, job = _finish(_WA())
        assert [k for k in job if k.startswith('_')] == []

    def test_a_job_this_process_never_had_is_none(self):
        """Not an empty job: the jobs live in memory, so "I do not know that id" is the truth
        after a restart, and the screen has a different thing to say about it."""
        assert jobs.job_status('nope') is None
        assert jobs.job_status('') is None

    def test_the_answer_is_a_copy(self):
        """The poll must not hand out the live dict — a caller that kept it would be reading
        a structure the worker threads are still writing."""
        job_id, job = _finish(_WA())
        job['completed'] = 999
        assert jobs.job_status(job_id)['completed'] != 999


class TestHowLongAModuleIsGiven:

    def test_it_asks_the_scheduler_and_not_the_browser(self):
        """45 s is how long a BROWSER is asked to wait on the Status screen. Nothing is
        waiting on a request here, and how long a module is given is the operator's setting —
        `monitoring|module_timeout`, which a fleet with a five-minute NAS has to be able to
        raise."""
        seen = []
        wa = _WA(timeout_seen=seen)
        wa._embedded_services = {'monitoring': type('M', (), {
            '_monitoring_module_timeout': 600})()}
        _finish(wa)
        assert seen == [600]

    def test_without_a_scheduler_it_still_runs(self):
        """A process with no embedded monitoring (a slimmed panel, a test) has no setting to
        read. A short deadline is the wrong number; not collecting at all is worse."""
        seen = []
        wa = _WA(timeout_seen=seen)
        _finish(wa)
        assert seen and isinstance(seen[0], int) and seen[0] > 0


class TestTheChecklistKeepsMovingWhileItWaits:
    """Reported from the screen: the module says "still working", the run is legitimately
    waiting for it, and every line under it is frozen mid-read.

    Two things had to be true and only one was. The job waits — that part worked. But the
    executor took the progress channel off the moment the batch returned, which was right when
    a run ended at its deadline and is wrong now that it does not: the straggler kept working
    and kept reporting into nothing.
    """

    def test_a_straggler_that_keeps_talking_keeps_the_lines_moving(self):
        seen = {}

        def late(mods, cb):
            seen['cb'] = cb
            cb('running', mods[0], 'isen', {'step': 'Leyendo', 'scope': 'isen',
                                            'n': 2, 'total': 24})
            cb('timeout', mods[0], '120')
            return {}, [f'{mods[0]}: timeout after 120s']

        jid = _start(_WA(behaviour=late), modules=('snmp',))
        _until(jid, lambda j: j['awaiting'])
        seen['cb']('running', 'snmp', 'isen', {'step': 'Leyendo', 'scope': 'isen',
                                               'n': 9, 'total': 24})
        job = _until(jid, lambda j: j['modules'][0]['steps'][0]['n'] == 9)
        assert not job['done'], 'a report from a straggler must not end the run'
        assert job['modules'][0]['state'] == 'timeout', (
            'the row left the state that says it is still out, and the run would end early')

    def test_and_it_still_ends_when_the_straggler_actually_lands(self):
        seen = {}

        def late(mods, cb):
            seen['cb'] = cb
            cb('timeout', mods[0], '120')
            return {}, []

        jid = _start(_WA(behaviour=late), modules=('snmp',))
        _until(jid, lambda j: j['awaiting'])
        seen['cb']('running', 'snmp', '', {'step': 'Leyendo', 'n': 3, 'total': 24})
        seen['cb']('ok', 'snmp', '900')
        job = _until(jid, lambda j: j['done'])
        assert job['modules'][0]['state'] == 'ok' and not job['gave_up']

    def test_a_finished_job_takes_no_more_reports(self):
        """A module can outlive the panel's patience. Once the run is closed its rows are the
        record of what happened, and a late write would edit history nobody is watching."""
        seen = {}

        def late(mods, cb):
            seen['cb'] = cb
            cb('timeout', mods[0], '120')
            return {}, []

        grace = jobs._LATE_GRACE
        jobs._LATE_GRACE = 0.15
        try:
            jid = _start(_WA(behaviour=late), modules=('snmp',))
            _until(jid, lambda j: j['done'], wait=5.0)
        finally:
            jobs._LATE_GRACE = grace
        seen['cb']('ok', 'snmp', '900')
        assert jobs.job_status(jid)['modules'][0]['state'] == 'timeout'



class TestItCollectsTheDeviceItWasOpenedFor:
    """A collection is OF a machine, and it used to be of the whole fleet.

    Each module ran with its whole configuration, so asking for one NAS walked every other
    device that module watched — on an SNMP fleet, minutes of other people's equipment for a
    number the operator asked about one of theirs. Reported from the screen: a dialog stuck
    on "still working" listing six devices, five of which nobody had asked about, held up by
    one of THOSE not answering.
    """

    def test_the_uid_is_what_the_run_is_narrowed_to(self):
        wa = _WA()
        job_id = _start(wa, uid='u-erebor')
        _until(job_id, lambda j: j['done'])
        assert wa.scope_seen == ['u-erebor']

    def test_it_is_the_machine_and_not_its_name(self):
        """The name is what a person recognises and the uid is what survives a rename; a
        collection narrowed by the label would follow the wrong machine after one."""
        wa = _WA()
        job_id = _start(wa, uid='u1', name='erebor')
        _until(job_id, lambda j: j['done'])
        assert wa.scope_seen == ['u1']



class TestAPhaseThatEnded:
    """A line on the checklist has to be able to STOP.

    A phase ended only when the same scope started another one, so the last phase of anything
    spun for ever — a device sitting at "reading the metrics 24/24" with a spinner, minutes
    after it finished, until the whole module landed. On a fleet that is the slowest device
    deciding when every other one looks done. And a phase that FAILED had no way to say so,
    so a device refusing connections drew a line that looked busy.
    """

    def _row(self, *reports):
        row = {'state': 'running', 'detail': '', 'steps': []}
        for scope, step, state in reports:
            jobs._step(row, 'running', '',
                       {'step': step, 'scope': scope, 'n': 0, 'total': 0, 'state': state})
        return row

    def _states(self, row):
        return [(s.get('scope', ''), s['key'], s['state']) for s in row['steps']]

    def test_a_phase_the_module_ended_stops(self):
        row = self._row(('nas', 'reading', ''), ('nas', 'reading', 'done'))
        assert self._states(row) == [('nas', 'reading', 'done')]

    def test_and_one_that_failed_says_so(self):
        row = self._row(('pve02', 'reading', ''), ('pve02', 'reading', 'fail'))
        assert self._states(row) == [('pve02', 'reading', 'fail')]

    def test_it_ends_that_machines_line_and_nobody_elses(self):
        """This module samples its devices in a pool: several lines are live at once, and an
        ending that closed them all would tick nine machines because the tenth finished."""
        row = self._row(('a', 'reading', ''), ('b', 'reading', ''), ('a', 'reading', 'done'))
        assert self._states(row) == [('a', 'reading', 'done'), ('b', 'reading', 'run')]

    def test_an_ending_does_not_create_a_line(self):
        """A phase nobody was shown does not need a tick, and inventing one would put a line
        on the checklist for work the screen never saw happening."""
        row = self._row(('c', 'reading', 'done'))
        assert row['steps'] == []

    def test_the_counter_goes_with_it(self):
        """"24/24" beside a green tick is a number that means nothing — the same reason the
        module landing clears them."""
        row = {'state': 'running', 'detail': '', 'steps': []}
        jobs._step(row, 'running', '', {'step': 'reading', 'scope': 'nas', 'n': 7, 'total': 24})
        jobs._step(row, 'running', '', {'step': 'reading', 'scope': 'nas', 'state': 'done'})
        assert row['steps'][0]['n'] == 0 and row['steps'][0]['total'] == 0

    def test_a_state_the_core_does_not_know_is_ignored(self):
        """The module names its own phases; the two words for how one ENDED are the core's,
        because they are the only part it draws rather than prints."""
        row = self._row(('nas', 'reading', ''), ('nas', 'reading', 'whatever'))
        assert self._states(row) == [('nas', 'reading', 'run')]
