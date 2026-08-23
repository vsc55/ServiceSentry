#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module's own working state has to outlive the cycle that wrote it.

The monitor's ``self.status`` looks like a free-form dictionary: ``set_conf`` takes any path,
creates whatever is missing and returns True. It is not one. What survives is what the
``check_state`` table has a column for, because ``status.read()`` at the top of every cycle
rebuilds each entry from those columns — so a field written anywhere else lives until the next
read and then disappears, with no error at either end.

That cost every counter in the SNMP module. A rate is the difference between two readings, so
the sampler kept the previous reading under the check's key and looked for it next cycle; it
was never there. Every sample was the FIRST sample, every rate was ``None``, and what the panel
showed was a device that answers its gauges and serves no traffic counters at all — interface
octets, packets, errors and discards, the TCP/UDP/ICMP/IP counters, disk and volume I/O, all of
them missing for months with nothing anywhere saying why.

So ``module_state`` is a column, and these tests are about the two halves of that: that it
round-trips, and that a counter therefore produces a rate on the second cycle. The second one
is the test that would have caught this — the first only says a column works.
"""

import json

from lib.db import get_connector
from lib.core.snmp import metrics as snmp_metrics
from lib.services.monitoring.check_state import CheckStateStore, DbBackedStatus

#: What the SNMP sampler calls its corner of the module state (`watchfuls/snmp/sampler.py`).
_ROOT, _FIELD = 'module_state', 'snmp_prev'


def _store():
    return CheckStateStore(get_connector(None, default_sqlite_path=':memory:'))


def _status():
    """The monitor's ``self.status``: a ConfigControl whose read/save is the table."""
    return DbBackedStatus(_store())


class TestTheColumnRoundTrips:

    def test_a_modules_own_state_comes_back(self):
        st = _status()
        st.data = {'snmp': {'nas/metrics': {'status': True, 'message': 'ok',
                                            'other_data': {'cpu': 7}}}}
        st.set_conf(['snmp', 'nas/metrics', _ROOT, _FIELD], {'eth0': {'v': 100.0, 't': 10.0}})
        st.save()
        st.read()
        assert st.get_conf(['snmp', 'nas/metrics', _ROOT, _FIELD], {}) == {
            'eth0': {'v': 100.0, 't': 10.0}}

    def test_the_result_is_not_disturbed_by_it(self):
        """The columns that were already there answer exactly as before — this is a field
        beside the result, not a change to what a result is."""
        st = _status()
        st.data = {'ping': {'gw': {'status': False, 'message': 'down', 'severity': 'error',
                                   'other_data': {'ms': 12}, 'fail_count': 3}}}
        st.save()
        st.read()
        rec = st.data['ping']['gw']
        assert rec['status'] is False and rec['message'] == 'down'
        assert rec['severity'] == 'error' and rec['other_data'] == {'ms': 12}
        assert rec['fail_count'] == 3
        assert rec[_ROOT] == {}, 'a check that keeps no state gets an empty room, not a None'

    def test_a_seed_does_not_erase_a_baseline(self):
        """``set()`` is the one-row upsert used by seeds and by the tests. It writes every
        column, so unless it carries the state forward it wipes it — a device that goes quiet
        for a cycle because something unrelated touched its row."""
        s = _store()
        s.set('snmp', 'nas', True, metric='/metrics', module_state={_FIELD: {'a': 1}})
        s.set('snmp', 'nas', True, metric='/metrics', message='second pass')
        rec = s.get_all()[('snmp', 'nas', '/metrics')]
        assert rec['message'] == 'second pass'
        assert rec[_ROOT] == {_FIELD: {'a': 1}}, 'the baseline was erased by an unrelated write'

    def test_nothing_the_reader_emits_is_dropped_by_the_writer(self):
        """The silent-drop guard, and the shape of the bug this file is about: the reader
        rebuilds an entry from a fixed set of names and the writer stores a fixed set. A name
        on one list and not the other is a value that vanishes between two cycles with nothing
        raised, which is not a failure anybody goes looking for."""
        s = _store()
        s.set('m', 'k', True, message='m', other_data={'x': 1}, fail_count=2,
              severity='', module_state={'kept': True})
        first = s.as_status_dict()
        # …and the whole thing straight back in, as the monitor does every cycle.
        s.persist_status(first)
        again = s.as_status_dict()
        lost = [k for k, v in first['m']['k'].items()
                if k not in ('ts', 'uid') and again['m']['k'].get(k) != v]
        assert not lost, (
            f'as_status_dict emits {lost} and persist_status does not carry it — the value '
            'dies on the next read with no error')


class TestACounterGetsItsRate:
    """End to end over the two cycles, with the real counter maths.

    Written against ``metrics.sample`` and the real status object rather than against the
    sampler, which needs a device: what broke was never the arithmetic, it was that the
    number it subtracts from was gone by the time it was asked for.
    """

    def _cycle(self, st, key, metric, raw, now):
        """One cycle: read the state as the monitor does, sample, write it back, save."""
        st.read()
        prev = (st.get_conf(['snmp', key, _ROOT, _FIELD], {}) or {}).get(metric['key'])
        value, new_state = snmp_metrics.sample(metric, raw, prev, now)
        if new_state is not None:
            st.set_conf(['snmp', key, _ROOT, _FIELD, metric['key']], new_state)
        st.set_conf(['snmp', key, 'status'], True)
        st.save()
        return value

    def test_the_second_sample_is_a_rate(self):
        st = _status()
        m = {'key': 'if_in', 'kind': 'counter', 'width': 64}
        assert self._cycle(st, 'nas/metrics', m, 1_000, 100.0) is None, (
            'the first sample of a counter is a baseline and not a number')
        # …and 10 seconds later, 8000 octets further on: 700 per second.
        assert self._cycle(st, 'nas/metrics', m, 8_000, 110.0) == 700.0

    def test_a_gauge_never_needed_any_of_this(self):
        """The half that always worked, so a regression here reads as what it is."""
        st = _status()
        m = {'key': 'cpu_idle', 'kind': 'gauge'}
        assert self._cycle(st, 'nas/metrics', m, 87, 100.0) == 87

    def test_the_baseline_is_filed_under_the_check_it_belongs_to(self):
        """Two devices sampled by the same module must not share one baseline — a rate
        computed against another machine's counter is a number, and a wrong one."""
        st = _status()
        m = {'key': 'if_in', 'kind': 'counter', 'width': 64}
        self._cycle(st, 'a/metrics', m, 1_000, 100.0)
        self._cycle(st, 'b/metrics', m, 50_000, 100.0)
        assert self._cycle(st, 'a/metrics', m, 2_000, 110.0) == 100.0
        assert self._cycle(st, 'b/metrics', m, 51_000, 110.0) == 100.0

    def test_it_is_json_and_stays_json(self):
        """The column is text. A baseline that cannot be serialised would be written as a
        string of a dict and read back as one, and the arithmetic would fail on it."""
        s = _store()
        s.set('snmp', 'nas', True, module_state={_FIELD: {'eth0': {'v': 1.5, 't': 2.5}}})
        raw = s._db.fetchone(
            'SELECT module_state FROM check_state WHERE module=? AND '
            f'{s._qk}=?', ('snmp', 'nas'))[0]
        assert json.loads(raw) == {_FIELD: {'eth0': {'v': 1.5, 't': 2.5}}}


class TestARunFromThePanelStartsFromWhatIsStored:
    """A forced collection saves with ``persist_status``, which REPLACES the table.

    So whatever this process is holding is what every check in the installation ends up
    with — and in a split deployment the web process is not the one that has been writing.
    It also decides whether a counter has anything to subtract from: the previous reading
    is in the table, and a run that never read it starts from nothing every time, which is
    the same "every sample is the first sample" this file is about.
    """

    class _Status:
        def __init__(self):
            self.reads = 0

        def read(self):
            self.reads += 1

        def save(self):
            pass

    class _Monitor:
        def __init__(self, status):
            self.status = status
            self.debug = type('D', (), {'print': lambda *a, **k: None})()
            self.config_modules = type('C', (), {'get_conf': lambda *a, **k: {}})()

        def _get_enabled_modules(self):
            return []

        def _import_watchful(self, _name):
            pass

        def check_module(self, name):
            return False, name, None

    def test_the_state_is_read_before_anything_runs(self):
        from lib.services.monitoring.executor import run_checks   # noqa: PLC0415
        st = self._Status()
        run_checks(self._Monitor(st), ['nosuch'], timeout=2)
        assert st.reads == 1, 'the run rewrote the whole table from a snapshot it never took'

    def test_a_state_that_cannot_be_read_does_not_stop_the_checks(self):
        """A broken read is a reason to run blind, not a reason not to monitor."""
        from lib.services.monitoring.executor import run_checks   # noqa: PLC0415

        class Boom(self._Status):
            def read(self):
                raise RuntimeError('database is away')

        _, errors = run_checks(self._Monitor(Boom()), ['nosuch'], timeout=2)
        assert errors, 'the module still ran and still reported'


class TestAnExistingInstallJustGainsAColumn:
    """Nobody reinstalls to get a fix. The column has to appear on a table that is already
    full, without touching a row of it — which is why it is declared LAST: a missing column
    is added with ADD COLUMN only while every one before it is already there."""

    def test_the_old_table_migrates_and_keeps_its_rows(self):
        from lib.db.schema import TableSpec                       # noqa: PLC0415
        from lib.services.monitoring.check_state.store import _SCHEMA   # noqa: PLC0415
        before = TableSpec(
            name=_SCHEMA.name,
            columns=tuple(c for c in _SCHEMA.columns if c.name != _ROOT),
            unique_constraints=_SCHEMA.unique_constraints)
        db = get_connector(None, default_sqlite_path=':memory:')
        db.reconcile_table(before)
        db.execute(
            'INSERT INTO check_state(uid, module, "key", item_uid, metric, status, message, '
            'other_data, fail_count, last_change_ts, severity) '
            "VALUES('u', 'snmp', 'nas', 'nas', '/metrics', 1, 'ok', '{\"cpu\": 7}', 0, 1.0, '')")
        db.commit()
        rec = CheckStateStore(db).get_all()[('snmp', 'nas', '/metrics')]   # its bootstrap migrates
        assert rec['message'] == 'ok' and rec['other_data'] == {'cpu': 7}
        assert rec[_ROOT] == {}, 'a row written before the column exists reads as empty state'

    def test_it_is_the_last_column_declared(self):
        """The rule that makes the migration an ADD COLUMN. Moving it earlier would rebuild
        the whole table on every install that upgrades."""
        from lib.services.monitoring.check_state.store import _SCHEMA   # noqa: PLC0415
        assert _SCHEMA.columns[-1].name == _ROOT
