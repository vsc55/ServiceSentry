#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for SyslogStore — insert, filtered query and retention."""

import time

from lib.db import get_connector
from lib.services.syslog.store import SyslogStore


def _store():
    return SyslogStore(get_connector(None, default_sqlite_path=':memory:'))


def _rec(**kw):
    base = {'ts': time.time(), 'received_at': '2026-06-22T10:00:00Z', 'source': '10.0.0.1',
            'hostname': 'h1', 'app': 'sshd', 'procid': '1', 'severity': 6, 'facility': 4,
            'msgid': '', 'message': 'hello', 'raw': '<38>...'}
    base.update(kw)
    return base


class TestSyslogStore:

    def test_add_and_query(self):
        s = _store()
        s.add(_rec(message='first'))
        s.add(_rec(message='second'))
        rows = s.query()
        assert len(rows) == 2
        assert rows[0]['message'] == 'second'        # newest first
        assert rows[0]['severity_name'] == 'info' and rows[0]['facility_name'] == 'auth'

    def test_add_many(self):
        s = _store()
        s.add_many([_rec(message=f'm{i}') for i in range(50)])
        assert s.count() == 50

    def test_filter_severity_max(self):
        s = _store()
        s.add(_rec(severity=3, message='error'))     # err
        s.add(_rec(severity=6, message='info'))       # info
        # severity_max=3 → only err and worse
        rows = s.query({'severity_max': 3})
        assert len(rows) == 1 and rows[0]['message'] == 'error'

    def test_filter_host_app_facility_text(self):
        s = _store()
        s.add(_rec(hostname='web01', app='nginx', facility=4, message='boom error'))
        s.add(_rec(hostname='db03', app='postgres', facility=16, message='vacuum ok'))
        assert len(s.query({'hostname': 'web01'})) == 1
        assert len(s.query({'app': 'postgres'})) == 1
        assert len(s.query({'facility': 16})) == 1
        assert len(s.query({'q': 'error'})) == 1

    def test_filter_time_range(self):
        s = _store()
        now = time.time()
        s.add(_rec(ts=now - 7200, message='old'))     # 2h ago
        s.add(_rec(ts=now, message='new'))
        rows = s.query({'since': now - 3600})         # last hour
        assert len(rows) == 1 and rows[0]['message'] == 'new'

    def test_distinct(self):
        s = _store()
        s.add(_rec(hostname='a')); s.add(_rec(hostname='b')); s.add(_rec(hostname='a'))
        assert s.distinct('hostname') == ['a', 'b']
        assert s.distinct('bogus') == []

    def test_prune_by_age(self):
        s = _store()
        now = time.time()
        s.add(_rec(ts=now - 40 * 86400, message='old'))   # 40 days
        s.add(_rec(ts=now, message='recent'))
        deleted = s.prune(retention_days=30)
        assert deleted == 1 and s.count() == 1
        assert s.query()[0]['message'] == 'recent'

    def test_prune_by_max_rows(self):
        s = _store()
        s.add_many([_rec(message=f'm{i}') for i in range(100)])
        deleted = s.prune(max_rows=10)
        assert deleted == 90 and s.count() == 10
        # the 10 newest survive
        msgs = {r['message'] for r in s.query(limit=20)}
        assert 'm99' in msgs and 'm0' not in msgs

    def test_prune_disabled(self):
        s = _store()
        s.add_many([_rec() for _ in range(5)])
        assert s.prune(retention_days=0, max_rows=0) == 0 and s.count() == 5

    def test_delete_all(self):
        s = _store()
        s.add_many([_rec() for _ in range(5)])
        s.delete_all()
        assert s.count() == 0


class TestSyslogStats:

    def test_breakdowns_and_total(self):
        s = _store()
        s.add_many([_rec(hostname='web01', app='nginx', severity=3, facility=4),
                    _rec(hostname='web01', app='nginx', severity=6, facility=4),
                    _rec(hostname='db01',  app='mysqld', severity=4, facility=3)])
        st = s.stats()
        assert st['total'] == 3
        # by_host ordered by count desc
        assert st['by_host'][0] == {'value': 'web01', 'count': 2}
        # severity/facility carry their human name
        sevs = {d['name']: d['count'] for d in st['by_severity']}
        assert sevs.get('err') == 1 and sevs.get('info') == 1
        assert any(d['count'] == 2 for d in st['by_app'])      # nginx x2
        assert all('name' in d for d in st['by_facility'])

    def test_only_computes_the_requested_breakdowns(self):
        """Each breakdown is its own GROUP BY over the whole table.

        The Overview card reads the total and the severity split, so computing host, app
        and facility as well made it four times as expensive for data nobody displays —
        slow enough on a large store to look like a hung widget."""
        s = _store()
        s.add_many([_rec(hostname='web01', app='nginx', severity=3, facility=4),
                    _rec(hostname='db01', app='mysqld', severity=6, facility=3)])
        st = s.stats(only=('severity',))
        assert st['total'] == 2                                # total is always computed
        assert [d['count'] for d in st['by_severity']] == [1, 1]
        # Omitted ones are empty, not missing — callers index them unconditionally.
        for key in ('by_host', 'by_app', 'by_facility'):
            assert st[key] == [], f'{key} was computed but not requested'

    def test_no_only_still_computes_everything(self):
        s = _store()
        s.add_many([_rec(hostname='web01', app='nginx', severity=3, facility=4)])
        st = s.stats()
        assert st['by_host'] and st['by_app'] and st['by_severity'] and st['by_facility']

    def test_stats_honour_filters(self):
        s = _store()
        s.add_many([_rec(hostname='a', severity=2), _rec(hostname='b', severity=6)])
        st = s.stats({'severity_max': 3})                      # only the severe one
        assert st['total'] == 1
        assert st['by_host'] == [{'value': 'a', 'count': 1}]

    def test_stats_empty(self):
        st = _store().stats()
        assert st['total'] == 0 and st['by_host'] == [] and st['by_severity'] == []

    def test_stats_faceting_keeps_own_dimension_options(self):
        # Selecting a severity must NOT collapse the By-severity breakdown — its
        # own filter is excluded so every option stays visible (multi-select).
        s = _store()
        s.add_many([_rec(severity=2, hostname='a'), _rec(severity=4, hostname='a'),
                    _rec(severity=6, hostname='b')])
        st = s.stats({'severity': [2]})
        assert {d['value'] for d in st['by_severity']} >= {2, 4, 6}   # all still shown
        assert st['by_host'] == [{'value': 'a', 'count': 1}]          # other facets apply it
        assert st['total'] == 1                                        # total applies everything

    def test_effective_host_falls_back_to_source(self):
        # A message with no parsed hostname is shown/grouped/filtered by its
        # source IP (effective host), consistently across facet/chart/filter.
        s = _store()
        s.add_many([_rec(hostname='h1', source='10.0.0.1'),
                    _rec(hostname='', source='192.168.200.10')])
        assert '192.168.200.10' in s.distinct('hostname')          # appears in the dropdown
        hosts = {d['value'] for d in s.stats()['by_host']}
        assert hosts == {'h1', '192.168.200.10'}                   # chart, no blank/—
        assert s.count({'hostname': '192.168.200.10'}) == 1        # filterable by the IP
        assert s.count({'hostname': 'h1'}) == 1

    def test_stats_multi_value(self):
        s = _store()
        s.add_many([_rec(hostname='a'), _rec(hostname='b'), _rec(hostname='c')])
        st = s.stats({'hostname': ['a', 'b']})
        assert st['total'] == 2
        # by_host excludes its own filter → all three hosts still listed
        assert {d['value'] for d in st['by_host']} == {'a', 'b', 'c'}
