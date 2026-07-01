#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the syslog API routes and the alert-rule evaluation."""

import time
from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _seed(admin, **kw):
    base = {'ts': time.time(), 'received_at': '2026-06-22T10:00:00Z', 'source': '10.0.0.1',
            'hostname': 'h1', 'app': 'sshd', 'procid': '1', 'severity': 6, 'facility': 4,
            'msgid': '', 'message': 'hello', 'raw': ''}
    base.update(kw)
    admin._syslog_store.add(base)


class TestSyslogApi:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/syslog').status_code == 401

    def test_list_empty(self, client):
        _login(client)
        r = client.get('/api/v1/syslog')
        assert r.status_code == 200
        assert r.get_json() == {'messages': [], 'total': 0}

    def test_list_and_filter(self, client, admin):
        _login(client)
        _seed(admin, message='boom error', severity=3, hostname='web01')
        _seed(admin, message='all good', severity=6, hostname='db03')
        data = client.get('/api/v1/syslog').get_json()
        assert data['total'] == 2
        # severity filter (err and worse)
        data = client.get('/api/v1/syslog?severity_max=3').get_json()
        assert data['total'] == 1 and data['messages'][0]['message'] == 'boom error'
        # host filter
        assert client.get('/api/v1/syslog?hostname=db03').get_json()['total'] == 1
        # text search
        assert client.get('/api/v1/syslog?q=error').get_json()['total'] == 1

    def test_sort_by_column(self, client, admin):
        _login(client)
        _seed(admin, hostname='aaa', severity=2, message='m1')
        _seed(admin, hostname='ccc', severity=6, message='m2')
        _seed(admin, hostname='bbb', severity=4, message='m3')
        # ascending by host
        hosts = [m['hostname'] for m in
                 client.get('/api/v1/syslog?sort=hostname&order=asc').get_json()['messages']]
        assert hosts == ['aaa', 'bbb', 'ccc']
        # descending by host
        hosts = [m['hostname'] for m in
                 client.get('/api/v1/syslog?sort=hostname&order=desc').get_json()['messages']]
        assert hosts == ['ccc', 'bbb', 'aaa']
        # ascending by severity (numeric)
        sevs = [m['severity'] for m in
                client.get('/api/v1/syslog?sort=severity&order=asc').get_json()['messages']]
        assert sevs == [2, 4, 6]
        # an unknown sort key falls back to ts (no error)
        assert client.get('/api/v1/syslog?sort=bogus&order=asc').status_code == 200

    def test_host_filter_matches_hostname_or_source(self, client, admin):
        _login(client)
        _seed(admin, hostname='pve01.lan', source='10.0.0.9', message='a')
        _seed(admin, hostname='', source='192.168.1.5', message='b')   # no hostname
        _seed(admin, hostname='other', source='10.0.0.1', message='c')
        # the per-server Logs tab passes ?host=<address> (FQDN or IP)
        assert client.get('/api/v1/syslog?host=pve01.lan').get_json()['total'] == 1
        assert client.get('/api/v1/syslog?host=192.168.1.5').get_json()['total'] == 1

    def test_multi_value_filter(self, client, admin):
        _login(client)
        _seed(admin, hostname='a', severity=2)
        _seed(admin, hostname='b', severity=4)
        _seed(admin, hostname='c', severity=6)
        # repeated params → IN (...) (Ctrl+click multi-select)
        assert client.get('/api/v1/syslog?hostname=a&hostname=b').get_json()['total'] == 2
        assert client.get('/api/v1/syslog?severity=2&severity=4').get_json()['total'] == 2
        # stats endpoint honours the same multi-select
        st = client.get('/api/v1/syslog/stats?hostname=a&hostname=b').get_json()
        assert st['total'] == 2

    def test_exact_severity_filter(self, client, admin):
        _login(client)
        _seed(admin, message='warn', severity=4)
        _seed(admin, message='crit', severity=2)
        _seed(admin, message='info', severity=6)
        # exact severity (clicking a By-severity bar) → only that level
        d = client.get('/api/v1/syslog?severity=4').get_json()
        assert d['total'] == 1 and d['messages'][0]['message'] == 'warn'
        # distinct from severity_max (≤): warning OR worse = warn + crit
        assert client.get('/api/v1/syslog?severity_max=4').get_json()['total'] == 2

    def test_pagination_offset_limit(self, client, admin):
        _login(client)
        for i in range(5):
            _seed(admin, message=f'm{i}', ts=1000 + i)   # ascending ts
        # newest first: m4..m0. Page size 2.
        p1 = client.get('/api/v1/syslog?limit=2&offset=0').get_json()
        assert p1['total'] == 5 and [m['message'] for m in p1['messages']] == ['m4', 'm3']
        p2 = client.get('/api/v1/syslog?limit=2&offset=2').get_json()
        assert [m['message'] for m in p2['messages']] == ['m2', 'm1']
        p3 = client.get('/api/v1/syslog?limit=2&offset=4').get_json()
        assert [m['message'] for m in p3['messages']] == ['m0']

    def test_date_range_filter(self, client, admin):
        _login(client)
        _seed(admin, message='old', ts=1000)
        _seed(admin, message='mid', ts=2000)
        _seed(admin, message='new', ts=3000)
        # since/until are unix seconds (inclusive)
        assert client.get('/api/v1/syslog?since=2000').get_json()['total'] == 2
        assert client.get('/api/v1/syslog?until=2000').get_json()['total'] == 2
        win = client.get('/api/v1/syslog?since=1500&until=2500').get_json()
        assert win['total'] == 1 and win['messages'][0]['message'] == 'mid'

    def test_facets(self, client, admin):
        _login(client)
        _seed(admin, hostname='a'); _seed(admin, hostname='b')
        facets = client.get('/api/v1/syslog/facets').get_json()
        assert set(facets['hostname']) == {'a', 'b'}

    def test_status(self, client):
        _login(client)
        st = client.get('/api/v1/syslog/status').get_json()
        assert st['enabled'] is False and st['running'] is False and 'count' in st

    def test_stats(self, client, admin):
        _login(client)
        _seed(admin, hostname='web01', app='nginx', severity=3)
        _seed(admin, hostname='web01', app='nginx', severity=6)
        _seed(admin, hostname='db01', app='mysqld', severity=4)
        st = client.get('/api/v1/syslog/stats').get_json()
        assert st['total'] == 3
        assert st['by_host'][0] == {'value': 'web01', 'count': 2}
        assert any(d['name'] == 'err' for d in st['by_severity'])
        # honours filters like the list endpoint
        st = client.get('/api/v1/syslog/stats?severity_max=3').get_json()
        assert st['total'] == 1 and st['by_host'] == [{'value': 'web01', 'count': 1}]

    def test_stats_requires_auth(self, client):
        assert client.get('/api/v1/syslog/stats').status_code == 401

    def test_clear(self, client, admin):
        _login(client)
        _seed(admin); _seed(admin)
        assert client.delete('/api/v1/syslog').get_json()['deleted'] == 2
        assert client.get('/api/v1/syslog').get_json()['total'] == 0


class TestSyslogCfgDefaults:

    def test_null_field_uses_registry_default(self, admin):
        # A blank (null) numeric field falls back to the registry default; an
        # explicit 0 is preserved (e.g. disable a transport).
        admin._write_config({'syslog': {'enabled': True, 'udp_port': None, 'tcp_port': 0}})
        admin._invalidate_config_cache()
        cfg = admin._embedded_services['syslog']._syslog_cfg()
        assert int(cfg['udp_port']) == 514     # null → default
        assert int(cfg['tcp_port']) == 0       # explicit 0 kept


class TestSyslogDrops:

    def test_drops_requires_auth(self, client):
        assert client.get('/api/v1/syslog/drops').status_code == 401

    def test_drops_endpoint(self, client, admin):
        _login(client)
        admin._syslog_drops_store.record('5.5.5.5', 'UDP', 4, 1000.0)
        admin._syslog_drops_store.record('6.6.6.6', 'TCP', 1, 1001.0)
        d = client.get('/api/v1/syslog/drops').get_json()
        assert d['sources'] == 2 and d['dropped'] == 5
        assert {x['source']: x['count'] for x in d['drops']} == {'5.5.5.5': 4, '6.6.6.6': 1}
        # delete a single source by its uid
        uid = next(x['uid'] for x in d['drops'] if x['source'] == '5.5.5.5')
        assert client.delete(f'/api/v1/syslog/drops/{uid}').get_json()['ok'] is True
        left = client.get('/api/v1/syslog/drops').get_json()
        assert left['sources'] == 1 and left['drops'][0]['source'] == '6.6.6.6'
        assert client.delete('/api/v1/syslog/drops/nope').status_code == 404
        # clear resets the tally
        assert client.delete('/api/v1/syslog/drops').get_json()['ok'] is True
        assert client.get('/api/v1/syslog/drops').get_json()['sources'] == 0


class TestSyslogAlert:
    """Syslog rule evaluation is decoupled: the listener only stores messages; the
    background event worker drains new rows by cursor and evaluates them (the match
    coverage lives in test_wa_events)."""

    def test_worker_evaluates_stored_messages(self, admin):
        evsvc = admin._embedded_services['events']
        evsvc._is_leader = True   # act as the active worker (tick is leader-gated)
        evsvc._event_state.set_cursor('syslog', 0)        # process from the start
        _seed(admin, severity=2, message='kernel panic')
        with mock.patch.object(evsvc, '_eval_event') as ev:
            evsvc._event_worker_tick()
        assert ev.call_count >= 1
        assert any(c.args[0] == 'syslog' for c in ev.call_args_list)
