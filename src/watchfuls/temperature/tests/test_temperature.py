#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/temperature — psutil backend (Linux / macOS only)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from conftest import create_mock_monitor


def _shwtemp(label, current, high=100.0, critical=100.0):
    """Mimics a psutil shwtemp namedtuple entry."""
    return SimpleNamespace(label=label, current=current, high=high, critical=critical)


def _config(extra=None):
    base = {'watchfuls.temperature': {}}
    if extra:
        base['watchfuls.temperature'].update(extra)
    return base


class TestTemperatureInit:

    def test_init(self):
        from watchfuls.temperature import Watchful
        w = Watchful(create_mock_monitor(_config()))
        assert w.name_module == 'watchfuls.temperature'

    def test_defaults_from_schema(self):
        from watchfuls.temperature import Watchful
        assert Watchful._DEFAULTS['alert'] == 80
        assert Watchful._DEFAULTS['enabled'] is True


class TestTemperatureCheck:

    def setup_method(self):
        from watchfuls.temperature import Watchful
        self.Watchful = Watchful

    def _make(self, extra=None):
        return self.Watchful(create_mock_monitor(_config(extra)))

    @patch('watchfuls.temperature.psutil')
    def test_normal_temp_is_ok(self, mock_psutil):
        """Temperature below threshold → status True."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 45.0)]
        }
        result = self._make().check()
        assert result.list['coretemp_0']['status'] is True
        assert 'Ok' in result.list['coretemp_0']['message']
        assert '45.0' in result.list['coretemp_0']['message']

    @patch('watchfuls.temperature.psutil')
    def test_high_temp_is_warning(self, mock_psutil):
        """Temperature above threshold → status False."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 95.0)]
        }
        result = self._make().check()
        assert result.list['coretemp_0']['status'] is False
        assert 'Warning' in result.list['coretemp_0']['message']
        assert '95.0' in result.list['coretemp_0']['message']

    @patch('watchfuls.temperature.psutil')
    def test_exact_threshold_is_ok(self, mock_psutil):
        """Temperature exactly at threshold is OK (not strictly greater)."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 80.0)]
        }
        result = self._make({'alert': 80}).check()
        assert result.list['coretemp_0']['status'] is True

    @patch('watchfuls.temperature.psutil')
    def test_sensor_key_format(self, mock_psutil):
        """Keys are '{chip}_{index}'."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 40.0), _shwtemp('Core 1', 42.0)],
            'acpitz':   [_shwtemp('', 30.0)],
        }
        result = self._make().check()
        assert 'coretemp_0' in result.list
        assert 'coretemp_1' in result.list
        assert 'acpitz_0' in result.list

    @patch('watchfuls.temperature.psutil')
    def test_multiple_sensors_independent(self, mock_psutil):
        """Each sensor is evaluated independently."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 45.0), _shwtemp('Core 1', 95.0)]
        }
        result = self._make().check()
        assert result.list['coretemp_0']['status'] is True
        assert result.list['coretemp_1']['status'] is False

    @patch('watchfuls.temperature.psutil')
    def test_label_from_psutil(self, mock_psutil):
        """Label defaults to psutil's label when not empty."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Package id 0', 50.0)]
        }
        result = self._make().check()
        assert 'Package id 0' in result.list['coretemp_0']['message']

    @patch('watchfuls.temperature.psutil')
    def test_empty_psutil_label_uses_chip_name(self, mock_psutil):
        """Empty psutil label falls back to the chip name."""
        mock_psutil.sensors_temperatures.return_value = {
            'acpitz': [_shwtemp('', 28.0)]
        }
        result = self._make().check()
        assert 'acpitz' in result.list['acpitz_0']['message']

    @patch('watchfuls.temperature.psutil')
    def test_label_from_config_overrides(self, mock_psutil):
        """Label set in config overrides the psutil label."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 50.0)]
        }
        result = self._make({'list': {'coretemp_0': {'label': 'My CPU', 'enabled': True}}}).check()
        assert 'My CPU' in result.list['coretemp_0']['message']

    @patch('watchfuls.temperature.psutil')
    def test_module_level_alert_applies(self, mock_psutil):
        """Module-level alert threshold applies when no per-sensor override."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 75.0)]
        }
        result = self._make({'alert': 70}).check()
        assert result.list['coretemp_0']['status'] is False

    @patch('watchfuls.temperature.psutil')
    def test_per_sensor_alert_overrides_module(self, mock_psutil):
        """Per-sensor alert overrides the module-level threshold."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 75.0)]
        }
        config = {
            'alert': 70,
            'list': {'coretemp_0': {'alert': 90, 'enabled': True}},
        }
        result = self._make(config).check()
        assert result.list['coretemp_0']['status'] is True

    @patch('watchfuls.temperature.psutil')
    def test_disabled_sensor_skipped(self, mock_psutil):
        """Sensor disabled in config is not reported."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 50.0)]
        }
        result = self._make({'list': {'coretemp_0': {'enabled': False}}}).check()
        assert 'coretemp_0' not in result.list

    @patch('watchfuls.temperature.psutil')
    def test_empty_sensors_returns_empty(self, mock_psutil):
        """No available sensors → empty result."""
        mock_psutil.sensors_temperatures.return_value = {}
        assert self._make().check().list == {}

    @patch('watchfuls.temperature.psutil')
    def test_sensors_raises_exception_returns_empty(self, mock_psutil):
        """Exception in sensors_temperatures is caught and returns empty."""
        mock_psutil.sensors_temperatures.side_effect = RuntimeError('hw error')
        assert self._make().check().list == {}

    def test_no_sensors_temperatures_attr_returns_empty(self):
        """psutil has no sensors_temperatures (Windows) → empty result."""
        with patch('watchfuls.temperature.psutil', spec=[]):
            assert self._make().check().list == {}

    @patch('watchfuls.temperature.psutil')
    def test_other_data_contains_temp_type_alert(self, mock_psutil):
        """other_data stores type (chip name), temp, and alert."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 55.0)]
        }
        result = self._make({'alert': 80}).check()
        od = result.list['coretemp_0']['other_data']
        assert od['temp'] == 55.0
        assert od['alert'] == 80.0
        assert od['type'] == 'coretemp'

    def test_module_disabled_returns_empty(self):
        """Disabled module returns empty dict_return."""
        from watchfuls.temperature import Watchful
        w = Watchful(create_mock_monitor({'watchfuls.temperature': {'enabled': False}}))
        assert w.check().list == {}


class TestTemperatureGetConf:

    def setup_method(self):
        from watchfuls.temperature import Watchful
        self.Watchful = Watchful

    def _make(self, extra=None):
        return self.Watchful(create_mock_monitor(_config(extra)))

    def test_get_conf_none_raises_value_error(self):
        with pytest.raises(ValueError, match="can not be None"):
            self._make()._get_conf(None, 'coretemp_0')

    def test_get_conf_invalid_option_raises_type_error(self):
        from enum import IntEnum

        class FakeOption(IntEnum):
            invalid = 999

        with pytest.raises(TypeError, match="is not valid option"):
            self._make()._get_conf(FakeOption.invalid, 'coretemp_0')


class TestTemperatureDiscover:

    def setup_method(self):
        from watchfuls.temperature import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.temperature.psutil')
    def test_discover_basic(self, mock_psutil):
        """Returns one entry per sensor reading."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 45.0), _shwtemp('Core 1', 47.0)],
            'acpitz':   [_shwtemp('', 28.0)],
        }
        names = [r['name'] for r in self.Watchful.discover()]
        assert 'coretemp_0' in names
        assert 'coretemp_1' in names
        assert 'acpitz_0' in names

    @patch('watchfuls.temperature.psutil')
    def test_discover_display_name_with_label(self, mock_psutil):
        """display_name includes chip and psutil label when label is present."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Package id 0', 50.0)]
        }
        assert self.Watchful.discover()[0]['display_name'] == 'coretemp — Package id 0'

    @patch('watchfuls.temperature.psutil')
    def test_discover_display_name_without_label(self, mock_psutil):
        """display_name uses chip + index when psutil label is empty."""
        mock_psutil.sensors_temperatures.return_value = {
            'acpitz': [_shwtemp('', 28.0)]
        }
        assert self.Watchful.discover()[0]['display_name'] == 'acpitz [0]'

    @patch('watchfuls.temperature.psutil')
    def test_discover_status_is_temperature(self, mock_psutil):
        """status field contains the formatted temperature."""
        mock_psutil.sensors_temperatures.return_value = {
            'coretemp': [_shwtemp('Core 0', 55.3)]
        }
        assert self.Watchful.discover()[0]['status'] == '55.3°C'

    @patch('watchfuls.temperature.psutil')
    def test_discover_empty(self, mock_psutil):
        mock_psutil.sensors_temperatures.return_value = {}
        assert self.Watchful.discover() == []

    @patch('watchfuls.temperature.psutil')
    def test_discover_exception_returns_empty(self, mock_psutil):
        mock_psutil.sensors_temperatures.side_effect = RuntimeError('hw error')
        assert self.Watchful.discover() == []

    def test_discover_no_attribute_returns_empty(self):
        """psutil has no sensors_temperatures (Windows) → empty list."""
        with patch('watchfuls.temperature.psutil', spec=[]):
            assert self.Watchful.discover() == []
