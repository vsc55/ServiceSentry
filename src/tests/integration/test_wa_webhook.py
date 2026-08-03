#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the Webhook notification module and webhook API routes.

Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_wa_webhook.py`` lives in ``tests/unit/test_wa_webhook.py``."""

import unittest.mock

import pytest

try:
    from lib.web_admin import WebAdmin
    from lib.core.notify.webhook import notify as webhook_notify
    from lib.core.notify.webhook import channel as webhook_channel
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
        webhook_channel.get_store(admin._notify).upsert({
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
    """Integration tests for /api/v1/notify/webhooks CRUD endpoints."""

    def _create(self, client, **kwargs):
        payload = {
            'name': 'Test Hook',
            'enabled': True,
            'url': 'https://hooks.example.com/test',
            'method': 'POST',
            'timeout': 5,
            **kwargs,
        }
        return client.post('/api/v1/notify/webhooks', json=payload)

    def test_create_requires_auth(self, client):
        resp = client.post('/api/v1/notify/webhooks', json={})
        assert resp.status_code == 401

    def test_list_requires_auth(self, client):
        resp = client.get('/api/v1/notify/webhooks')
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

        resp2 = client.get('/api/v1/notify/webhooks')
        assert resp2.status_code == 200
        ids = [w['id'] for w in resp2.get_json()['webhooks']]
        assert wh['id'] in ids

    def test_create_missing_url_fails(self, admin, client):
        _login(client)
        resp = client.post('/api/v1/notify/webhooks', json={'name': 'X', 'enabled': True})
        assert resp.status_code == 400

    def test_update(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        resp = client.put(f'/api/v1/notify/webhooks/{wh_id}', json={
            'name': 'Updated', 'url': 'https://hooks.example.com/v2',
            'method': 'PUT', 'timeout': 10,
        })
        assert resp.status_code == 200
        assert resp.get_json()['webhook']['name'] == 'Updated'

    def test_delete(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        resp = client.delete(f'/api/v1/notify/webhooks/{wh_id}')
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True
        ids = [w['id'] for w in client.get('/api/v1/notify/webhooks').get_json()['webhooks']]
        assert wh_id not in ids

    def test_delete_not_found(self, admin, client):
        _login(client)
        resp = client.delete('/api/v1/notify/webhooks/nonexistent-id')
        assert resp.status_code == 404

    def test_test_by_id(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            resp = client.post(f'/api/v1/notify/webhooks/{wh_id}/test', json={})
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

    def test_test_by_id_not_found(self, admin, client):
        _login(client)
        resp = client.post('/api/v1/notify/webhooks/no-such-id/test', json={})
        assert resp.status_code == 404

    def test_secret_masked_in_list(self, admin, client):
        _login(client)
        self._create(client, secret='supersecret')
        webhooks = client.get('/api/v1/notify/webhooks').get_json()['webhooks']
        assert webhooks[-1]['secret'] is None  # masked

    def test_audit_on_create(self, admin, client):
        _login(client)
        self._create(client)
        events = [e['event'] for e in admin._audit_log]
        assert 'webhook_created' in events

    def test_audit_on_delete(self, admin, client):
        _login(client)
        wh_id = self._create(client).get_json()['webhook']['id']
        client.delete(f'/api/v1/notify/webhooks/{wh_id}')
        events = [e['event'] for e in admin._audit_log]
        assert 'webhook_deleted' in events
