#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/datastore from the second 2026-10-12 audit (WF-9).

``connect_timeout`` bounds the handshake only: a MySQL server that accepted the connection
and then stalled held the check thread on the first read with no limit, and the PostgreSQL
metrics query had no statement timeout. The drivers are patched: no database is contacted.
"""

from unittest.mock import MagicMock, patch

import pytest

from watchfuls.datastore import deps
from watchfuls.datastore import engines

_TCP = {'conn_type': 'tcp', 'host': '192.0.2.10', 'user': 'u', 'password': 'p', 'db': 'd',
        'timeout': 7}


@pytest.mark.skipif(not deps._PYMYSQL, reason='PyMySQL not installed')
def test_mysql_connect_carries_read_and_write_timeouts():
    from watchfuls.datastore import Watchful
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    with patch('pymysql.connect', return_value=conn) as connect:
        ok, _msg, _m = Watchful._test_mysql({**_TCP, 'port': 3306})
    assert ok is True
    kw = connect.call_args.kwargs
    assert kw['read_timeout'] == kw['write_timeout'] == kw['connect_timeout'] == 7


def test_postgres_bounds_its_statements():
    from watchfuls.datastore import Watchful
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.return_value = (3, 100)
    fake = MagicMock()
    fake.connect.return_value = conn
    with patch.object(deps, '_PSYCOPG2', True), \
            patch.object(engines, 'psycopg2', fake, create=True):
        ok, _msg, metrics = Watchful._test_postgres({**_TCP, 'port': 5432, 'tls': False})
    assert ok is True and metrics == {'connections': 3, 'uptime': 100}
    first_sql, first_args = cur.execute.call_args_list[0].args
    assert first_sql.startswith('SET statement_timeout')
    assert first_args == (7000,)
    # A SET, not the `options` startup parameter, which pgbouncer refuses.
    assert 'options' not in fake.connect.call_args.kwargs
