#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the Webhook notification module and webhook API routes."""

import hashlib
import hmac
import json
import unittest.mock

import pytest

try:
    from lib.web_admin import WebAdmin
    from lib.core.notify.webhook import notify as webhook_notify
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')

_ENABLED_CFG = {
    'enabled': True,
    'url': 'https://hooks.example.com/notify',
    'method': 'POST',
    'timeout': 5,
}


# ──────────────────────── webhook_notify._dispatch ─────────────────────────

class TestWebhookDispatch:
    """Unit tests for webhook_notify._dispatch()."""

    def test_disabled_returns_error(self):
        ok, msg = webhook_notify._dispatch({'enabled': False, 'url': 'https://x.com'})
        assert not ok
        assert 'not enabled' in msg.lower()

    def test_no_url_returns_error(self):
        ok, msg = webhook_notify._dispatch({'enabled': True, 'url': ''})
        assert not ok
        assert 'url' in msg.lower()

    def test_no_requests_package(self, monkeypatch):
        monkeypatch.setattr(webhook_notify, '_HAS_REQUESTS', False)
        ok, msg = webhook_notify._dispatch(_ENABLED_CFG)
        assert not ok
        assert 'requests' in msg.lower()

    def test_post_success(self):
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            ok, msg = webhook_notify._dispatch(_ENABLED_CFG, kind='down', item='svc')
        assert ok
        assert '200' in msg
        mock_post.assert_called_once()

    def test_put_method(self):
        cfg = {**_ENABLED_CFG, 'method': 'PUT'}
        with unittest.mock.patch('requests.put') as mock_put:
            mock_put.return_value = unittest.mock.Mock(status_code=201)
            ok, msg = webhook_notify._dispatch(cfg)
        assert ok
        mock_put.assert_called_once()

    def test_get_method(self):
        cfg = {**_ENABLED_CFG, 'method': 'GET',
               'url': 'https://hooks.example.com/notify?k={kind}'}
        with unittest.mock.patch('requests.get') as mock_get:
            mock_get.return_value = unittest.mock.Mock(status_code=200)
            ok, _ = webhook_notify._dispatch(cfg, kind='down')
        assert ok
        called_url = mock_get.call_args[0][0]
        assert 'down' in called_url

    def test_http_error_returns_failure(self):
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=500)
            ok, msg = webhook_notify._dispatch(_ENABLED_CFG)
        assert not ok
        assert '500' in msg

    def test_network_exception(self):
        with unittest.mock.patch('requests.post', side_effect=ConnectionError('refused')):
            ok, msg = webhook_notify._dispatch(_ENABLED_CFG)
        assert not ok
        assert 'refused' in msg

    def test_placeholder_substitution(self):
        cfg = {**_ENABLED_CFG, 'body_template': '{kind}:{item}:{status}'}
        captured = {}
        def fake_post(url, data, headers, timeout):
            captured['body'] = data
            return unittest.mock.Mock(status_code=200)
        with unittest.mock.patch('requests.post', side_effect=fake_post):
            webhook_notify._dispatch(cfg, kind='down', item='api', status='DOWN')
        assert captured['body'] == b'down:api:DOWN'

    def test_default_body_template_used_when_empty(self):
        cfg = {**_ENABLED_CFG, 'body_template': ''}
        captured = {}
        def fake_post(url, data, headers, timeout):
            captured['body'] = data
            return unittest.mock.Mock(status_code=200)
        with unittest.mock.patch('requests.post', side_effect=fake_post):
            webhook_notify._dispatch(cfg, kind='test', module='m', item='i',
                                     status='TEST', message='msg', timestamp='ts')
        payload = json.loads(captured['body'])
        assert payload['kind'] == 'test'
        assert payload['module'] == 'm'
        assert payload['item'] == 'i'

    def test_hmac_signature_added(self):
        cfg = {**_ENABLED_CFG, 'secret': 'mysecret', 'secret_header': 'X-Sig'}
        captured_headers = {}
        body_tpl = '{"kind":"{kind}"}'
        cfg['body_template'] = body_tpl
        def fake_post(url, data, headers, timeout):
            captured_headers.update(headers)
            return unittest.mock.Mock(status_code=200)
        with unittest.mock.patch('requests.post', side_effect=fake_post):
            webhook_notify._dispatch(cfg, kind='down')
        assert 'X-Sig' in captured_headers
        sig_value = captured_headers['X-Sig']
        assert sig_value.startswith('sha256=')
        expected_body = b'{"kind":"down"}'
        expected_sig = 'sha256=' + hmac.new(
            b'mysecret', expected_body, hashlib.sha256
        ).hexdigest()
        assert sig_value == expected_sig

    def test_custom_headers_merged(self):
        cfg = {**_ENABLED_CFG, 'headers': '{"X-Custom": "value123"}'}
        captured_headers = {}
        def fake_post(url, data, headers, timeout):
            captured_headers.update(headers)
            return unittest.mock.Mock(status_code=200)
        with unittest.mock.patch('requests.post', side_effect=fake_post):
            webhook_notify._dispatch(cfg)
        assert captured_headers.get('X-Custom') == 'value123'
        assert 'Content-Type' in captured_headers

    def test_invalid_headers_json_returns_error(self):
        cfg = {**_ENABLED_CFG, 'headers': 'not-json'}
        ok, msg = webhook_notify._dispatch(cfg)
        assert not ok
        assert 'json' in msg.lower()


# ──────────────────── /api/v1/notify/webhook/test endpoint ─────────────────

class TestWebhookArbitraryTest:
    """Integration tests for the generic webhook test endpoint."""

    def test_requires_auth(self, client):
        resp = client.post('/api/v1/notify/webhook/test', json={})
        assert resp.status_code == 401

    def test_viewer_denied(self, admin, client):
        from werkzeug.security import generate_password_hash
        admin._users['vwr'] = {
            'password_hash': generate_password_hash('pass'),
            'role': 'viewer',
        }
        _login(client, 'vwr', 'pass')
        resp = client.post('/api/v1/notify/webhook/test', json={})
        assert resp.status_code == 403

    def test_success_returns_ok(self, admin, client):
        _login(client)
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            resp = client.post('/api/v1/notify/webhook/test', json={
                'enabled': True,
                'url': 'https://hooks.example.com/test',
                'method': 'POST',
                'timeout': 5,
            })
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

    def test_disabled_returns_ok_false(self, client):
        _login(client)
        resp = client.post('/api/v1/notify/webhook/test', json={'enabled': False})
        data = resp.get_json()
        assert resp.status_code == 200
        assert data['ok'] is False

    def test_stored_secret_kept_on_null(self, admin, client):
        """Sending id + secret=null merges the stored secret from the webhooks store."""
        admin._webhooks_store.upsert({
            'id': 'test-wh-id',
            'enabled': True,
            'url': 'https://hooks.example.com/test',
            'method': 'POST',
            'timeout': 5,
            'secret': 'stored-secret',
            'secret_header': 'X-Hub-Signature-256',
        })
        _login(client)
        captured_headers = {}
        def fake_post(url, data, headers, timeout):
            captured_headers.update(headers)
            return unittest.mock.Mock(status_code=200)
        with unittest.mock.patch('requests.post', side_effect=fake_post):
            resp = client.post('/api/v1/notify/webhook/test', json={
                'id': 'test-wh-id',
                'enabled': True, 'url': 'https://hooks.example.com/test',
                'method': 'POST', 'timeout': 5,
                'secret': None,  # null = keep stored
            })
        assert resp.get_json()['ok'] is True
        assert 'X-Hub-Signature-256' in captured_headers

    def test_audit_ok_on_success(self, admin, client):
        _login(client)
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            client.post('/api/v1/notify/webhook/test', json={
                'enabled': True,
                'url': 'https://hooks.example.com/test',
            })
        events = [e['event'] for e in admin._audit_log]
        assert 'webhook_test_ok' in events

    def test_audit_fail_on_error(self, admin, client):
        _login(client)
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=500)
            client.post('/api/v1/notify/webhook/test', json={
                'enabled': True,
                'url': 'https://hooks.example.com/test',
            })
        events = [e['event'] for e in admin._audit_log]
        assert 'webhook_test_fail' in events
        entry = [e for e in admin._audit_log if e['event'] == 'webhook_test_fail'][-1]
        assert 'error' in entry['detail']


# ──────────────────────── Webhook CRUD routes ──────────────────────────────

class TestWebhookCRUD:
    """Integration tests for /api/v1/webhooks CRUD endpoints."""

    def _create(self, client, **kwargs):
        payload = {
            'name': 'Test Hook',
            'enabled': True,
            'url': 'https://hooks.example.com/test',
            'method': 'POST',
            'timeout': 5,
            **kwargs,
        }
        return client.post('/api/v1/webhooks', json=payload)

    def test_create_requires_auth(self, client):
        resp = client.post('/api/v1/webhooks', json={})
        assert resp.status_code == 401

    def test_list_requires_auth(self, client):
        resp = client.get('/api/v1/webhooks')
        assert resp.status_code == 401

    def test_create_and_list(self, admin, client):
        _login(client)
        resp = self._create(client)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        wh = data['webhook']
        assert wh['name'] == 'Test Hook'
        assert 'id' in wh

        resp2 = client.get('/api/v1/webhooks')
        assert resp2.status_code == 200
        ids = [w['id'] for w in resp2.get_json()['webhooks']]
        assert wh['id'] in ids

    def test_create_missing_url_fails(self, admin, client):
        _login(client)
        resp = client.post('/api/v1/webhooks', json={'name': 'X', 'enabled': True})
        assert resp.status_code == 400

    def test_update(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        resp = client.put(f'/api/v1/webhooks/{wh_id}', json={
            'name': 'Updated', 'url': 'https://hooks.example.com/v2',
            'method': 'PUT', 'timeout': 10,
        })
        assert resp.status_code == 200
        assert resp.get_json()['webhook']['name'] == 'Updated'

    def test_delete(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        resp = client.delete(f'/api/v1/webhooks/{wh_id}')
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True
        ids = [w['id'] for w in client.get('/api/v1/webhooks').get_json()['webhooks']]
        assert wh_id not in ids

    def test_delete_not_found(self, admin, client):
        _login(client)
        resp = client.delete('/api/v1/webhooks/nonexistent-id')
        assert resp.status_code == 404

    def test_test_by_id(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            resp = client.post(f'/api/v1/webhooks/{wh_id}/test', json={})
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

    def test_test_by_id_not_found(self, admin, client):
        _login(client)
        resp = client.post('/api/v1/webhooks/no-such-id/test', json={})
        assert resp.status_code == 404

    def test_secret_masked_in_list(self, admin, client):
        _login(client)
        self._create(client, secret='supersecret')
        webhooks = client.get('/api/v1/webhooks').get_json()['webhooks']
        assert webhooks[-1]['secret'] is None  # masked

    def test_audit_on_create(self, admin, client):
        _login(client)
        self._create(client)
        events = [e['event'] for e in admin._audit_log]
        assert 'webhook_created' in events

    def test_audit_on_delete(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        client.delete(f'/api/v1/webhooks/{wh_id}')
        events = [e['event'] for e in admin._audit_log]
        assert 'webhook_deleted' in events
