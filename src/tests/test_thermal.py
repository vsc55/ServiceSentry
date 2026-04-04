#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/linux/thermal_info_collection.py — ThermalNode and ThermalInfoCollection."""

import os
from unittest.mock import MagicMock, mock_open, patch

import pytest

from lib.linux.thermal_info_collection import (ThermalInfoCollection,
                                               ThermalNode)

# --- ThermalNode tests ---

class TestThermalNodeInit:

    def test_init_valid_dev(self):
        node = ThermalNode('thermal_zone0')
        assert node.dev == 'thermal_zone0'

    def test_init_strips_whitespace(self):
        node = ThermalNode('  thermal_zone1  ')
        assert node.dev == 'thermal_zone1'

    def test_init_empty_raises(self):
        with pytest.raises(ValueError, match="dev cannot be empty"):
            ThermalNode('')

    def test_init_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="dev cannot be empty"):
            ThermalNode('   ')

    def test_init_none_raises(self):
        with pytest.raises(ValueError):
            ThermalNode(None)


class TestThermalNodePaths:

    def test_path_dev(self):
        node = ThermalNode('thermal_zone0')
        expected = os.path.join('/sys/class/thermal', 'thermal_zone0')
        assert node._path_dev == expected

    def test_path_temp(self):
        node = ThermalNode('thermal_zone0')
        expected = os.path.join('/sys/class/thermal', 'thermal_zone0', 'temp')
        assert node._path_temp == expected

    def test_path_type(self):
        node = ThermalNode('thermal_zone0')
        expected = os.path.join('/sys/class/thermal', 'thermal_zone0', 'type')
        assert node._path_type == expected


class TestThermalNodeType:

    def test_type_reads_file(self):
        node = ThermalNode('thermal_zone0')
        with patch.object(node, '_read_file', return_value='cpu-thermal\n'):
            assert node.type == 'cpu-thermal'

    def test_type_unknown_when_file_missing(self):
        node = ThermalNode('thermal_zone0')
        with patch.object(node, '_read_file', return_value=None):
            assert node.type == 'Unknown'


class TestThermalNodeTemp:

    def test_temp_normal_value(self):
        node = ThermalNode('thermal_zone0')
        with patch.object(node, '_read_file', return_value='45000\n'):
            assert node.temp == pytest.approx(45.0)

    def test_temp_fractional(self):
        node = ThermalNode('thermal_zone0')
        with patch.object(node, '_read_file', return_value='67500\n'):
            assert node.temp == pytest.approx(67.5)

    def test_temp_zero(self):
        node = ThermalNode('thermal_zone0')
        with patch.object(node, '_read_file', return_value='0\n'):
            assert node.temp == 0.0

    def test_temp_file_missing(self):
        node = ThermalNode('thermal_zone0')
        with patch.object(node, '_read_file', return_value=None):
            assert node.temp == 0.0

    def test_temp_invalid_content(self):
        node = ThermalNode('thermal_zone0')
        with patch.object(node, '_read_file', return_value='not_a_number'):
            assert node.temp == 0.0


class TestThermalNodeReadFile:

    def test_read_existing_file(self):
        node = ThermalNode('thermal_zone0')
        with patch('builtins.open', mock_open(read_data='cpu-thermal\n')):
            result = node._read_file('/sys/class/thermal/thermal_zone0/type')
            assert result == 'cpu-thermal\n'

    def test_read_nonexistent_file(self):
        node = ThermalNode('thermal_zone0')
        with patch('builtins.open', side_effect=OSError("No such file")):
            result = node._read_file('/nonexistent/path')
            assert result is None

    def test_read_with_custom_default(self):
        node = ThermalNode('thermal_zone0')
        with patch('builtins.open', side_effect=OSError("No such file")):
            result = node._read_file('/nonexistent/path', default='fallback')
            assert result == 'fallback'


# --- ThermalInfoCollection tests ---

class TestThermalInfoCollectionInit:

    def test_init_no_autodetect(self):
        t = ThermalInfoCollection()
        assert t.nodes == []
        assert t.count == 0

    @patch('lib.linux.thermal_info_collection.glob.glob', return_value=[])
    def test_init_autodetect_no_sensors(self, mock_glob):
        t = ThermalInfoCollection(autodetect=True)
        assert t.count == 0


class TestThermalInfoCollectionClear:

    def test_clear_removes_nodes(self):
        t = ThermalInfoCollection()
        t.nodes.append(ThermalNode('thermal_zone0'))
        t.nodes.append(ThermalNode('thermal_zone1'))
        assert t.count == 2
        t.clear()
        assert t.count == 0


class TestThermalInfoCollectionCount:

    def test_count_empty(self):
        t = ThermalInfoCollection()
        assert t.count == 0

    def test_count_with_nodes(self):
        t = ThermalInfoCollection()
        t.nodes.append(ThermalNode('thermal_zone0'))
        assert t.count == 1
        t.nodes.append(ThermalNode('thermal_zone1'))
        assert t.count == 2


class TestThermalInfoCollectionAddSensor:

    def test_add_valid_sensor(self):
        t = ThermalInfoCollection()
        result = t._add_sensor('thermal_zone0')
        assert result is True
        assert t.count == 1
        assert t.nodes[0].dev == 'thermal_zone0'

    def test_add_empty_returns_false(self):
        t = ThermalInfoCollection()
        result = t._add_sensor('')
        assert result is False
        assert t.count == 0

    def test_add_none_returns_false(self):
        t = ThermalInfoCollection()
        result = t._add_sensor(None)
        assert result is False
        assert t.count == 0

    def test_add_whitespace_returns_false(self):
        t = ThermalInfoCollection()
        result = t._add_sensor('   ')
        assert result is False
        assert t.count == 0


class TestThermalInfoCollectionDetect:

    @patch('lib.linux.thermal_info_collection.glob.glob')
    def test_detect_finds_zones(self, mock_glob):
        mock_glob.return_value = [
            '/sys/class/thermal/thermal_zone0',
            '/sys/class/thermal/thermal_zone1',
            '/sys/class/thermal/thermal_zone2',
        ]
        t = ThermalInfoCollection()
        t.detect()
        assert t.count == 3
        assert t.nodes[0].dev == 'thermal_zone0'
        assert t.nodes[1].dev == 'thermal_zone1'
        assert t.nodes[2].dev == 'thermal_zone2'

    @patch('lib.linux.thermal_info_collection.glob.glob')
    def test_detect_no_zones(self, mock_glob):
        mock_glob.return_value = []
        t = ThermalInfoCollection()
        t.detect()
        assert t.count == 0

    @patch('lib.linux.thermal_info_collection.glob.glob')
    def test_detect_clears_previous(self, mock_glob):
        """detect() clears existing nodes before adding new ones."""
        t = ThermalInfoCollection()
        t.nodes.append(ThermalNode('old_zone'))
        assert t.count == 1

        mock_glob.return_value = ['/sys/class/thermal/thermal_zone0']
        t.detect()
        assert t.count == 1
        assert t.nodes[0].dev == 'thermal_zone0'

    @patch('lib.linux.thermal_info_collection.glob.glob')
    def test_detect_uses_correct_pattern(self, mock_glob):
        """detect() should glob for thermal_zone* only."""
        mock_glob.return_value = []
        t = ThermalInfoCollection()
        t.detect()
        expected = os.path.join('/sys/class/thermal', 'thermal_zone*')
        mock_glob.assert_called_once_with(expected)


class TestThermalBasePathConstant:

    def test_path_thermal_constant(self):
        assert ThermalNode.PATH_THERMAL == '/sys/class/thermal'
        assert ThermalInfoCollection.PATH_THERMAL == '/sys/class/thermal'
