#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The row caps and the history ceiling, run against a connector that refuses what MySQL does.

SQLite accepts two things MySQL and MariaDB reject, and both were used to trim a table inside
the same transaction as the write that grew it:

* ``DELETE … WHERE k IN (SELECT … LIMIT n)`` — MySQL error 1093, MariaDB 1235. The ban list
  (5000) and the syslog drop sources (500) trimmed this way, so once a table reached its cap
  the INSERT rolled back with the trim and nothing new was ever stored again;
* ``LIMIT -1 OFFSET n`` — SQLite's "no limit". The job history ceiling used it, and the
  age-based DELETE beside it rolled back too, so the history grew for ever.

The suite runs on SQLite, which would have passed both. So the stores are driven through a
wrapper that raises on exactly those two shapes, the way the real engines do; the live check
against a real MariaDB/MySQL is in ``tests/e2e/test_db_portability_live.py``.
"""

import re
import time

import pytest

from lib.core.jobs.history import JobHistoryStore
from lib.db import get_connector
from lib.services.ipban.store import bans as bans_mod
from lib.services.syslog.store import drops as drops_mod

_REFUSED = (
    re.compile(r'\bIN\s*\(\s*SELECT\b[^()]*\bLIMIT\b', re.I | re.S),
    re.compile(r'\bLIMIT\s+-\s*1\b', re.I),
)


class _MySQLStrict:
    """An in-memory SQLite connector that rejects the SQL MySQL/MariaDB reject."""

    def __init__(self):
        self._db = get_connector(None, default_sqlite_path=':memory:')

    @staticmethod
    def _check(sql):
        for rx in _REFUSED:
            if rx.search(sql):
                raise RuntimeError(f'refused by MySQL/MariaDB: {sql}')

    def execute(self, sql, params=()):
        self._check(sql)
        return self._db.execute(sql, params)

    def fetchone(self, sql, params=()):
        self._check(sql)
        return self._db.fetchone(sql, params)

    def fetchall(self, sql, params=()):
        self._check(sql)
        return self._db.fetchall(sql, params)

    def __getattr__(self, name):
        return getattr(self._db, name)


def _ban(ts):
    return {'reason': 'r', 'category': 'auth', 'level': 1, 'offenses': 1,
            'banned_at': ts, 'until': None, 'first_seen': ts, 'by': 'system'}


class TestTheBanListKeepsTakingBansWhenFull:

    def test_a_new_ban_is_stored_past_the_cap(self, monkeypatch):
        monkeypatch.setattr(bans_mod, '_MAX_ROWS', 3)
        st = bans_mod.BansStore(_MySQLStrict())
        for i in range(5):
            st.upsert(f'10.0.0.{i}', _ban(1000.0 + i))
        ips = sorted(r['ip'] for r in st.query())
        assert ips == ['10.0.0.2', '10.0.0.3', '10.0.0.4'], \
            'the newest bans were rolled back with the trim'


class TestTheDropTallyKeepsTakingSourcesWhenFull:

    def test_a_new_source_is_stored_past_the_cap(self, monkeypatch):
        monkeypatch.setattr(drops_mod, '_MAX_ROWS', 3)
        st = drops_mod.SyslogDropsStore(_MySQLStrict())
        for i in range(5):
            st.record(f'10.0.0.{i}', 'udp', 1, 1000.0 + i)
        srcs = sorted(r['source'] for r in st.query())
        assert srcs == ['10.0.0.2', '10.0.0.3', '10.0.0.4'], \
            'the newest sources were rolled back with the trim'


def _job(jid, ended):
    return {'id': jid, 'kind': 'collect', 'source': 'infra', 'label': jid,
            'state': 'done', 'started': ended - 1, 'ended': ended, 'done': 1, 'total': 1,
            'error': ''}


class TestTheJobHistoryShrinksOnEveryEngine:

    def test_the_ceiling_and_the_age_limit_both_apply(self):
        st = JobHistoryStore(_MySQLStrict())
        now = time.time()
        st.record(_job('old', now - 40 * 86400))
        for i in range(6):
            st.record(_job(f'x{i}', now - 100 + i))
        assert st.prune(keep=4, days=30) == 3
        assert [r['job_id'] for r in st.list()] == ['x5', 'x4', 'x3', 'x2']

    def test_a_running_job_is_not_pruned_from_under_itself(self):
        """A row still open has ended_at 0, sorts last newest-first and was the first one the
        ceiling deleted — under the job that was about to close it."""
        st = JobHistoryStore(_MySQLStrict())
        now = time.time()
        for i in range(3):
            st.record(_job(f'x{i}', now - 100 + i))
        uid = st.begin({'id': 'live', 'kind': 'collect', 'label': 'live',
                        'started': now})
        assert uid
        st.prune(keep=2, days=0)
        assert st.get(uid) is not None, 'the running row was pruned'
        assert st.count() == 2


@pytest.mark.parametrize('rx_sql', [
    'DELETE FROM t WHERE ip IN (SELECT ip FROM t ORDER BY a ASC LIMIT ?)',
    'SELECT uid FROM t ORDER BY ended_at DESC LIMIT -1 OFFSET ?',
])
def test_the_strict_connector_really_refuses_them(rx_sql):
    """The wrapper is what makes the tests above mean anything: if it stopped refusing, they
    would pass against the broken SQL too."""
    with pytest.raises(RuntimeError):
        _MySQLStrict._check(rx_sql)
