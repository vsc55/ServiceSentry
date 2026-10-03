#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The audit cap, on every engine and after it is lowered.

The trim after each capped insert was ``DELETE FROM audit WHERE id = (SELECT MIN(id) FROM
audit)``. Two things were wrong with it:

* it names the table it deletes from inside its own subquery — MySQL 8 refuses that with error
  1093 (MariaDB and SQLite accept it), so on MySQL every capped insert raised after its row had
  been committed, and the table was never trimmed at all;
* it removed ONE row per insert, so a table above a cap that had just been lowered stayed above
  it for good — each insert added one and took one away.

And the monitor process passed a fixed 500 rather than the configured cap, which once the trim
honours the cap would cut a log the panel was told to keep at 5000 back to 500.

The suite runs on SQLite, so the store is driven through a wrapper that refuses the 1093 shape
the way MySQL 8 does.
"""

import re

from lib.config import ConfigControl
from lib.core.audit.store import AuditStore
from lib.db import get_connector
from lib.services.monitoring.monitor import Monitor

# DELETE FROM <t> … (SELECT … FROM <t> …): MySQL error 1093.
_SELF_SUBQUERY = re.compile(
    r'\bDELETE\s+FROM\s+(\S+)\s.*\(\s*SELECT\b.*\bFROM\s+\1(\s|\))', re.I | re.S)


class _MySQL8Strict:
    """An in-memory SQLite connector that rejects what MySQL 8 rejects with error 1093."""

    def __init__(self):
        self._db = get_connector(None, default_sqlite_path=':memory:')

    def execute(self, sql, params=()):
        if _SELF_SUBQUERY.search(sql):
            raise RuntimeError(f'(1093) You can\'t specify target table for update: {sql}')
        return self._db.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._db, name)


def _fill(st, n, *, cap=0, start=0):
    for i in range(start, start + n):
        st.insert(f'2026-01-01T00:00:{i:02d}Z', f'e{i}', 'u', 'ip', '', max_entries=cap)


class TestTheCapHolds:

    def test_a_capped_insert_works_where_mysql8_refuses_the_self_subquery(self):
        st = AuditStore(_MySQL8Strict())
        _fill(st, 8, cap=5)
        assert st.count() == 5
        assert [e['event'] for e in st.get_all()] == ['e7', 'e6', 'e5', 'e4', 'e3']

    def test_a_lowered_cap_is_reached_on_the_next_insert(self):
        st = AuditStore(get_connector(None, default_sqlite_path=':memory:'))
        _fill(st, 20)                       # no cap: all of them stay
        assert st.count() == 20
        _fill(st, 1, cap=5, start=20)       # the cap comes down to 5
        assert st.count() == 5
        assert [e['event'] for e in st.get_all()] == ['e20', 'e19', 'e18', 'e17', 'e16']

    def test_no_cap_keeps_everything(self):
        st = AuditStore(get_connector(None, default_sqlite_path=':memory:'))
        _fill(st, 12, cap=0)
        assert st.count() == 12


class TestTheMonitorUsesTheConfiguredCap:

    @staticmethod
    def _monitor(config):
        mon = object.__new__(Monitor)
        mon.config = ConfigControl(None, config)
        return mon

    def test_the_panel_setting_is_what_the_monitor_passes(self):
        mon = self._monitor({'web_admin': {'audit_max_entries': 5000}})
        assert mon._audit_max_entries() == 5000      # pylint: disable=protected-access

    def test_zero_still_means_no_limit(self):
        mon = self._monitor({'web_admin': {'audit_max_entries': 0}})
        assert mon._audit_max_entries() == 0         # pylint: disable=protected-access

    def test_without_the_setting_the_registry_default_applies(self):
        mon = self._monitor({})
        assert mon._audit_max_entries() == 500       # pylint: disable=protected-access

    def test_a_system_event_does_not_cut_a_larger_configured_log(self):
        mon = self._monitor({'web_admin': {'audit_max_entries': 5000}})
        mon._audit_store = AuditStore(get_connector(None, default_sqlite_path=':memory:'))
        _fill(mon._audit_store, 600)
        mon._audit_system('monitor_event')           # pylint: disable=protected-access
        assert mon._audit_store.count() == 601
