#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests para watchfuls/ram_swap.py."""

import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import create_mock_monitor


class TestRamSwapInit:

    def test_init(self):
        from watchfuls.ram_swap import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.ram_swap': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.ram_swap'


class TestRamSwapCheckConfig:

    def setup_method(self):
        from watchfuls.ram_swap import Watchful
        self.Watchful = Watchful

    def test_default_alert_values(self):
        """Sin configuración usa valores por defecto (60%)."""
        config = {'watchfuls.ram_swap': {}}
        mock_monitor = create_mock_monitor(config)
        w = self.Watchful(mock_monitor)
        # Los defaults internos son 60 para ram y swap
        assert w.get_conf('alert_ram', 60) == 60
        assert w.get_conf('alert_swap', 60) == 60


class TestRamSwapCheck:

    def setup_method(self):
        from watchfuls.ram_swap import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.ram_swap.Mem')
    def test_check_normal_usage(self, mock_mem_cls):
        """RAM y SWAP por debajo del umbral = OK."""
        config = {
            'watchfuls.ram_swap': {
                'alert_ram': 80,
                'alert_swap': 80,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mem = MagicMock()
        mock_mem.ram.used_percent = 40.0
        mock_mem.swap.used_percent = 20.0
        mock_mem_cls.return_value = mock_mem

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list

        assert 'ram' in items
        assert 'swap' in items
        assert items['ram']['status'] is True
        assert items['swap']['status'] is True
        assert 'Normal' in items['ram']['message']

    @patch('watchfuls.ram_swap.Mem')
    def test_check_high_ram_usage(self, mock_mem_cls):
        """RAM por encima del umbral = warning."""
        config = {
            'watchfuls.ram_swap': {
                'alert_ram': 60,
                'alert_swap': 60,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mem = MagicMock()
        mock_mem.ram.used_percent = 85.0
        mock_mem.swap.used_percent = 30.0
        mock_mem_cls.return_value = mock_mem

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list

        assert items['ram']['status'] is False
        assert items['swap']['status'] is True
        assert 'Excessive' in items['ram']['message']

    @patch('watchfuls.ram_swap.Mem')
    def test_check_high_swap_usage(self, mock_mem_cls):
        """SWAP por encima del umbral = warning."""
        config = {
            'watchfuls.ram_swap': {
                'alert_ram': 80,
                'alert_swap': 50,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mem = MagicMock()
        mock_mem.ram.used_percent = 40.0
        mock_mem.swap.used_percent = 60.0
        mock_mem_cls.return_value = mock_mem

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list

        assert items['ram']['status'] is True
        assert items['swap']['status'] is False

    @patch('watchfuls.ram_swap.Mem')
    def test_check_exact_threshold(self, mock_mem_cls):
        """Uso exactamente en el umbral = warning (>= alert)."""
        config = {
            'watchfuls.ram_swap': {
                'alert_ram': 60,
                'alert_swap': 60,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mem = MagicMock()
        mock_mem.ram.used_percent = 60.0
        mock_mem.swap.used_percent = 60.0
        mock_mem_cls.return_value = mock_mem

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list

        # >= alert → warning
        assert items['ram']['status'] is False
        assert items['swap']['status'] is False

    @patch('watchfuls.ram_swap.Mem')
    def test_check_other_data(self, mock_mem_cls):
        """other_data contiene used y alert."""
        config = {
            'watchfuls.ram_swap': {
                'alert_ram': 70,
                'alert_swap': 80,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mem = MagicMock()
        mock_mem.ram.used_percent = 50.0
        mock_mem.swap.used_percent = 30.0
        mock_mem_cls.return_value = mock_mem

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list

        assert items['ram']['other_data']['used'] == 50.0
        assert items['ram']['other_data']['alert'] == 70.0
        assert items['swap']['other_data']['used'] == 30.0
        assert items['swap']['other_data']['alert'] == 80.0

    @patch('watchfuls.ram_swap.Mem')
    def test_check_invalid_config_uses_default(self, mock_mem_cls):
        """Config inválida usa valor por defecto."""
        config = {
            'watchfuls.ram_swap': {
                'alert_ram': 'invalid',
                'alert_swap': -10,
            }
        }
        mock_monitor = create_mock_monitor(config)

        mock_mem = MagicMock()
        mock_mem.ram.used_percent = 50.0
        mock_mem.swap.used_percent = 30.0
        mock_mem_cls.return_value = mock_mem

        w = self.Watchful(mock_monitor)
        result = w.check()
        items = result.list
        # Usa defaults (60%), y 50% < 60% → OK
        assert items['ram']['status'] is True
        assert items['swap']['status'] is True
