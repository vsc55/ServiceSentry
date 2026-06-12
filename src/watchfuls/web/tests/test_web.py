#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/web.py.

The per-item request helper is ``_web_request(url, timeout, verify_ssl, scheme,
method, check_content, content_contains, auth_user, auth_password)`` and returns
a ``(status_code, detail)`` tuple.  It also runs the SSRF guard
(``lib.net_guard.validate_external_url``) before the request — neutralised here
so tests stay hermetic (no DNS).
"""

from unittest.mock import MagicMock, patch

import pytest

from conftest import create_mock_monitor


@pytest.fixture(autouse=True)
def _no_ssrf_guard():
    """Neutralise the SSRF guard so direct _web_request tests don't hit DNS."""
    with patch('lib.net_guard.validate_external_url', return_value=None):
        yield


class TestWebInit:

    def test_init(self):
        from watchfuls.web import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.web': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.web'
        # curl is no longer used — native urllib is used instead
        assert w.paths.find('curl') == ''

    def test_schema_has_url(self):
        """ITEM_SCHEMA includes 'url' field."""
        from watchfuls.web import Watchful
        schema = Watchful.ITEM_SCHEMA['list']
        assert 'url' in schema
        assert schema['url']['default'] == ''
        assert schema['url']['type'] == 'str'


class TestWebCheck:

    def setup_method(self):
        from watchfuls.web import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        """Sin URLs configuradas, no hay resultados."""
        config = {'watchfuls.web': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        assert len(w.check().items()) == 0

    def test_check_disabled_url(self):
        """URL deshabilitada no se procesa."""
        config = {'watchfuls.web': {'list': {'example.com': False}}}
        w = self.Watchful(create_mock_monitor(config))
        assert len(w.check().items()) == 0

    def test_check_url_ok(self):
        """URL que retorna 200 = OK."""
        config = {'watchfuls.web': {'list': {'example.com': True}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')):
            items = w.check().list
            assert 'example.com' in items
            assert items['example.com']['status'] is True
            assert items['example.com']['other_data']['code'] == 200

    def test_check_url_500(self):
        """URL que retorna 500 = fallo."""
        config = {'watchfuls.web': {'list': {'example.com': True}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(500, 'HTTP 500')):
            assert w.check().list['example.com']['status'] is False

    def test_check_url_custom_code(self):
        """URL con código esperado personalizado."""
        config = {'watchfuls.web': {'list': {
            'example.com': {'enabled': True, 'code': 301},
        }}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(301, 'HTTP 301')):
            assert w.check().list['example.com']['status'] is True

    def test_check_url_404(self):
        """URL que retorna 404 = fallo."""
        config = {'watchfuls.web': {'list': {'example.com': True}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(404, 'HTTP 404')):
            items = w.check().list
            assert items['example.com']['status'] is False
            assert items['example.com']['other_data']['code'] == 404

    def test_check_multiple_urls(self):
        """Múltiples URLs se procesan."""
        config = {'watchfuls.web': {'list': {
            'example.com': True, 'google.com': True, 'disabled.com': False,
        }}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')):
            items = w.check().list
            assert 'example.com' in items
            assert 'google.com' in items
            assert 'disabled.com' not in items

    def test_check_url_enabled_dict(self):
        """URL habilitada con dict."""
        config = {'watchfuls.web': {'list': {'example.com': {'enabled': True}}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')):
            items = w.check().list
            assert 'example.com' in items
            assert items['example.com']['status'] is True

    def test_check_url_string_value_uses_default_enabled(self):
        """Valor string en config no hace match con bool() ni dict(), usa default_enabled=True."""
        config = {'watchfuls.web': {'list': {'example.com': 'some_string'}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')):
            items = w.check().list
            assert 'example.com' in items
            assert items['example.com']['status'] is True


class TestWebRequest:
    """Tests for _web_request using native urllib (returns (code, detail))."""

    def setup_method(self):
        from watchfuls.web import Watchful
        self.Watchful = Watchful

    def _make_watchful(self, config=None):
        return self.Watchful(create_mock_monitor(config or {'watchfuls.web': {}}))

    def _resp(self, status=200):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_successful_request(self):
        """200 response returns code 200."""
        w = self._make_watchful()
        with patch('urllib.request.urlopen', return_value=self._resp(200)):
            code, _ = w._web_request('example.com')
            assert code == 200

    def test_http_error_returns_code(self):
        """HTTPError returns the error status code."""
        import urllib.error
        w = self._make_watchful()
        with patch('urllib.request.urlopen',
                   side_effect=urllib.error.HTTPError(
                       'https://example.com', 503, 'Unavailable', {}, None)):
            code, _ = w._web_request('example.com')
            assert code == 503

    def test_url_error_returns_zero(self):
        """URLError (DNS failure, etc.) returns 0."""
        import urllib.error
        w = self._make_watchful()
        with patch('urllib.request.urlopen',
                   side_effect=urllib.error.URLError('DNS failure')):
            code, _ = w._web_request('example.com')
            assert code == 0

    def test_blocked_by_ssrf_guard_returns_zero(self):
        """A URL rejected by the SSRF guard returns code 0 without a request."""
        w = self._make_watchful()
        with patch('lib.net_guard.validate_external_url',
                   return_value='link-local / metadata address blocked'), \
             patch('urllib.request.urlopen') as mock_open:
            code, detail = w._web_request('http://169.254.169.254/')
            assert code == 0
            assert 'Blocked' in detail
            mock_open.assert_not_called()

    def test_url_with_scheme_preserved(self):
        """URL with explicit scheme is used as-is."""
        w = self._make_watchful()
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('http://example.com')
            req = mock_open.call_args[0][0]
            assert req.full_url.startswith('http://')

    def test_url_without_scheme_gets_https(self):
        """URL without scheme gets https:// prepended."""
        w = self._make_watchful()
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('example.com')
            req = mock_open.call_args[0][0]
            assert req.full_url.startswith('https://')


class TestWebUrl:
    """Tests for url field in the new data model."""

    def setup_method(self):
        from watchfuls.web import Watchful
        self.Watchful = Watchful

    def test_url_field_used_for_request(self):
        """Key es nombre descriptivo, url field contiene la dirección."""
        config = {'watchfuls.web': {'list': {
            'Mi Blog': {'enabled': True, 'url': 'example.com'}}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')) as mock_ret:
            result = w.check()
            assert 'Mi Blog' in result.list
            assert result.list['Mi Blog']['status'] is True
            assert mock_ret.call_args[0][0] == 'example.com'   # url, not key

    def test_backward_compat_key_as_url(self):
        """Sin campo url, el key se usa como URL (retrocompat)."""
        config = {'watchfuls.web': {'list': {'example.com': True}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')) as mock_ret:
            result = w.check()
            assert 'example.com' in result.list
            assert mock_ret.call_args[0][0] == 'example.com'

    def test_empty_url_falls_back_to_key(self):
        """url vacío usa el key como URL."""
        config = {'watchfuls.web': {'list': {
            'example.com': {'enabled': True, 'url': '  '}}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')) as mock_ret:
            result = w.check()
            assert 'example.com' in result.list
            assert mock_ret.call_args[0][0] == 'example.com'

    def test_key_used_in_message(self):
        """El mensaje usa el key (nombre descriptivo), no la url."""
        config = {'watchfuls.web': {'list': {
            'Blog': {'enabled': True, 'url': 'blog.example.com'}}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')):
            assert 'Blog' in w.check().list['Blog']['message']


class TestWebScheme:
    """Tests for scheme and verify_ssl fields."""

    def setup_method(self):
        from watchfuls.web import Watchful
        self.Watchful = Watchful

    def _resp(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_scheme_http_prepended_when_no_scheme_in_url(self):
        """When scheme='http', URLs without scheme get http:// prepended."""
        w = self.Watchful(create_mock_monitor({'watchfuls.web': {}}))
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('example.com', scheme='http')
            assert mock_open.call_args[0][0].full_url.startswith('http://')

    def test_scheme_default_is_https(self):
        """Without explicit scheme, URLs without :// get https://."""
        w = self.Watchful(create_mock_monitor({'watchfuls.web': {}}))
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('example.com')
            assert mock_open.call_args[0][0].full_url.startswith('https://')

    def test_explicit_scheme_in_url_overrides_scheme_param(self):
        """A URL that already contains :// is used as-is regardless of scheme param."""
        w = self.Watchful(create_mock_monitor({'watchfuls.web': {}}))
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('http://example.com', scheme='https')
            assert mock_open.call_args[0][0].full_url.startswith('http://')

    def test_verify_ssl_false_passes_ssl_context(self):
        """verify_ssl=False passes an SSL context that skips verification."""
        import ssl as ssl_mod
        w = self.Watchful(create_mock_monitor({'watchfuls.web': {}}))
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('https://example.com', verify_ssl=False)
            ctx = mock_open.call_args[1].get('context')
            assert isinstance(ctx, ssl_mod.SSLContext)
            assert ctx.verify_mode == ssl_mod.CERT_NONE

    def test_verify_ssl_true_does_not_pass_context(self):
        """verify_ssl=True (default) does not pass a custom SSL context."""
        w = self.Watchful(create_mock_monitor({'watchfuls.web': {}}))
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('https://example.com', verify_ssl=True)
            assert 'context' not in mock_open.call_args[1]

    def test_verify_ssl_false_not_applied_to_http(self):
        """verify_ssl=False has no effect for plain http:// URLs."""
        w = self.Watchful(create_mock_monitor({'watchfuls.web': {}}))
        with patch('urllib.request.urlopen', return_value=self._resp()) as mock_open:
            w._web_request('http://example.com', verify_ssl=False)
            assert 'context' not in mock_open.call_args[1]

    def test_scheme_field_read_from_config(self):
        """scheme field in item config is passed to _web_request (4th positional arg)."""
        config = {'watchfuls.web': {'list': {
            'my-site': {'enabled': True, 'url': 'example.com', 'scheme': 'http'}}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')) as mock_ret:
            w.check()
            # _web_request(url, timeout, verify_ssl, scheme, method, …)
            assert mock_ret.call_args[0][3] == 'http'

    def test_verify_ssl_field_read_from_config(self):
        """verify_ssl=False in item config is passed to _web_request (3rd positional arg)."""
        config = {'watchfuls.web': {'list': {
            'my-site': {'enabled': True, 'url': 'example.com', 'verify_ssl': False}}}}
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_request', return_value=(200, 'HTTP 200')) as mock_ret:
            w.check()
            assert mock_ret.call_args[0][2] is False

    def test_schema_has_scheme_and_verify_ssl(self):
        """Schema declares scheme and verify_ssl fields."""
        from watchfuls.web import Watchful
        schema = Watchful.ITEM_SCHEMA['list']
        assert 'scheme' in schema
        assert schema['scheme']['default'] == 'https'
        assert schema['scheme']['options'] == ['http', 'https']
        assert 'verify_ssl' in schema
        assert schema['verify_ssl']['default'] is True
        assert schema['verify_ssl']['show_when'] == {'scheme': ['https']}
