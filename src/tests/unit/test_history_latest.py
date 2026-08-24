#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - the last sample of each series, and why it is not the index.
#
"""What "open this device" costs the history table.

Reported from the screen: clicking a machine in the fleet list took seconds, and the URL
changed before anything else did. About 700 ms of that was one call — the device page asking
for the WHOLE fleet's history index and using four fields of it.

``get_index`` answers a richer question (how many samples, since when, what share were up) and
pays for it twice over: the aggregate is a second pass across the table, and the grouping key
``COALESCE(item_uid, module || ':' || key)`` is an expression no index can serve, so both
passes sort the lot in a temporary B-tree. The device page reads none of that — it uses the
index purely as a FALLBACK for a check with no live state, and wants `key`, `last_data`,
`last_status` and `last_ts`.

``latest_by_series`` asks only that, grouped on ``(module, key)`` — which is how the rest of
the product addresses a series and exactly what ``idx_history_mkts`` is ordered by, so the
grouping streams off the index. Measured against a real 54.000-row history: **777 ms → 67 ms**,
same series, same values.

No Flask here, directly or transitively: a connector, a store, and rows.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.db import get_connector                      # noqa: E402
from lib.core.history.store import HistoryStore       # noqa: E402


def _store():
    return HistoryStore(get_connector(None, default_sqlite_path=':memory:'))


def _by_key(rows):
    return {(r['module'], r['key']): r for r in rows}


class TestTheLastSampleOfEachSeries:

    def test_one_row_per_series_and_it_is_the_newest(self):
        st = _store()
        for value in (1, 2, 3):
            st.record('cpu', 'srv1', status=True, data={'v': value})
        st.record('cpu', 'srv2', status=False, data={'v': 9})
        got = _by_key(st.latest_by_series())
        assert set(got) == {('cpu', 'srv1'), ('cpu', 'srv2')}
        assert got[('cpu', 'srv1')]['last_data'] == {'v': 3}
        assert got[('cpu', 'srv2')]['last_status'] is False

    def test_it_answers_the_same_series_as_the_index_it_replaces(self):
        """The whole point: a cheaper question, not a different one."""
        st = _store()
        for mod, key in (('cpu', 'a'), ('cpu', 'b'), ('ping', 'a'), ('snmp', 'x/eth0')):
            st.record(mod, key, status=True, data={'n': key})
            st.record(mod, key, status=False, data={'n': key + '!'})
        index = _by_key(st.get_index())
        lean = _by_key(st.latest_by_series())
        assert set(index) == set(lean)
        for k, row in index.items():
            for field in ('last_ts', 'last_status', 'last_data'):
                assert lean[k][field] == row[field], (k, field)

    def test_a_module_filter_narrows_it(self):
        """The fallback can only contribute a series belonging to one of this machine's own
        checks, so the rest of the fleet's is fetched and thrown away."""
        st = _store()
        for mod in ('cpu', 'ping', 'snmp'):
            st.record(mod, 'k', status=True, data={})
        assert {r['module'] for r in st.latest_by_series(['cpu', 'snmp'])} == {'cpu', 'snmp'}
        assert {r['module'] for r in st.latest_by_series()} == {'cpu', 'ping', 'snmp'}
        assert st.latest_by_series([]) == st.latest_by_series(), (
            'an empty filter must mean "everything" and not "nothing"')
        assert st.latest_by_series(['', None]) == st.latest_by_series()

    def test_an_empty_history_is_an_empty_list(self):
        assert _store().latest_by_series() == []
        assert _store().latest_by_series(['cpu']) == []

    def test_two_samples_sharing_a_timestamp_still_give_one_row(self):
        """A join on `MAX(ts)` matches both. `get_index` breaks the tie with `id DESC`; this
        keeps the last row the scan hands back, which is the same row for the same reason."""
        st = _store()
        st.record('cpu', 'k', status=True, data={'v': 1})
        st.record('cpu', 'k', status=True, data={'v': 2})
        # force the tie
        st._db.execute('UPDATE history SET ts = 1000 WHERE module = ?', ('cpu',))
        rows = st.latest_by_series()
        assert len(rows) == 1, 'a tie in the timestamp duplicated the series'


class TestNothingWritesAnItemUid:
    """`latest_by_series` groups on `(module, key)` and does not consult `item_uid`, while
    `get_index` groups on `COALESCE(item_uid, module || ':' || key)`. Those are the same set
    only while no history row carries an item_uid — which is the case: the monitor records a
    sample as `record(module, key, status, data)`.

    Pinned here rather than assumed. The day something starts passing one, the two answers
    begin to differ — a renamed check staying one series in the index and becoming two here —
    and this is the test that should say so first."""

    def test_the_monitor_records_without_one(self):
        from tests.helpers import _read                 # noqa: PLC0415
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        src = _read(os.path.join(root, 'lib', 'services', 'monitoring', 'executor.py'))
        assert 'item_uid' not in src, (
            'the monitor now writes an item_uid — latest_by_series groups without it')

    def test_and_the_two_groupings_agree_while_that_holds(self):
        st = _store()
        st.record('cpu', 'a', status=True, data={})
        st.record('cpu', 'b', status=True, data={})
        assert _by_key(st.get_index()).keys() == _by_key(st.latest_by_series()).keys()

    def test_a_row_that_does_carry_one_is_where_they_part(self):
        """Not a failure — a difference, written down. The index folds the two keys of one
        item into a single series; this reports the series as the rest of the product
        addresses them."""
        st = _store()
        st.record('cpu', 'old-name', status=True, data={}, item_uid='u1')
        st.record('cpu', 'new-name', status=True, data={}, item_uid='u1')
        assert len(st.get_index()) == 1
        assert len(st.latest_by_series()) == 2
