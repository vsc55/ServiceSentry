#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/ping.py."""

from unittest.mock import patch

import pytest

from tests.conftest import create_mock_monitor


class TestPingInit:

    def test_init(self):
        from watchfuls.ping import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.ping': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.ping'
        assert w.paths.find('ping') == '/bin/ping'


class TestPingCheck:

    def setup_method(self):
        from watchfuls.ping import Watchful
        self.Watchful = Watchful

    def test_check_empty_list(self):
        """Sin hosts configurados, no hay resultados."""
        config = {'watchfuls.ping': {'list': {}}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.list) == 0

    def test_check_disabled_host(self):
        """Host deshabilitado no se procesa."""
        config = {
            'watchfuls.ping': {
                'list': {
                    '192.168.1.1': False
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    def test_check_host_enabled_bool(self):
        """Host habilitado con booleano se procesa."""
        config = {
            'watchfuls.ping': {
                'list': {
                    '192.168.1.1': True
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Mock _run_cmd para simular ping exitoso (exit_code=0)
        with patch.object(w, '_run_cmd', return_value=("", 0)):
            result = w.check()
            items = result.list
            assert '192.168.1.1' in items
            assert items['192.168.1.1']['status'] is True

    def test_check_host_ping_fails(self):
        """Ping fallido se marca como fallo."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'timeout': 1,
                'list': {
                    '192.168.1.99': True
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        # Mock _run_cmd para simular ping fallido (exit_code=1)
        with patch.object(w, '_run_cmd', return_value=("", 1)):
            result = w.check()
            items = result.list
            assert '192.168.1.99' in items
            assert items['192.168.1.99']['status'] is False

    def test_check_host_with_label(self):
        """Host con label personalizado."""
        config = {
            'watchfuls.ping': {
                'list': {
                    '192.168.1.1': {
                        'enabled': True,
                        'label': 'Router',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=("", 0)):
            result = w.check()
            items = result.list
            assert '192.168.1.1' in items
            # El mensaje debe contener "Router"
            assert 'Router' in items['192.168.1.1']['message']

    def test_check_multiple_hosts(self):
        """Múltiples hosts se procesan."""
        config = {
            'watchfuls.ping': {
                'attempt': 1,
                'list': {
                    '192.168.1.1': True,
                    '192.168.1.2': True,
                    '192.168.1.3': False,
                }
            }
        }
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)

        with patch.object(w, '_run_cmd', return_value=("", 0)):
            result = w.check()
            items = result.list
            assert '192.168.1.1' in items
            assert '192.168.1.2' in items
            assert '192.168.1.3' not in items  # Deshabilitado


class TestPingConfigOptions:

    def test_config_options_enum(self):
        from watchfuls.ping import ConfigOptions
        assert hasattr(ConfigOptions, 'enabled')
        assert hasattr(ConfigOptions, 'label')
        assert hasattr(ConfigOptions, 'timeout')
        assert hasattr(ConfigOptions, 'attempt')


class TestPingGetConf:

    def setup_method(self):
        from watchfuls.ping import ConfigOptions, Watchful
        self.Watchful = Watchful
        self.ConfigOptions = ConfigOptions

    def test_get_conf_none_raises_value_error(self):
        """opt_find=None lanza ValueError."""
        config = {'watchfuls.ping': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(ValueError, match="can not be None"):
            w._get_conf(None, '192.168.1.1')

    def test_get_conf_invalid_option_raises_type_error(self):
        """opt_find inválido lanza TypeError."""
        from enum import IntEnum

        class FakeOption(IntEnum):
            invalid = 999

        config = {'watchfuls.ping': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(TypeError, match="is not valid option"):
            w._get_conf(FakeOption.invalid, '192.168.1.1')
