#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/web.py."""

from unittest.mock import MagicMock, patch

import pytest

from conftest import create_mock_monitor


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
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_url(self):
        """URL deshabilitada no se procesa."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': False
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_url_ok(self):
        """URL que retorna 200 = OK."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': True
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_web_return', return_value=200):
            result = w.check()
            items = result.list
            assert 'example.com' in items
            assert items['example.com']['status'] is True
            assert items['example.com']['other_data']['code'] == 200

    def test_check_url_500(self):
        """URL que retorna 500 = fallo."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': True
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_web_return', return_value=500):
            result = w.check()
            items = result.list
            assert items['example.com']['status'] is False

    def test_check_url_custom_code(self):
        """URL con código esperado personalizado."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': {
                        'enabled': True,
                        'code': 301,
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_web_return', return_value=301):
            result = w.check()
            items = result.list
            assert items['example.com']['status'] is True

    def test_check_url_404(self):
        """URL que retorna 404 = fallo."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': True
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_web_return', return_value=404):
            result = w.check()
            items = result.list
            assert items['example.com']['status'] is False
            assert items['example.com']['other_data']['code'] == 404

    def test_check_multiple_urls(self):
        """Múltiples URLs se procesan."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': True,
                    'google.com': True,
                    'disabled.com': False,
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_web_return', return_value=200):
            result = w.check()
            items = result.list
            assert 'example.com' in items
            assert 'google.com' in items
            assert 'disabled.com' not in items

    def test_check_url_enabled_dict(self):
        """URL habilitada con dict."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': {
                        'enabled': True,
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_web_return', return_value=200):
            result = w.check()
            items = result.list
            assert 'example.com' in items
            assert items['example.com']['status'] is True

    def test_check_url_string_value_uses_default_enabled(self):
        """Valor string en config no hace match con bool() ni dict(), usa default_enabled=True."""
        config = {
            'watchfuls.web': {
                'list': {
                    'example.com': 'some_string'
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_web_return', return_value=200):
            result = w.check()
            items = result.list
            # default_enabled=True, así que se procesa
            assert 'example.com' in items
            assert items['example.com']['status'] is True


class TestWebReturn:
    """Tests for _web_return using native urllib."""

    def setup_method(self):
        from watchfuls.web import Watchful
        self.Watchful = Watchful

    def _make_watchful(self, config=None):
        if config is None:
            config = {'watchfuls.web': {}}
        return self.Watchful(create_mock_monitor(config))

    def test_successful_request(self):
        """200 response returns 200."""
        w = self._make_watchful()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_resp):
            assert w._web_return('example.com') == 200

    def test_http_error_returns_code(self):
        """HTTPError returns the error status code."""
        import urllib.error
        w = self._make_watchful()
        with patch('urllib.request.urlopen',
                   side_effect=urllib.error.HTTPError(
                       'https://example.com', 503, 'Unavailable', {}, None)):
            assert w._web_return('example.com') == 503

    def test_url_error_returns_zero(self):
        """URLError (DNS failure, etc.) returns 0."""
        import urllib.error
        w = self._make_watchful()
        with patch('urllib.request.urlopen',
                   side_effect=urllib.error.URLError('DNS failure')):
            assert w._web_return('example.com') == 0

    def test_url_with_scheme_preserved(self):
        """URL with explicit scheme is used as-is."""
        w = self._make_watchful()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            w._web_return('http://example.com')
            # The Request URL should be http:// (not prepended with https://)
            req = mock_open.call_args[0][0]
            assert req.full_url.startswith('http://')

    def test_url_without_scheme_gets_https(self):
        """URL without scheme gets https:// prepended."""
        w = self._make_watchful()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            w._web_return('example.com')
            req = mock_open.call_args[0][0]
            assert req.full_url.startswith('https://')


class TestWebUrl:
    """Tests for url field in the new data model."""

    def setup_method(self):
        from watchfuls.web import Watchful
        self.Watchful = Watchful

    def test_url_field_used_for_request(self):
        """Key es nombre descriptivo, url field contiene la dirección."""
        config = {
            'watchfuls.web': {
                'list': {'Mi Blog': {'enabled': True, 'url': 'example.com'}}
            }
        }
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_return', return_value=200) as mock_ret:
            result = w.check()
            # El resultado se indexa por el key (nombre descriptivo)
            assert 'Mi Blog' in result.list
            assert result.list['Mi Blog']['status'] is True
            # _web_return recibe la url, no el key
            mock_ret.assert_called_once_with('example.com')

    def test_backward_compat_key_as_url(self):
        """Sin campo url, el key se usa como URL (retrocompat)."""
        config = {
            'watchfuls.web': {
                'list': {'example.com': True}
            }
        }
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_return', return_value=200) as mock_ret:
            result = w.check()
            assert 'example.com' in result.list
            mock_ret.assert_called_once_with('example.com')

    def test_empty_url_falls_back_to_key(self):
        """url vacío usa el key como URL."""
        config = {
            'watchfuls.web': {
                'list': {'example.com': {'enabled': True, 'url': '  '}}
            }
        }
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_return', return_value=200) as mock_ret:
            result = w.check()
            assert 'example.com' in result.list
            mock_ret.assert_called_once_with('example.com')

    def test_key_used_in_message(self):
        """El mensaje usa el key (nombre descriptivo), no la url."""
        config = {
            'watchfuls.web': {
                'list': {'Blog': {'enabled': True, 'url': 'blog.example.com'}}
            }
        }
        w = self.Watchful(create_mock_monitor(config))
        with patch.object(w, '_web_return', return_value=200):
            result = w.check()
            msg = result.list['Blog']['message']
            assert 'Blog' in msg
