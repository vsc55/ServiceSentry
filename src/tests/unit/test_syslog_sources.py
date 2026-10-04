#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""External syslog sources: the store that lists them, the registry that opens them.

A source is another program's log database (rsyslog's `SystemEvents`), only read. What must
hold, and what these pin:

- its password is encrypted at rest, and the connection keeps only the keys it knows;
- the registry opens a source once and reuses it, reopens it after an edit, refuses one that
  is switched off, and — when a source cannot be reached — says so without trying again on
  every request for a while;
- a SQLite source pointing at a missing file is refused rather than created empty;
- what a permission set may read: everything, some, or nothing;
- `syslogsrc.<uid>.view` is a permission the role editor can store.
"""

import sqlite3
import time

import pytest
from cryptography.fernet import Fernet

from lib.core.permissions import is_valid_perm
from lib.db import get_connector
from lib.services.syslog import sources as srcmod
from lib.services.syslog.store.sources import SyslogSourcesStore, clean_conn
from tests.helpers import RSYSLOG_CREATE, STOCK_INSERT, rsyslog_utc


def _main_db():
    return get_connector(None, default_sqlite_path=':memory:')


def _rsyslog_file(path, rows=1):
    """A SQLite file shaped like rsyslog's database, with *rows* stock-template rows."""
    con = sqlite3.connect(str(path))
    con.execute(RSYSLOG_CREATE)
    for i in range(rows):
        con.execute(STOCK_INSERT,
                    (f'm{i}', 4, 'web01', 6, rsyslog_utc(time.time()),
                     rsyslog_utc(time.time()), 1, 'sshd[1]:'))
    con.commit()
    con.close()
    return str(path)


def _source(path, **kw):
    base = {'name': 'rsyslog', 'enabled': True, 'watch': False, 'time_zone': 'UTC',
            'data': {'driver': 'sqlite', 'path': path}}
    base.update(kw)
    return base


class TestTheStore:

    def test_the_password_is_encrypted_at_rest(self):
        db = _main_db()
        store = SyslogSourcesStore(db, fernet=Fernet(Fernet.generate_key()))
        uid = store.create({'name': 'r', 'data': {'driver': 'mysql', 'host': 'h',
                                                  'name': 'Syslog', 'password': 's3cret'}})
        raw = db.fetchone('SELECT data FROM syslog_sources WHERE uid = ?', (uid,))[0]
        assert 's3cret' not in raw
        assert store.get(uid)['data']['password'] == 's3cret'

    def test_names_are_unique_and_required(self):
        store = SyslogSourcesStore(_main_db())
        assert store.create({'name': 'a'})
        assert store.create({'name': 'a'}) is None
        assert store.create({'name': ' '}) is None

    def test_the_connection_keeps_only_what_it_knows(self):
        c = clean_conn({'driver': 'oracle', 'host': ' h ', 'port': '99999', 'extra': 1})
        assert c['driver'] == 'mysql' and c['host'] == 'h' and c['port'] is None
        assert 'extra' not in c


class TestTheRegistry:

    def test_a_source_is_opened_once_and_read(self, tmp_path):
        store = SyslogSourcesStore(_main_db())
        uid = store.create(_source(_rsyslog_file(tmp_path / 'r.db', rows=2)))
        reg = srcmod.SyslogSources(store)
        s1 = reg.get(uid)
        assert s1.read_only and s1.count() == 2
        assert reg.get(uid) is s1

    def test_an_edit_reopens_it(self, tmp_path):
        store = SyslogSourcesStore(_main_db())
        uid = store.create(_source(_rsyslog_file(tmp_path / 'a.db', rows=1)))
        reg = srcmod.SyslogSources(store)
        assert reg.get(uid).count() == 1
        time.sleep(1.1)                       # updated_at has a one-second resolution
        store.update(uid, _source(_rsyslog_file(tmp_path / 'b.db', rows=3)))
        reg.invalidate()
        assert reg.get(uid).count() == 3

    def test_a_switched_off_or_unknown_source_is_not_opened(self, tmp_path):
        store = SyslogSourcesStore(_main_db())
        uid = store.create(_source(_rsyslog_file(tmp_path / 'r.db'), enabled=False))
        reg = srcmod.SyslogSources(store)
        with pytest.raises(KeyError):
            reg.get(uid)
        with pytest.raises(KeyError):
            reg.get('nope')

    def test_a_missing_sqlite_file_is_refused_not_created(self, tmp_path):
        store = SyslogSourcesStore(_main_db())
        path = tmp_path / 'absent.db'
        uid = store.create(_source(str(path)))
        reg = srcmod.SyslogSources(store)
        with pytest.raises(srcmod.SourceUnavailable):
            reg.get(uid)
        assert not path.exists()
        assert 'not found' in reg.errors[uid]

    def test_a_failure_is_not_retried_on_every_request(self, tmp_path, monkeypatch):
        store = SyslogSourcesStore(_main_db())
        uid = store.create(_source(str(tmp_path / 'absent.db')))
        reg = srcmod.SyslogSources(store)
        calls = []
        real = srcmod.open_source

        def counting(src, credentials=None):
            calls.append(1)
            return real(src, credentials)

        monkeypatch.setattr(srcmod, 'open_source', counting)
        for _ in range(3):
            with pytest.raises(srcmod.SourceUnavailable):
                reg.get(uid)
        assert len(calls) == 1

    def test_only_the_watched_ones_are_watched(self, tmp_path):
        store = SyslogSourcesStore(_main_db())
        a = store.create(_source(_rsyslog_file(tmp_path / 'a.db'), name='a', watch=True))
        store.create(_source(_rsyslog_file(tmp_path / 'b.db'), name='b'))
        store.create(_source(str(tmp_path / 'gone.db'), name='c', watch=True))
        reg = srcmod.SyslogSources(store)
        assert [w[0] for w in reg.watched()] == [a]

    def test_probe_says_what_it_found(self, tmp_path):
        ok = srcmod.probe(_source(_rsyslog_file(tmp_path / 'r.db', rows=2)))
        assert ok['ok'] and ok['has_table'] and ok['count'] == 2
        empty = tmp_path / 'empty.db'
        sqlite3.connect(str(empty)).close()
        res = srcmod.probe(_source(str(empty)))
        assert res['ok'] and not res['has_table'] and 'SystemEvents' in res['error']
        assert not srcmod.probe(_source(str(tmp_path / 'absent.db')))['ok']


class TestWhoMayReadWhat:

    def test_the_general_flag_grants_every_source(self):
        assert srcmod.visible({'syslog_view', 'syslog_sources_all_view'}) is None
        assert srcmod.may_see('anything', {'syslog_sources_all_view'})

    def test_a_per_source_grant_grants_that_one(self):
        perms = {'syslog_view', 'syslogsrc.abc.view'}
        assert srcmod.visible(perms) == {'abc'}
        assert srcmod.may_see('abc', perms) and not srcmod.may_see('xyz', perms)

    def test_syslog_view_alone_grants_no_external_source(self):
        assert srcmod.visible({'syslog_view'}) == set()

    def test_the_key_is_a_permission_a_role_can_hold(self):
        assert is_valid_perm('syslogsrc.0b5e-uid.view')
        assert not is_valid_perm('syslogsrc.0b5e-uid.edit')
        assert is_valid_perm('syslog_sources_all_view')


class TestTheConnection:

    def test_an_external_source_is_bounded_and_reads_in_autocommit(self):
        """An open transaction on somebody else's server holds a lock their DDL queues behind
        (see test_an_external_source_never_blocks_its_owners_ddl, live)."""
        cfg = srcmod.connector_config({'driver': 'mysql', 'host': 'h', 'name': 'Syslog',
                                       'password': ''})
        assert cfg['autocommit'] is True
        assert cfg['connect_timeout'] == 5 and cfg['read_timeout'] == 30
        assert 'password' not in cfg                 # an empty value is not sent at all


class TestAStoredCredential:
    """A source may log in with a stored "database" credential instead of its own fields."""

    class _Creds:
        def __init__(self, rows):
            self._rows = rows

        def get(self, uid):
            return self._rows.get(uid)

    def test_its_user_and_password_win(self):
        creds = self._Creds({'c1': {'uid': 'c1', 'name': 'ro', 'enabled': True,
                                    'data': {'db_user': 'reader', 'db_password': 'pw'}}})
        conn = srcmod.with_credential({'driver': 'mysql', 'user': 'typed', 'password': 'x',
                                       'cred_uid': 'c1'}, creds)
        assert (conn['user'], conn['password']) == ('reader', 'pw')
        assert 'cred_uid' not in srcmod.connector_config(conn)

    def test_a_missing_or_switched_off_credential_is_an_error_not_a_fallback(self):
        creds = self._Creds({'off': {'uid': 'off', 'name': 'old', 'enabled': False, 'data': {}}})
        with pytest.raises(srcmod.SourceUnavailable, match='not found'):
            srcmod.with_credential({'cred_uid': 'gone'}, creds)
        with pytest.raises(srcmod.SourceUnavailable, match='switched off'):
            srcmod.with_credential({'cred_uid': 'off'}, creds)

    def test_without_one_the_fields_are_used_as_typed(self):
        conn = {'driver': 'mysql', 'user': 'u', 'password': 'p'}
        assert srcmod.with_credential(conn, None) == conn

    def test_the_database_type_is_built_in_and_its_password_is_secret(self):
        from lib.modules.discovery.credential_schemas import credential_schemas
        from lib.security.secret_manager import ENCRYPT_KEYS
        db = credential_schemas()['db']
        assert db['builtin'] and [f['name'] for f in db['fields']] == ['db_user', 'db_password']
        assert 'db_password' in ENCRYPT_KEYS

    def test_a_credentials_usage_names_the_sources_using_it(self):
        from lib.core.credentials.service import find_all_credential_usage
        use = find_all_credential_usage([], {}, [{'uid': 's1', 'name': 'rsyslog',
                                                  'data': {'cred_uid': 'c1'}}])
        assert use['c1']['checks'] == [{'module': 'syslog', 'key': 's1', 'label': 'rsyslog'}]
