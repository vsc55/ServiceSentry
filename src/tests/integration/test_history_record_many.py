#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`HistoryStore.record_many`: a cycle's samples in batches, as `record` writes each.

What a cycle writes at its end is one sample per result of every module —sixteen thousand on
the demo's SNMP fleet— and a commit each was most of the cycle on SQLite. Batched, they must be
EXACTLY what one-by-one wrote: the same samples, measurements, series summary and identity; a
batch that fails costs only the sample that could not be written; a series another process
deleted meanwhile is created again. On a SQLite store over a temporary file.
"""

import pytest

from lib.core.history.store import HistoryStore
from lib.db import get_connector


@pytest.fixture()
def two(tmp_path):
    a = HistoryStore(get_connector(None, default_sqlite_path=str(tmp_path / 'a.db')))
    b = HistoryStore(get_connector(None, default_sqlite_path=str(tmp_path / 'b.db')))
    return a, b


def _recs(n):
    return [('snmp', f'host.d{i % 7}/eth{i % 3}', i % 5 != 0,
             {'if_in': float(i), 'if_oper': 1, '_row': f'eth{i % 3}',
              '_attrs': {'if': {'mac': f'02:00:00:00:00:{i % 7:02d}'}}})
            for i in range(n)]


def _view(store):
    out = {}
    for s in store.get_index():
        pts = store.query(s['module'], s['key'], 0, 2 ** 40, max_points=0)
        out[(s['module'], s['key'])] = (s.get('count'), s.get('uptime'),
                                        s.get('last_status'),
                                        [(p['status'], {k: v for k, v in (p.get('data') or {})
                                                        .items()}) for p in pts])
    return out


def test_the_same_as_one_by_one(two, monkeypatch):
    a, b = two
    monkeypatch.setattr(HistoryStore, 'MANY_CHUNK', 7)        # several batches and a remainder
    recs = _recs(50)
    for r in recs:
        a.record(*r)
    assert b.record_many(recs) == 50
    assert _view(a) == _view(b) and len(_view(b)) == 21


def test_fewer_commits(two, monkeypatch):
    _a, b = two
    commits = []
    real = type(b._db).commit                                   # noqa: SLF001
    monkeypatch.setattr(type(b._db), 'commit', lambda self: commits.append(1) or real(self))
    b.record_many(_recs(50))                                    # every series exists now
    commits.clear()
    b.record_many(_recs(400))
    assert len(commits) <= 400 // HistoryStore.MANY_CHUNK + 1


def test_a_batch_that_fails_costs_only_its_bad_sample(two, monkeypatch):
    _a, b = two
    recs = _recs(10)
    real = b.facts.write

    def write(sid, ts, medidas, strict=False):
        if medidas.get('if_in') == 4.0:
            raise RuntimeError('this one cannot be written')
        return real(sid, ts, medidas, strict=strict)
    monkeypatch.setattr(b.facts, 'write', write)
    assert b.record_many(recs) == 10
    total = sum(v[0] or 0 for v in _view(b).values())
    assert total == 9                                           # all but the bad one


def test_a_series_deleted_meanwhile_is_created_again(two):
    _a, b = two
    b.record_many(_recs(3))
    key = _recs(3)[0][1]
    from lib.core.history import store as hstore
    # As another process would: the row gone, this store's cache of its id still there.
    b._db.execute(f'DELETE FROM {hstore._TS} WHERE {b._qk} = ?', (key,))   # noqa: SLF001
    b._db.commit()                                                          # noqa: SLF001
    b.record_many(_recs(3))
    assert ('snmp', key) in _view(b)
