#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module that finishes after the deadline still gets recorded.

The cycle gives each module a deadline and moves on. What it does NOT do is kill the thread —
it cannot, so the module comes back, and when it does it writes its live status the same way
it always would. Its history rows went somewhere else: into a buffer whose writer had run
minutes earlier, and they were dropped without a word.

The result is a module with a current status on screen and no series behind it, which is a
shape nothing complains about: the panel is green, the chart is empty, and the two look like
different subsystems having different problems.

Found on a real fleet. Sampling one NAS with a full SNMP device profile is hundreds of round
trips and took about five minutes against a 120-second deadline, so every cycle wrote 295
live results and, since the day the module was installed, not one history row.
"""

import threading
import time

from lib.services.monitoring.executor import run_checks


class _Result:
    """The slice of ReturnModuleCheck that run_checks actually touches."""

    def __init__(self, items):
        self._items = dict(items)

    @property
    def list(self):
        return list(self._items)

    def get_status(self, key):
        return self._items[key][0]

    def get_message(self, key):
        return self._items[key][1]

    def get_other_data(self, key):
        return self._items[key][2]


class _History:
    def __init__(self):
        self.rows = []
        self._lock = threading.Lock()

    def record(self, module, key, status, data):
        with self._lock:
            self.rows.append((module, key, status, data))


class _Monitor:
    """A monitor whose modules are functions: name → seconds to take."""

    def __init__(self, delays, per_module=True):
        self._delays = delays
        self.debug = type('D', (), {'print': staticmethod(lambda *a, **k: None)})()
        self.config_modules = type('C', (), {'get_conf': staticmethod(lambda *a, **k: {'x': {}})})()
        self.saved = []
        self.saves = []
        self._per_module = per_module
        self._db = None
        self.scopes = []
        self.prunes = []

    def _get_enabled_modules(self):
        return list(self._delays)

    def check_module(self, name, only_host=''):
        self.scopes.append(only_host)
        time.sleep(self._delays[name])
        return True, name, _Result({f'{name}-item': (True, 'ok', {'v': 1})})

    def _process_module_result(self, name, _data, prune=True):
        self.saved.append(name)
        self.prunes.append(prune)

    @property
    def status(self):
        # Both, because the executor prefers the narrow one and must survive its absence:
        # with no database the monitor's status is a plain ConfigControl, which has neither.
        outer = self

        class _S:
            @staticmethod
            def save():
                outer.saves.append('*')

            @staticmethod
            def save_module(module):
                outer.saves.append(module)

        if not self._per_module:
            del _S.save_module
        return _S()

    def flush_alerts(self):
        pass


class TestSavingWhatOneModuleSaid:
    """A run saves after every module, and the whole-table write it used to do meant eleven
    modules' rows were read and rewritten to record the twelfth — measured at ~60 ms a time on
    a fleet-sized table, three quarters of a second per run, with every page load waiting
    behind it."""

    def test_only_the_module_that_finished_is_written(self):
        mon = _Monitor({'fast': 0, 'other': 0})
        run_checks(mon, ['fast', 'other'], timeout=5)
        assert sorted(mon.saves) == ['fast', 'other']
        assert '*' not in mon.saves, 'the whole table is rewritten per module again'

    def test_a_status_that_cannot_do_it_still_gets_saved(self):
        """With no database the monitor's status is a plain ConfigControl, which has no
        `save_module`. An AttributeError here is swallowed by the executor's own `except`, so
        the module would be recorded as having FAILED for the sole reason that it was saved."""
        mon = _Monitor({'fast': 0}, per_module=False)
        hist = _History()
        run_checks(mon, ['fast'], timeout=5, history=hist)
        assert mon.saves == ['*'], 'nothing was saved at all'
        assert [r[0] for r in hist.rows] == ['fast'], (
            'the module was recorded as failed because saving it raised')


class TestTheOnesThatArriveOnTime:

    def test_their_history_is_written(self):
        hist = _History()
        run_checks(_Monitor({'fast': 0}), ['fast'], timeout=5, history=hist)
        assert [r[0] for r in hist.rows] == ['fast']

    def test_no_history_store_is_not_an_error(self):
        """A probe runs the same executor with no store — it must not be a special case that
        only shows up the first time somebody presses "test"."""
        results, errors = run_checks(_Monitor({'fast': 0}), ['fast'], timeout=5, history=None)
        assert not errors and 'fast' in results


class TestTheOneThatArrivesLate:

    def test_it_is_reported_as_a_timeout(self):
        results, errors = run_checks(_Monitor({'slow': 2.5}), ['slow'], timeout=1,
                                     history=_History())
        assert 'slow' not in results
        assert any('timeout' in e for e in errors), errors

    def test_its_history_is_written_anyway(self):
        """The regression this file exists for. The cycle stops waiting; the module does not
        stop running, and what it measured is worth exactly as much as it was before the
        clock ran out."""
        hist = _History()
        mon = _Monitor({'slow': 2.5})
        run_checks(mon, ['slow'], timeout=1, history=hist)
        # It is still running when run_checks returns — wait for the straggler the way the
        # scheduler does: by letting it finish on its own.
        for _ in range(100):
            if hist.rows:
                break
            time.sleep(0.05)
        assert [r[0] for r in hist.rows] == ['slow'], 'a late module lost its series'
        assert mon.saved == ['slow'], 'and it did save its live status, as it always did'

    def test_it_is_recorded_once_and_not_twice(self):
        """Both paths are guarded by the same lock, so a module finishing exactly at the
        boundary is written by the flush or by itself — never by both."""
        hist = _History()
        run_checks(_Monitor({'a': 0, 'b': 2.5}), ['a', 'b'], timeout=1, history=hist)
        time.sleep(3.0)
        keys = sorted(r[1] for r in hist.rows)
        assert keys == ['a-item', 'b-item'], keys


class TestSayingWhereItIs:
    """A collection asked for by hand runs for minutes, and a bar that only moves at the end
    is indistinguishable from one that has hung. The executor is the only thing that knows
    when a module starts and lands, so it is the only thing that can say."""

    def _log(self, delays, names, timeout=5, monitor=None):
        seen = []
        lock = threading.Lock()

        def cb(state, module, detail='', extra=None):
            with lock:
                seen.append((state, module, detail))
        run_checks(monitor or _Monitor(delays), names, timeout=timeout, progress_cb=cb)
        return seen

    def test_the_callback_is_called_the_way_a_consumer_declares_it(self):
        """A signature mismatch here is INVISIBLE: the executor swallows anything the progress
        display raises, on purpose — it must never be able to fail a check — so a consumer
        written for three arguments simply stops being called and the dialog goes blank with
        nothing raised anywhere. The contract is four, and this is what says so."""
        seen = []
        run_checks(_Monitor({'fast': 0}), ['fast'], timeout=5,
                   progress_cb=lambda *a: seen.append(a))
        assert seen and all(len(a) == 4 for a in seen), seen

    def test_a_module_says_when_it_starts_and_when_it_lands(self):
        seen = self._log({'fast': 0}, ['fast'])
        assert [s for s, _m, _d in seen] == ['running', 'ok']
        assert all(m == 'fast' for _s, m, _d in seen)

    def test_it_says_how_many_values_came_back(self):
        """The count is what makes a finished row worth reading: "ok" says it ran, "295
        values" says it found the device."""
        seen = self._log({'fast': 0}, ['fast'])
        assert ('ok', 'fast', '1') in seen

    def test_a_late_module_is_a_timeout_and_not_an_error(self):
        """It has NOT failed — it is still running and writes its own state and history when
        it lands. A screen told "error" is one that has to take it back, and nothing is
        watching long enough to."""
        seen = self._log({'slow': 2.5}, ['slow'], timeout=1)
        states = [s for s, _m, _d in seen]
        assert 'timeout' in states and 'error' not in states

    def test_a_callback_that_raises_does_not_take_the_run_with_it(self):
        """The progress display must never be in a position to kill the work it describes."""
        def boom(*_a, **_k):
            raise RuntimeError('the screen exploded')
        results, errors = run_checks(_Monitor({'fast': 0}), ['fast'], timeout=5,
                                     progress_cb=boom)
        assert not errors and 'fast' in results

    def test_a_module_can_say_where_it_is_from_inside(self):
        """The module boundary is not enough for the one that matters. Sampling a NAS through
        its device profiles is minutes of round trips inside a SINGLE module, so a screen
        watching only start/finish sits at 0 % for five minutes and looks like a hang. The
        executor installs a sink the module reports through."""
        seen = []

        class _Chatty(_Monitor):
            def report_progress(self, module_name, detail, *, step='', n=0, total=0):
                cb = getattr(self, '_progress_sink', None)
                if cb is not None:
                    cb('running', module_name, detail,
                       {'step': step, 'n': n, 'total': total})

            def check_module(self, name, only_host=''):
                self.report_progress(name, 'erebor — Synology disks',
                                     step='Leyendo las métricas', n=3, total=24)
                return super().check_module(name, only_host)

        run_checks(_Chatty({'snmp': 0}), ['snmp'], timeout=5,
                   progress_cb=lambda s, m, d='', x=None: seen.append((s, m, d, x)))
        assert ('running', 'snmp', 'erebor — Synology disks',
                {'step': 'Leyendo las métricas', 'n': 3, 'total': 24}) in seen

    def test_the_phase_a_module_names_reaches_the_watcher_untouched(self):
        """The core draws what arrives and names nothing: it has no vocabulary for "which
        profile of a Synology am I on", and one written here would be a lie for the other
        twenty modules. So the executor carries the words, it does not interpret them."""
        seen = []

        class _Phased(_Monitor):
            def report_progress(self, module_name, detail, *, step='', n=0, total=0):
                cb = getattr(self, '_progress_sink', None)
                if cb is not None:
                    cb('running', module_name, detail,
                       {'step': step, 'n': n, 'total': total})

            def check_module(self, name, only_host=''):
                self.report_progress(name, '', step='una fase que nadie del núcleo conoce')
                return super().check_module(name, only_host)

        run_checks(_Phased({'snmp': 0}), ['snmp'], timeout=5,
                   progress_cb=lambda s, m, d='', x=None: seen.append(x))
        assert {'step': 'una fase que nadie del núcleo conoce', 'n': 0, 'total': 0} in seen

    def test_a_module_that_overran_is_reported_when_it_finally_lands(self):
        """It writes its own state and history — that part always worked. What nobody told was
        the SCREEN, which had been shown "still working" and never heard another word, so a
        collection somebody was watching ended at 90 % and stayed there."""
        seen = []
        lock = threading.Lock()

        def cb(state, module, detail='', extra=None):
            with lock:
                seen.append((state, module))
        run_checks(_Monitor({'slow': 0.6}), ['slow'], timeout=0.2, progress_cb=cb)
        assert ('timeout', 'slow') in seen
        deadline = time.time() + 5
        while time.time() < deadline and ('ok', 'slow') not in seen:
            time.sleep(0.02)
        assert ('ok', 'slow') in seen, f'the straggler landed and said nothing: {seen}'

    def test_the_sink_does_not_outlive_the_batch(self):
        """The scheduler shares this monitor. A sink left behind would have its cycles
        reporting into a job that ended hours ago."""
        mon = _Monitor({'fast': 0})
        run_checks(mon, ['fast'], timeout=5, progress_cb=lambda *_a, **_k: None)
        assert getattr(mon, '_progress_sink', None) is None

    def test_no_callback_is_the_normal_case(self):
        results, _errors = run_checks(_Monitor({'fast': 0}), ['fast'], timeout=5)
        assert 'fast' in results


class TestTheAccessorsAreProperties:
    """A `@property` decorates whatever function comes next, so a method inserted between the
    two silently steals it — and the one that lost it becomes a bound method that every caller
    then uses as a number.

    That is what happened here: `interval * _WORKER_FRESH_INTERVALS` became "method times
    int", and the Services endpoint answered 500 on every poll. Nothing about the change was
    wrong to read; the decorator was simply attached to something else.
    """

    def test_the_scheduler_accessors_are_values_and_not_methods(self):
        from lib.services.monitoring.manager import _MonitoringMixin   # noqa: PLC0415
        for name in ('_monitoring_running', '_monitoring_interval',
                     '_monitoring_module_timeout'):
            attr = getattr(_MonitoringMixin, name)
            assert isinstance(attr, property), (
                f'{name} is a plain method — every caller reads it as a value, so the first '
                f'arithmetic on it raises and the endpoint that reads it answers 500')

    def test_nothing_calls_them(self):
        """The other half of the same mistake, from the other side: a caller that adds `()`
        to a property gets whatever the value is, called — a TypeError one layer further from
        the change that caused it."""
        import os                                                      # noqa: PLC0415
        import re                                                      # noqa: PLC0415
        src_root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        bad = []
        for root, _dirs, files in os.walk(os.path.join(src_root, 'lib')):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                path = os.path.join(root, fname)
                with open(path, encoding='utf-8') as fh:
                    body = fh.read()
                for name in ('_monitoring_running', '_monitoring_interval',
                             '_monitoring_module_timeout'):
                    # ...the definition itself excluded, obviously.
                    if re.search(r'(?<!def )' + re.escape(name) + r'\s*\(', body):
                        bad.append(f'{fname}: {name}()')
        assert not bad, f'called as a method: {bad}'


class TestTheChannelOutlivesTheBatchWhenTheWorkDoes:
    """Taking it off when the call returns was right when a run ENDED at its deadline.

    It does not any more: a module past the deadline is still working, still reporting, and
    the job on the screen is open waiting for it. Reported as a checklist frozen mid-read
    under the words "still working".
    """

    def test_it_stays_while_a_module_is_still_out(self):
        mon = _Monitor({'slow': 0.6})
        run_checks(mon, ['slow'], timeout=0.2, progress_cb=lambda *_a, **_k: None)
        assert getattr(mon, '_progress_sink', None) is not None, (
            'the straggler is reporting into nothing')

    def test_and_comes_off_when_it_lands(self):
        """Never taking it off would leave the scheduler's own cycles reporting into a job
        that ended hours ago."""
        mon = _Monitor({'slow': 0.4})
        run_checks(mon, ['slow'], timeout=0.15, progress_cb=lambda *_a, **_k: None)
        deadline = time.time() + 5
        while time.time() < deadline and getattr(mon, '_progress_sink', None) is not None:
            time.sleep(0.02)
        assert getattr(mon, '_progress_sink', None) is None

    def test_a_batch_that_did_not_overrun_lets_go_at_once(self):
        mon = _Monitor({'fast': 0})
        run_checks(mon, ['fast'], timeout=5, progress_cb=lambda *_a, **_k: None)
        assert getattr(mon, '_progress_sink', None) is None

    def test_several_stragglers_all_have_to_land(self):
        """The count is what decides, and it is taken under a lock: `-= 1` is three bytecodes,
        and two threads doing it at once is a count that never reaches zero."""
        mon = _Monitor({'a': 0.5, 'b': 0.7})
        run_checks(mon, ['a', 'b'], timeout=0.15, progress_cb=lambda *_a, **_k: None)
        assert getattr(mon, '_progress_sink', None) is not None
        deadline = time.time() + 5
        while time.time() < deadline and getattr(mon, '_progress_sink', None) is not None:
            time.sleep(0.02)
        assert getattr(mon, '_progress_sink', None) is None



class TestARunAboutOneMachine:
    """"Collect this device" is not a cycle, and the difference is what gets deleted.

    The prune below the result — every stored key the run did not report — is right when the
    run covered everything and catastrophic when it did not: a collection of one NAS would
    wipe the live state of every other machine that module watches. So a narrowed run carries
    its scope down to the module AND turns the prune off, and those two facts have to travel
    together or the feature is a data-loss bug with a progress bar on it.
    """

    def test_without_a_scope_nothing_changes(self):
        mon = _Monitor({'ping': 0})
        run_checks(mon, ['ping'], timeout=5)
        assert mon.scopes == [''] and mon.prunes == [True]

    def test_the_machine_reaches_the_module(self):
        mon = _Monitor({'ping': 0})
        run_checks(mon, ['ping'], timeout=5, only_host='h1')
        assert mon.scopes == ['h1']

    def test_and_a_narrowed_run_never_prunes(self):
        """The half that deletes. A narrowed run did not fail to report the other machines —
        it was never asked about them, and treating the two the same is how a button that
        refreshes one device empties the screen for thirty-nine."""
        mon = _Monitor({'ping': 0})
        run_checks(mon, ['ping'], timeout=5, only_host='h1')
        assert mon.prunes == [False]
