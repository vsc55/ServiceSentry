#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/web.py."""

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import create_mock_monitor


class TestWebInit:

    def test_init(self):
        from watchfuls.web import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.web': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.web'
        assert w.paths.find('curl') == '/usr/bin/curl'


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

        with patch.object(w, '_run_cmd', return_value="200"):
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

        with patch.object(w, '_run_cmd', return_value="500"):
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

        with patch.object(w, '_run_cmd', return_value="301"):
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

        with patch.object(w, '_run_cmd', return_value="404"):
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

        with patch.object(w, '_run_cmd', return_value="200"):
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

        with patch.object(w, '_run_cmd', return_value="200"):
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

        with patch.object(w, '_run_cmd', return_value="200"):
            result = w.check()
            items = result.list
            # default_enabled=True, así que se procesa
            assert 'example.com' in items
            assert items['example.com']['status'] is True