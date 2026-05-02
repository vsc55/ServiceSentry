#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/temperature.py."""

from unittest.mock import MagicMock, patch

import pytest

from conftest import create_mock_monitor


class TestTemperatureInit:

    def test_init(self):
        from watchfuls.temperature import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.temperature': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.temperature'


class TestTemperatureCheck:

    def setup_method(self):
        from watchfuls.temperature import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_check_normal_temp(self, mock_thermal_cls):
        """Temperatura normal (por debajo del umbral) se marca OK."""
        config = {
            'watchfuls.temperature': {
                'alert': 80,
            }
        }
        mock_monitor = create_mock_monitor(config)

        # Simular sensor
        mock_node = MagicMock()
        mock_node.dev = 'thermal_zone0'
        mock_node.type = 'cpu-thermal'
        mock_node.temp = 45.0

        mock_thermal = MagicMock()
        mock_thermal.nodes = [mock_node]
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'thermal_zone0' in items
        assert items['thermal_zone0']['status'] is True
        assert 'Ok' in items['thermal_zone0']['message']

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_check_high_temp(self, mock_thermal_cls):
        """Temperatura alta (por encima del umbral) se marca como warning."""
        config = {
            'watchfuls.temperature': {
                'alert': 80,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_node = MagicMock()
        mock_node.dev = 'thermal_zone0'
        mock_node.type = 'cpu-thermal'
        mock_node.temp = 90.0

        mock_thermal = MagicMock()
        mock_thermal.nodes = [mock_node]
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'thermal_zone0' in items
        assert items['thermal_zone0']['status'] is False
        assert 'Warning' in items['thermal_zone0']['message']

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_check_exact_threshold(self, mock_thermal_cls):
        """Temperatura exactamente en el umbral es OK (<=)."""
        config = {
            'watchfuls.temperature': {
                'alert': 80,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_node = MagicMock()
        mock_node.dev = 'thermal_zone0'
        mock_node.type = 'cpu-thermal'
        mock_node.temp = 80.0

        mock_thermal = MagicMock()
        mock_thermal.nodes = [mock_node]
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert items['thermal_zone0']['status'] is True

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_check_no_sensors(self, mock_thermal_cls):
        """Sin sensores, sin resultados."""
        config = {'watchfuls.temperature': {}}
        mock_monitor = create_mock_monitor(config)

        mock_thermal = MagicMock()
        mock_thermal.nodes = []
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_check_multiple_sensors(self, mock_thermal_cls):
        """Múltiples sensores se procesan independientemente."""
        config = {
            'watchfuls.temperature': {
                'alert': 80,
            }
        }
        mock_monitor = create_mock_monitor(config)

        node1 = MagicMock()
        node1.dev = 'thermal_zone0'
        node1.type = 'cpu-thermal'
        node1.temp = 45.0

        node2 = MagicMock()
        node2.dev = 'thermal_zone1'
        node2.type = 'gpu-thermal'
        node2.temp = 95.0

        mock_thermal = MagicMock()
        mock_thermal.nodes = [node1, node2]
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert items['thermal_zone0']['status'] is True
        assert items['thermal_zone1']['status'] is False

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_check_disabled_sensor(self, mock_thermal_cls):
        """Sensor deshabilitado en config no se reporta."""
        config = {
            'watchfuls.temperature': {
                'alert': 80,
                'list': {
                    'thermal_zone0': {
                        'enabled': False,
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_node = MagicMock()
        mock_node.dev = 'thermal_zone0'
        mock_node.type = 'cpu-thermal'
        mock_node.temp = 45.0

        mock_thermal = MagicMock()
        mock_thermal.nodes = [mock_node]
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_other_data_contains_temp_info(self, mock_thermal_cls):
        """other_data contiene type, temp y alert."""
        config = {
            'watchfuls.temperature': {
                'alert': 80,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_node = MagicMock()
        mock_node.dev = 'thermal_zone0'
        mock_node.type = 'cpu-thermal'
        mock_node.temp = 45.0

        mock_thermal = MagicMock()
        mock_thermal.nodes = [mock_node]
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        other = items['thermal_zone0']['other_data']
        assert other['type'] == 'cpu-thermal'
        assert other['temp'] == 45.0
        assert 'alert' in other


class TestTemperatureGetConf:

    def setup_method(self):
        from watchfuls.temperature import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.temperature.ThermalInfoCollection')
    def test_get_conf_custom_label(self, mock_thermal_cls):
        """Sensor con label personalizado en config."""
        config = {
            'watchfuls.temperature': {
                'alert': 80,
                'list': {
                    'thermal_zone0': {
                        'enabled': True,
                        'label': 'CPU Core',
                    }
                }
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_node = MagicMock()
        mock_node.dev = 'thermal_zone0'
        mock_node.type = 'cpu-thermal'
        mock_node.temp = 45.0

        mock_thermal = MagicMock()
        mock_thermal.nodes = [mock_node]
        mock_thermal_cls.return_value = mock_thermal

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        assert 'CPU Core' in items['thermal_zone0']['message']

    def test_get_conf_none_raises_value_error(self):
        """opt_find=None lanza ValueError."""
        config = {'watchfuls.temperature': {}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(ValueError, match="can not be None"):
            w._get_conf(None, 'thermal_zone0')

    def test_get_conf_invalid_option_raises_type_error(self):
        """opt_find inválido lanza TypeError."""
        from enum import IntEnum

        class FakeOption(IntEnum):
            invalid = 999

        config = {'watchfuls.temperature': {}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(TypeError, match="is not valid option"):
            w._get_conf(FakeOption.invalid, 'thermal_zone0')
