#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the event-rules manager: CRUD API + matching/dispatch."""

from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_DISP = 'lib.core.notify.notification_dispatcher.dispatch'


class TestEventsEnabled:
    """events|enabled is the on/off master switch (uniform with monitoring/syslog);
    the legacy events|mode is honoured for backward compat."""

    def test_enabled_default_true(self, admin):
        assert admin._embedded_services['events']._events_enabled() is True

    def test_disabled_idles_and_stops(self, admin):
        ev = admin._embedded_services['events']
        admin._write_config({'events': {'enabled': False}})
        admin._invalidate_config_cache()
        assert ev._events_enabled() is False
        ev._is_leader = True
        assert ev._event_worker_tick() == 0        # disabled → processes nothing

    def test_legacy_mode_off_maps_to_disabled(self, admin):
        # An old config carrying events|mode='off' (no events|enabled) reads disabled.
        admin._write_config({'events': {'mode': 'off'}})
        admin._invalidate_config_cache()
        assert admin._embedded_services['events']._events_enabled() is False

    def test_legacy_mode_embedded_maps_to_enabled(self, admin):
        admin._write_config({'events': {'mode': 'embedded'}})
        admin._invalidate_config_cache()
        assert admin._embedded_services['events']._events_enabled() is True

    def test_explicit_enabled_wins_over_legacy_mode(self, admin):
        admin._write_config({'events': {'enabled': True, 'mode': 'off'}})
        admin._invalidate_config_cache()
        assert admin._embedded_services['events']._events_enabled() is True


class TestEventRulesApi:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/event-rules').status_code == 401

    def test_crud(self, client):
        _login(client)
        assert client.get('/api/v1/event-rules').get_json()['rules'] == []
        r = client.post('/api/v1/event-rules', json={
            'name': 'Failed logins', 'source': 'audit',
            'events': ['login_failed'], 'channels': ['telegram']})
        assert r.status_code == 200
        rid = r.get_json()['rule']['id']
        rules = client.get('/api/v1/event-rules').get_json()['rules']
        assert len(rules) == 1 and rules[0]['name'] == 'Failed logins'
        # update
        r = client.put(f'/api/v1/event-rules/{rid}', json={
            'name': 'Renamed', 'source': 'audit',
            'events': ['login_failed'], 'channels': ['telegram', 'email']})
        assert r.status_code == 200 and r.get_json()['rule']['name'] == 'Renamed'
        # delete
        assert client.delete(f'/api/v1/event-rules/{rid}').status_code == 200
        assert client.get('/api/v1/event-rules').get_json()['rules'] == []

    def test_promoted_columns(self, admin, client):
        """name/enabled/description are first-class columns, not buried in data."""
        _login(client)
        rid = client.post('/api/v1/event-rules', json={
            'name': 'Promo', 'description': 'a note', 'enabled': False,
            'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram']}).get_json()['rule']['id']
        # round-trips through the flat public dict
        rule = client.get('/api/v1/event-rules').get_json()['rules'][0]
        assert rule['name'] == 'Promo' and rule['description'] == 'a note'
        assert rule['enabled'] is False
        # and they live in their own columns (the data blob does not carry them)
        row = admin._db_connector.fetchone(
            'SELECT name, enabled, description, data FROM event_rules WHERE uid=?', (rid,))
        assert row[0] == 'Promo' and row[1] == 0 and row[2] == 'a note'
        import json
        blob = json.loads(row[3])
        assert 'name' not in blob and 'enabled' not in blob and 'description' not in blob
        assert blob['source'] == 'audit'

    def test_validation(self, client):
        _login(client)
        # no channels
        assert client.post('/api/v1/event-rules', json={
            'source': 'audit', 'events': ['x'], 'channels': []}).status_code == 400
        # audit with no events
        assert client.post('/api/v1/event-rules', json={
            'source': 'audit', 'events': [], 'channels': ['telegram']}).status_code == 400
        # bad regex (syslog)
        assert client.post('/api/v1/event-rules', json={
            'source': 'syslog', 'match_type': 'regex', 'match_text': '(',
            'channels': ['telegram']}).status_code == 400


class TestEventMatching:

    def test_audit_event_fires_rule(self, admin, client):
        _login(client)
        client.post('/api/v1/event-rules', json={
            'name': 'r', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram']})
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {'user': 'bob'}})
        assert disp.called
        assert disp.call_args.kwargs['kind'] == 'event'
        assert disp.call_args.kwargs['channels'] == ['telegram']

    def test_non_matching_audit_event_does_not_fire(self, admin, client):
        _login(client)
        client.post('/api/v1/event-rules', json={
            'name': 'r', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram']})
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_ok', 'user': 'system', 'detail': {}})
        assert not disp.called

    def test_disabled_rule_does_not_fire(self, admin, client):
        _login(client)
        client.post('/api/v1/event-rules', json={
            'name': 'r', 'enabled': False, 'source': 'audit',
            'events': ['login_failed'], 'channels': ['telegram']})
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {}})
        assert not disp.called

    def test_syslog_rule_matches_by_severity(self, admin, client):
        _login(client)
        client.post('/api/v1/event-rules', json={
            'name': 's', 'source': 'syslog', 'severity_max': 3,
            'channels': ['webhook']})
        rec_err = {'severity': 2, 'severity_name': 'crit', 'hostname': 'h',
                   'source': '1.1.1.1', 'app': 'x', 'message': 'boom', 'received_at': ''}
        rec_info = {**rec_err, 'severity': 6, 'message': 'fine'}
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('syslog',rec_err)
            assert disp.called and disp.call_args.kwargs['channels'] == ['webhook']
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('syslog',rec_info)        # severity 6 > 3 → no match
            assert not disp.called

    def test_cooldown_suppresses_second(self, admin, client):
        _login(client)
        client.post('/api/v1/event-rules', json={
            'name': 'r', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram'], 'cooldown': 60})
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {}})
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {}})
        assert disp.call_count == 1

    def test_blank_cooldown_inherits_global(self, admin, client):
        _login(client)
        admin._write_config({'events': {'cooldown': 600}})
        admin._invalidate_config_cache()
        client.post('/api/v1/event-rules', json={      # no cooldown → inherit global
            'name': 'g', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram']})
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {}})
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {}})
        assert disp.call_count == 1                     # global cooldown suppresses the 2nd

    def test_explicit_zero_overrides_global(self, admin, client):
        _login(client)
        admin._write_config({'events': {'cooldown': 600}})
        admin._invalidate_config_cache()
        client.post('/api/v1/event-rules', json={      # explicit 0 → no cooldown
            'name': 'z', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram'], 'cooldown': 0})
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {}})
            admin._embedded_services['events']._eval_event('audit', {'event': 'login_failed', 'user': 'system', 'detail': {}})
        assert disp.call_count == 2                     # 0 overrides the global default


class TestMatchTypes:

    @pytest.mark.parametrize('match_type,text,should_fire', [
        ('contains', 'disk is full', True),
        ('contains', 'all good', False),
        ('not_contains', 'all good', True),
        ('not_contains', 'disk is full', False),
        ('starts', 'disk failure ahead', True),
        ('starts', 'a disk failure', False),
        ('ends', 'ahead disk', True),
        ('ends', 'disk ahead', False),
        ('regex', 'err-42 raised', True),
        ('regex', 'no digits', False),
        ('any', 'whatever', True),
    ])
    def test_syslog_text_match(self, admin, client, match_type, text, should_fire):
        _login(client)
        needle = {'contains': 'full', 'not_contains': 'full', 'starts': 'disk',
                  'ends': 'disk', 'regex': r'err-\d+', 'any': ''}[match_type]
        r = client.post('/api/v1/event-rules', json={
            'name': 'm', 'source': 'syslog', 'match_type': match_type,
            'match_text': needle, 'channels': ['webhook']})
        assert r.status_code == 200
        rec = {'severity': 5, 'severity_name': 'notice', 'hostname': 'h',
               'source': '1.1.1.1', 'app': 'x', 'message': text, 'received_at': ''}
        with mock.patch(_DISP) as disp:
            admin._embedded_services['events']._eval_event('syslog',rec)
        assert disp.called is should_fire


class TestNotificationLog:

    def test_log_records_test_send_and_last_fired(self, client):
        _login(client)
        rid = client.post('/api/v1/event-rules', json={
            'name': 'r', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram']}).get_json()['rule']['id']
        with mock.patch(_DISP, return_value={'telegram': (True, 'sent')}):
            assert client.post(f'/api/v1/event-rules/{rid}/test').status_code == 200
        # the send is logged
        log = client.get('/api/v1/notifications/log').get_json()
        assert log['total'] == 1
        assert log['log'][0]['rule_name'] == 'r' and log['log'][0]['ok'] == 1
        # and the rule carries a last_fired / last_ok
        rule = client.get('/api/v1/event-rules').get_json()['rules'][0]
        assert rule['last_fired'] and rule['last_ok'] is True
        # clearing empties it
        assert client.delete('/api/v1/notifications/log').status_code == 200
        assert client.get('/api/v1/notifications/log').get_json()['total'] == 0

    def test_log_records_failure(self, client):
        _login(client)
        rid = client.post('/api/v1/event-rules', json={
            'name': 'r', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram']}).get_json()['rule']['id']
        with mock.patch(_DISP, return_value={'telegram': (False, 'boom')}):
            client.post(f'/api/v1/event-rules/{rid}/test')
        entry = client.get('/api/v1/notifications/log').get_json()['log'][0]
        assert entry['ok'] == 0 and 'boom' in entry['message']


class TestDispatcherChannels:

    def test_channels_override_targets_only_those(self, admin):
        # channels override ignores the notifications matrix
        from lib.core.notify.telegram import notify as telegram_notify; from lib.core.notify.webhook import notify as webhook_notify
        from lib.core.notify.notification_dispatcher import dispatch
        with mock.patch.object(telegram_notify, '_dispatch', return_value=(True, 'ok')) as tg, \
             mock.patch.object(webhook_notify, 'send_all', return_value=(True, 'ok')) as wh:
            res = dispatch(admin, kind='event', channels=['telegram'])
        assert tg.called and not wh.called
        assert set(res) == {'telegram'}

    def test_webhook_ids_restrict_destinations(self, admin):
        # A non-empty webhook_ids only notifies the matching enabled webhooks.
        from lib.core.notify.webhook import notify as webhook_notify
        from lib.core.notify.notification_dispatcher import dispatch
        hooks = [{'id': 'w1', 'name': 'one', 'url': 'http://a', 'enabled': True},
                 {'id': 'w2', 'name': 'two', 'url': 'http://b', 'enabled': True}]
        sent = []
        with mock.patch.object(admin, '_load_webhooks', return_value=hooks), \
             mock.patch.object(webhook_notify, '_dispatch',
                               side_effect=lambda wh, **k: (sent.append(wh['id']) or (True, 'ok'))):
            dispatch(admin, kind='event', channels=['webhook'], webhook_ids=['w2'])
        assert sent == ['w2']

    def test_empty_webhook_ids_targets_all(self, admin):
        from lib.core.notify.webhook import notify as webhook_notify
        from lib.core.notify.notification_dispatcher import dispatch
        hooks = [{'id': 'w1', 'name': 'one', 'url': 'http://a', 'enabled': True},
                 {'id': 'w2', 'name': 'two', 'url': 'http://b', 'enabled': True}]
        sent = []
        with mock.patch.object(admin, '_load_webhooks', return_value=hooks), \
             mock.patch.object(webhook_notify, '_dispatch',
                               side_effect=lambda wh, **k: (sent.append(wh['id']) or (True, 'ok'))):
            dispatch(admin, kind='event', channels=['webhook'], webhook_ids=[])
        assert sorted(sent) == ['w1', 'w2']


class TestEventWorker:
    """Decoupled worker: consumes new syslog/audit rows by cursor and evaluates the
    same rules off the ingestion path; cooldown is persisted across restarts."""

    def test_worker_consumes_audit_by_cursor(self, admin, client):
        _login(client)
        client.post('/api/v1/event-rules', json={
            'name': 'w', 'source': 'audit', 'events': ['login_failed'],
            'channels': ['telegram']})
        ev = admin._embedded_services['events']
        ev._is_leader = True   # act as the active worker (tick is leader-gated)
        ev._event_state.set_cursor('audit', 0)        # process from the start
        admin._audit_system('login_failed', detail={})   # decoupled: only stores a row
        with mock.patch(_DISP) as disp:
            processed = ev._event_worker_tick()
        assert processed >= 1
        assert disp.called                                # the worker fired the rule

    def test_cooldown_is_persisted(self, admin):
        admin._embedded_services['events']._event_state.set_cooldown('rule-x', 123.0)
        assert admin._embedded_services['events']._event_state.cooldowns().get('rule-x') == 123.0


class TestEventDetailStr:
    """The audit detail rendered into a notification body must be empty when there is
    no detail — an empty dict must NOT render as a literal "{}" (e.g. syslog_started
    audits with {})."""

    @pytest.mark.parametrize('detail,expected', [
        (None, ''),
        ('', ''),
        ({}, ''),
        ([], ''),
        ('boom', 'boom'),
        ({'deleted': 3}, '{"deleted": 3}'),
    ])
    def test_detail_str(self, detail, expected):
        from lib.services.events.manager import _EventsMixin
        assert _EventsMixin._event_detail_str(detail) == expected
