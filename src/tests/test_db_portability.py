"""MySQL/PostgreSQL portability regression tests.

Production runs on MySQL and PostgreSQL, but the suite exercises SQLite (which tolerates
bare reserved-word identifiers). These tests drive each store against a recording stub
connector reporting ``KIND='mysql'`` (backtick quoting) and assert the raw SQL quotes the
reserved-word identifiers — so a future bare `key`/`virtual`/`groups`/`user` is caught here.
"""
import contextlib
import re

import pytest


class _RecConn:
    """Minimal BaseConnector-shaped stub that records every SQL string it's given."""
    KIND = 'mysql'

    def __init__(self):
        self.sql = []

    def quote_ident(self, name):
        return f'`{name}`'

    def reconcile_table(self, spec):
        pass

    def execute(self, sql, params=()):
        self.sql.append(sql); return 0

    def executemany(self, sql, params_list=()):
        self.sql.append(sql); return 0

    def fetchone(self, sql, params=()):
        self.sql.append(sql); return None

    def fetchall(self, sql, params=()):
        self.sql.append(sql); return []

    def commit(self):
        pass

    def last_insert_id(self):
        return 1

    @contextlib.contextmanager
    def transaction(self):
        yield


def _bare(word, sql):
    """True if *word* appears as a standalone identifier NOT wrapped in backticks."""
    return bool(re.search(rf'(?<![`\w]){word}(?![`\w])', sql))


def test_check_state_quotes_key_on_mysql():
    from lib.services.monitoring.check_state.store import CheckStateStore
    c = _RecConn(); s = CheckStateStore(c)
    s.get_all(); s.set('mod', 'k', True); s.delete('mod', 'k')
    s.persist_status({'mod': {'k': {'status': True}}})
    sql = '\n'.join(c.sql)
    assert '`key`' in sql and not _bare('key', sql)


def test_history_quotes_key_on_mysql():
    from lib.core.history.store import HistoryStore
    c = _RecConn(); s = HistoryStore(c)
    s.record('mod', 'k', status=True, data={})
    s.get_index(); s.query('mod', 'k', 0, 9); s.get_stats('mod', 'k', 0, 9)
    s.delete_series('mod', 'k')
    sql = '\n'.join(c.sql)
    assert '`key`' in sql and not _bare('key', sql)


def test_hosts_quotes_virtual_on_mysql():
    from lib.core.hosts.store import HostsStore
    c = _RecConn(); s = HostsStore(c)
    s.list(); s.get('x'); s.create({'name': 'n'}, actor='a'); s.update('x', {'name': 'n'}, actor='a')
    sql = '\n'.join(c.sql)
    assert '`virtual`' in sql and not _bare('virtual', sql)


def test_audit_quotes_user_on_mysql():
    from lib.core.audit.store import AuditStore
    c = _RecConn(); s = AuditStore(c)
    s.insert('ts', 'ev', 'bob', 'ip', {}); s.get_all(); s.query_since(0)
    sql = '\n'.join(c.sql)
    assert '`user`' in sql and not _bare('user', sql)


def test_groups_quotes_groups_table_on_mysql():
    from lib.core.groups.store import GroupsStore
    c = _RecConn(); s = GroupsStore(c)
    s.load(); s.count(); s.save_all({'u1': {'name': 'g', 'roles': ['r1']}})
    sql = '\n'.join(c.sql)
    assert '`groups`' in sql and not _bare('groups', sql)   # groups_roles is fine (compound)


def test_quote_ident_is_dialect_aware():
    from lib.db.sqlite import SQLiteConnector
    from lib.db.mysql import MySQLConnector
    from lib.db.postgresql import PostgreSQLConnector
    # instances not needed — quote_ident is a plain method over the class contract
    assert MySQLConnector.quote_ident(object(), 'key') == '`key`'
    assert SQLiteConnector.quote_ident(object(), 'key') == '"key"'
    assert PostgreSQLConnector.quote_ident(object(), 'key') == '"key"'
