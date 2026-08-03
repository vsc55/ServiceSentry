#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the Webhook notification module and webhook API routes.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_webhook.py`` lives in ``tests/integration/test_wa_webhook.py``."""

import hashlib
import hmac
import json
import unittest.mock


from lib.core.notify.webhook import notify as webhook_notify


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

    def test_ssrf_rejects_non_http_scheme(self):
        ok, msg = webhook_notify._dispatch({'enabled': True, 'url': 'file:///etc/passwd'})
        assert not ok
        assert 'rejected' in msg.lower()

    def test_ssrf_rejects_metadata_address(self):
        ok, msg = webhook_notify._dispatch(
            {'enabled': True, 'url': 'http://169.254.169.254/latest/meta-data/'})
        assert not ok
        assert 'rejected' in msg.lower()

    def test_ssrf_allows_internal_target(self):
        # A monitoring tool legitimately posts to internal/private endpoints; only
        # link-local/metadata and non-http(s) schemes are blocked (see net_guard).
        cfg = {**_ENABLED_CFG, 'url': 'http://127.0.0.1:9000/hook'}
        with unittest.mock.patch('requests.post') as mock_post:
            mock_post.return_value = unittest.mock.Mock(status_code=200)
            ok, _ = webhook_notify._dispatch(cfg, kind='down')
        assert ok
        mock_post.assert_called_once()

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


# ──────────────────────── Webhook CRUD routes ──────────────────────────────

