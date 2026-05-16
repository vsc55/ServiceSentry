#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/cpu."""

import pytest
from unittest.mock import patch, MagicMock
from conftest import create_mock_monitor


class TestCpuInit:

    def test_init(self):
        from watchfuls.cpu import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.cpu': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.cpu'


class TestCpuCheck:

    def setup_method(self):
        from watchfuls.cpu import Watchful
        self.Watchful = Watchful

    def test_check_disabled_returns_empty(self):
        """Disabled module returns empty dict_return."""
        config = {'watchfuls.cpu': {'enabled': False}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.cpu.psutil.cpu_percent', return_value=40.0)
    def test_check_ok_below_threshold(self, mock_cpu):
        """CPU usage below alert threshold → status True."""
        config = {'watchfuls.cpu': {'alert': 85, 'interval': 1.0}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'cpu' in items
        assert items['cpu']['status'] is True
        assert 'Normal' in items['cpu']['message']
        mock_cpu.assert_called_once_with(interval=1.0)

    @patch('watchfuls.cpu.psutil.cpu_percent', return_value=90.0)
    def test_check_alert_above_threshold(self, mock_cpu):
        """CPU usage above alert threshold → status False."""
        config = {'watchfuls.cpu': {'alert': 85, 'interval': 1.0}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['cpu']['status'] is False
        assert 'Excessive' in items['cpu']['message']

    @patch('watchfuls.cpu.psutil.cpu_percent', return_value=85.0)
    def test_check_exact_threshold_is_not_ok(self, mock_cpu):
        """Usage exactly at threshold (not strictly below) → status False."""
        config = {'watchfuls.cpu': {'alert': 85, 'interval': 1.0}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['cpu']['status'] is False

    @patch('watchfuls.cpu.psutil.cpu_percent', return_value=55.0)
    def test_check_other_data_populated(self, mock_cpu):
        """other_data contains used and alert fields."""
        config = {'watchfuls.cpu': {'alert': 80, 'interval': 1.0}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['cpu']['other_data']['used'] == 55.0
        assert items['cpu']['other_data']['alert'] == 80.0

    @patch('watchfuls.cpu.psutil.cpu_percent', return_value=30.0)
    def test_check_uses_default_alert(self, mock_cpu):
        """Without explicit config, default alert (85) is used."""
        config = {'watchfuls.cpu': {}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['cpu']['status'] is True

    @patch('watchfuls.cpu.psutil.cpu_percent', return_value=50.0)
    def test_check_custom_interval(self, mock_cpu):
        """Custom interval is forwarded to psutil.cpu_percent."""
        config = {'watchfuls.cpu': {'alert': 85, 'interval': 2.0}}
        w = self.Watchful(create_mock_monitor(config))
        w.check()
        mock_cpu.assert_called_once_with(interval=2.0)

    @patch('watchfuls.cpu.psutil.cpu_percent', side_effect=Exception('psutil error'))
    def test_check_exception_handled(self, mock_cpu):
        """Exception during psutil call propagates (module does not silently swallow it)."""
        config = {'watchfuls.cpu': {'alert': 85, 'interval': 1.0}}
        w = self.Watchful(create_mock_monitor(config))
        with pytest.raises(Exception, match='psutil error'):
            w.check()
