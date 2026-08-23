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

    def __init__(self, delays):
        self._delays = delays
        self.debug = type('D', (), {'print': staticmethod(lambda *a, **k: None)})()
        self.config_modules = type('C', (), {'get_conf': staticmethod(lambda *a, **k: {'x': {}})})()
        self.saved = []
        self._db = None

    def _get_enabled_modules(self):
        return list(self._delays)

    def check_module(self, name):
        time.sleep(self._delays[name])
        return True, name, _Result({f'{name}-item': (True, 'ok', {'v': 1})})

    def _process_module_result(self, name, _data):
        self.saved.append(name)

    @property
    def status(self):
        return type('S', (), {'save': staticmethod(lambda: None)})()

    def flush_alerts(self):
        pass


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

    def _log(self, delays, names, timeout=5):
        seen = []
        lock = threading.Lock()

        def cb(state, module, detail=''):
            with lock:
                seen.append((state, module, detail))
        run_checks(_Monitor(delays), names, timeout=timeout, progress_cb=cb)
        return seen

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
            def report_progress(self, module_name, detail):
                cb = getattr(self, '_progress_sink', None)
                if cb is not None:
                    cb('running', module_name, detail)

            def check_module(self, name):
                self.report_progress(name, 'erebor — Synology disks (3/24)')
                return super().check_module(name)

        run_checks(_Chatty({'snmp': 0}), ['snmp'], timeout=5,
                   progress_cb=lambda s, m, d='': seen.append((s, m, d)))
        assert ('running', 'snmp', 'erebor — Synology disks (3/24)') in seen

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
