#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""External syslog sources through the panel: configured, chosen, guarded, watched.

The registry and its store are pinned in `tests/unit/test_syslog_sources.py`; this is the
panel's half:

- a source is added, listed with its password masked, edited and removed through the API;
- the Syslog reads take `src=<uid>` and answer from that database, which is never cleared;
- an unknown source is a 404 and an unreachable one a 503 that says why;
- an external source needs `syslog_sources_all_view` or its own `syslogsrc.<uid>.view` —
  `syslog_view` alone is the internal one;
- removing a source drops the grants to it;
- a watched source feeds the event rules that name it, and only those.
"""

import sqlite3
import time
from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login
from tests.helpers import RSYSLOG_CREATE, STOCK_INSERT, rsyslog_utc

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_DISP = 'lib.core.notify.notification_dispatcher.dispatch'


def _rsyslog_file(path, rows=2):
    con = sqlite3.connect(str(path))
    con.execute(RSYSLOG_CREATE)
    for i in range(rows):
        con.execute(STOCK_INSERT, (f'from rsyslog {i}', 4, 'web01', 3, rsyslog_utc(time.time()),
                                   rsyslog_utc(time.time()), 1, 'sshd[812]:'))
    con.commit()
    con.close()
    return str(path)


def _add(client, path, **kw):
    body = {'name': 'rsyslog', 'enabled': True, 'watch': False, 'time_zone': 'UTC',
            'data': {'driver': 'sqlite', 'path': path}}
    body.update(kw)
    r = client.post('/api/v1/syslog/sources', json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()['uid']


class TestConfiguringASource:

    def test_add_list_edit_remove(self, client, admin, tmp_path):
        _login(client)
        uid = _add(client, _rsyslog_file(tmp_path / 'r.db'),
                   data={'driver': 'sqlite', 'path': str(tmp_path / 'r.db'),
                         'password': 'never-shown'})
        cfg = client.get('/api/v1/syslog/sources/config').get_json()['sources']
        assert [s['name'] for s in cfg] == ['rsyslog']
        assert cfg[0]['data']['password'] is None                  # masked
        offered = client.get('/api/v1/syslog/sources').get_json()['sources']
        assert [s['uid'] for s in offered] == ['internal', uid]
        r = client.put(f'/api/v1/syslog/sources/{uid}',
                       json={'name': 'renamed', 'data': {'driver': 'sqlite',
                                                         'path': str(tmp_path / 'r.db')}})
        assert r.status_code == 200
        # a null password kept the stored one
        assert admin._syslog_sources._store.get(uid)['data']['password'] == 'never-shown'
        with mock.patch.object(admin, '_purge_scoped_permissions') as purge:
            assert client.delete(f'/api/v1/syslog/sources/{uid}').status_code == 200
        purge.assert_called_once_with('syslogsrc', [uid])
        assert client.get('/api/v1/syslog/sources').get_json()['sources'] == [
            {'uid': 'internal', 'name': '', 'internal': True}]

    def test_a_source_needs_what_its_driver_needs(self, client):
        _login(client)
        assert client.post('/api/v1/syslog/sources', json={
            'name': 'x', 'data': {'driver': 'mysql'}}).status_code == 400
        assert client.post('/api/v1/syslog/sources', json={
            'name': '', 'data': {'driver': 'sqlite', 'path': 'x'}}).status_code == 400

    def test_the_connection_test_reports(self, client, tmp_path):
        _login(client)
        ok = client.post('/api/v1/syslog/sources/test', json={
            'data': {'driver': 'sqlite', 'path': _rsyslog_file(tmp_path / 'r.db', rows=3)}})
        assert ok.get_json()['ok'] and ok.get_json()['count'] == 3
        bad = client.post('/api/v1/syslog/sources/test', json={
            'data': {'driver': 'sqlite', 'path': str(tmp_path / 'absent.db')}})
        assert bad.get_json()['ok'] is False


class TestReadingASource:

    def test_the_reads_answer_from_it(self, client, tmp_path):
        _login(client)
        uid = _add(client, _rsyslog_file(tmp_path / 'r.db', rows=2))
        data = client.get(f'/api/v1/syslog?src={uid}').get_json()
        assert data['total'] == 2 and data['messages'][0]['app'] == 'sshd'
        assert client.get(f'/api/v1/syslog/stats?src={uid}').get_json()['total'] == 2
        assert client.get(f'/api/v1/syslog/facets?src={uid}').get_json()['hostname'] == ['web01']
        st = client.get(f'/api/v1/syslog/status?src={uid}').get_json()
        assert st['read_only'] is True and st['count'] == 2
        # and the internal one is untouched by it
        assert client.get('/api/v1/syslog').get_json()['total'] == 0

    def test_it_is_never_cleared(self, client, tmp_path):
        _login(client)
        uid = _add(client, _rsyslog_file(tmp_path / 'r.db', rows=2))
        r = client.delete(f'/api/v1/syslog?src={uid}')
        assert r.status_code == 409 and r.get_json()['error'] == 'syslog_read_only'
        assert client.get(f'/api/v1/syslog?src={uid}').get_json()['total'] == 2

    def test_unknown_and_unreachable_say_so(self, client, tmp_path):
        _login(client)
        assert client.get('/api/v1/syslog?src=nope').status_code == 404
        uid = _add(client, str(tmp_path / 'absent.db'))
        r = client.get(f'/api/v1/syslog?src={uid}')
        assert r.status_code == 503
        assert r.get_json()['error'] == 'syslog_source_unreachable'
        assert 'not found' in r.get_json()['detail']


class TestWhoMayReadIt:

    def test_syslog_view_alone_is_the_internal_source(self, client, admin, tmp_path):
        _login(client)
        uid = _add(client, _rsyslog_file(tmp_path / 'r.db'))
        with mock.patch.object(admin, '_get_session_permissions',
                               return_value=['syslog_view']):
            assert client.get(f'/api/v1/syslog?src={uid}').status_code == 403
            offered = client.get('/api/v1/syslog/sources').get_json()['sources']
            assert [s['uid'] for s in offered] == ['internal']
            assert client.get('/api/v1/syslog').status_code == 200

    def test_a_per_source_grant_opens_that_one(self, client, admin, tmp_path):
        _login(client)
        a = _add(client, _rsyslog_file(tmp_path / 'a.db'), name='a')
        b = _add(client, _rsyslog_file(tmp_path / 'b.db'), name='b')
        with mock.patch.object(admin, '_get_session_permissions',
                               return_value=['syslog_view', f'syslogsrc.{a}.view']):
            assert client.get(f'/api/v1/syslog?src={a}').status_code == 200
            assert client.get(f'/api/v1/syslog?src={b}').status_code == 403
            offered = client.get('/api/v1/syslog/sources').get_json()['sources']
            assert [s['uid'] for s in offered] == ['internal', a]


class TestTheRulesWatchIt:

    def _rule(self, client, log_source):
        r = client.post('/api/v1/event/rules', json={
            'name': f'r-{log_source or "internal"}', 'source': 'syslog',
            'log_source': log_source, 'channels': ['telegram']})
        assert r.status_code in (200, 201), r.get_json()

    def test_a_watched_source_feeds_the_rules_that_name_it(self, client, admin, tmp_path):
        _login(client)
        path = _rsyslog_file(tmp_path / 'r.db', rows=0)
        uid = _add(client, path, watch=True)
        self._rule(client, uid)
        self._rule(client, '')                 # the internal one: must not fire on these
        evsvc = admin._embedded_services['events']
        evsvc._is_leader = True
        evsvc._event_state.set_cursor(f'syslog:{uid}', 0)
        con = sqlite3.connect(path)
        con.execute(STOCK_INSERT, ('disk failure', 4, 'nas01', 2, rsyslog_utc(time.time()),
                                   rsyslog_utc(time.time()), 1, 'smartd[9]:'))
        con.commit()
        con.close()
        with mock.patch(_DISP) as disp:
            evsvc._event_worker_tick()
        assert disp.call_count == 1
        kw = disp.call_args.kwargs
        assert kw['module'] == 'syslog' and kw['item'] == 'nas01 (rsyslog)'
        assert evsvc._event_state.cursor(f'syslog:{uid}') == 1


class TestAStoredCredential:

    def test_a_source_logs_in_with_one_and_shows_in_its_usage(self, client, admin, tmp_path):
        _login(client)
        r = client.post('/api/v1/credentials', json={
            'name': 'rsyslog-ro', 'ctype': 'db',
            'data': {'db_user': 'reader', 'db_password': 'pw'}})
        assert r.status_code in (200, 201), r.get_json()
        cred = next(c for c in client.get('/api/v1/credentials').get_json()['credentials']
                    if c['name'] == 'rsyslog-ro')
        uid = _add(client, _rsyslog_file(tmp_path / 'r.db'),
                   data={'driver': 'sqlite', 'path': str(tmp_path / 'r.db'),
                         'cred_uid': cred['uid']})
        stored = admin._syslog_sources._store.get(uid)['data']
        assert stored['cred_uid'] == cred['uid']
        assert client.get(f'/api/v1/syslog?src={uid}').status_code == 200
        use = client.get(f"/api/v1/credentials/{cred['uid']}/usage").get_json()
        assert {'module': 'syslog', 'key': uid, 'label': 'rsyslog'} in use['checks']


class TestTheSyslogDatabaseInExternalMode:
    """`syslog_db|mode = external`: the panel's OWN syslog database is rsyslog's, only read —
    the listener does not start, the Services tab cannot start it, and clearing is refused."""

    @pytest.fixture
    def external(self, admin):
        from lib.db import get_connector
        from lib.services.syslog.store import SyslogStore
        db = get_connector(None, default_sqlite_path=':memory:')
        db.execute_ddl(RSYSLOG_CREATE)
        db.execute(STOCK_INSERT, ('from rsyslog', 4, 'web01', 6, rsyslog_utc(time.time()),
                                  rsyslog_utc(time.time()), 1, 'sshd[812]:'))
        db.commit()
        admin._write_config({'syslog': {'enabled': True}})
        admin._invalidate_config_cache()
        original = admin._syslog_store
        admin._syslog_store = SyslogStore(db, read_only=True)
        yield admin
        admin._syslog_store = original

    def test_the_page_lists_its_rows_and_says_so(self, client, external):
        _login(client)
        data = client.get('/api/v1/syslog').get_json()
        assert data['total'] == 1 and data['messages'][0]['app'] == 'sshd'
        st = client.get('/api/v1/syslog/status').get_json()
        assert st['read_only'] is True and st['running'] is False

    def test_clearing_is_refused(self, client, external):
        _login(client)
        r = client.delete('/api/v1/syslog')
        assert r.status_code == 409 and r.get_json()['error'] == 'syslog_read_only'
        assert external._syslog_store.count() == 1

    def test_the_listener_does_not_start(self, external, monkeypatch):
        monkeypatch.delenv('SS_SYSLOG_EMBEDDED', raising=False)   # this process would bind
        svc = external._embedded_services['syslog']
        assert svc.apply_config() == []
        assert svc.server is None
        assert svc.control('start') == (False, 'syslog_read_only')
        st = svc.status()
        assert st['controllable'] is False and st['running'] is False
        assert any(d.get('value_key') == 'svc_mode_syslog_read_only' for d in st['detail'])
