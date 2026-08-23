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
        self._behaviour = behaviour or (lambda mods, cb: ({m: {} for m in mods}, []))
        self._timeout_seen = timeout_seen if timeout_seen is not None else []

    def _run_checks(self, mods, *, timeout, progress_cb):
        self._timeout_seen.append(timeout)
        return self._behaviour(mods, progress_cb)

    def _audit_write(self, event, user, ip, detail):
        self.audited.append({'event': event, 'user': user, 'ip': ip, 'detail': detail})


def _finish(wa, uid='u1', name='erebor', modules=('ping',), actor='javier', ip='10.0.0.2',
            wait=5.0):
    """Start a job with the lock held (as the route does) and wait for it to end."""
    assert wa._check_lock.acquire(blocking=False)
    job_id = jobs.start_collect(wa, uid, name, list(modules), actor=actor, ip=ip)
    deadline = time.time() + wait
    while time.time() < deadline:
        job = jobs.job_status(job_id)
        if job and job['done']:
            return job_id, job
        time.sleep(0.02)
    raise AssertionError('the job never finished')


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

    def test_a_timeout_counts_towards_the_bar(self):
        """The module is still running, but the bar must not stop at 90 % forever — which is
        exactly what the fleet this was written for would do."""
        def late(mods, cb):
            cb('timeout', mods[0], '120')
            return {}, [f'{mods[0]}: timeout after 120s']

        _job_id, job = _finish(_WA(behaviour=late), modules=('snmp',))
        assert job['completed'] == 1 and job['modules'][0]['state'] == 'timeout'


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
