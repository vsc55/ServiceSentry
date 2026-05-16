#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/process."""

import pytest
from unittest.mock import patch, MagicMock
from conftest import create_mock_monitor


def _make_proc(name):
    """Create a mock psutil process with a given name."""
    p = MagicMock()
    p.info = {'name': name}
    return p


class TestProcessInit:

    def test_init(self):
        from watchfuls.process import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.process': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.process'


class TestProcessCheck:

    def setup_method(self):
        from watchfuls.process import Watchful
        self.Watchful = Watchful

    def test_check_disabled_returns_empty(self):
        """Disabled module returns empty dict_return."""
        config = {'watchfuls.process': {'enabled': False}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_empty_list_returns_empty(self):
        """Empty list returns empty dict_return."""
        config = {'watchfuls.process': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_item_skipped(self):
        """Disabled list item is skipped."""
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': False, 'process': 'nginx', 'min_count': 1},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_process_running_ok(self, mock_iter):
        """Process found at or above min_count → status True."""
        mock_iter.return_value = [_make_proc('nginx'), _make_proc('nginx')]
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': True, 'process': 'nginx', 'min_count': 1},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'nginx' in items
        assert items['nginx']['status'] is True

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_process_not_running(self, mock_iter):
        """Process not found → status False."""
        mock_iter.return_value = [_make_proc('apache2'), _make_proc('sshd')]
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': True, 'process': 'nginx', 'min_count': 1},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['nginx']['status'] is False

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_min_count_not_met(self, mock_iter):
        """Found count below min_count → status False."""
        mock_iter.return_value = [_make_proc('worker')]
        config = {'watchfuls.process': {
            'list': {
                'worker': {'enabled': True, 'process': 'worker', 'min_count': 3},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['worker']['status'] is False

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_min_count_exactly_met(self, mock_iter):
        """Count exactly at min_count → status True."""
        mock_iter.return_value = [_make_proc('worker'), _make_proc('worker')]
        config = {'watchfuls.process': {
            'list': {
                'worker': {'enabled': True, 'process': 'worker', 'min_count': 2},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['worker']['status'] is True

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_case_insensitive(self, mock_iter):
        """Process name matching is case-insensitive."""
        mock_iter.return_value = [_make_proc('NGINX')]
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': True, 'process': 'nginx', 'min_count': 1},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['nginx']['status'] is True

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_empty_process_uses_key(self, mock_iter):
        """Empty process field falls back to item key."""
        mock_iter.return_value = [_make_proc('nginx')]
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': True, 'process': '', 'min_count': 1},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['nginx']['status'] is True

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_other_data_populated(self, mock_iter):
        """other_data contains process, count, min_count."""
        mock_iter.return_value = [_make_proc('nginx'), _make_proc('nginx')]
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': True, 'process': 'nginx', 'min_count': 1},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        od = result.list['nginx']['other_data']
        assert od['process'] == 'nginx'
        assert od['count'] == 2
        assert od['min_count'] == 1

    @patch('watchfuls.process.psutil.process_iter', side_effect=Exception('psutil error'))
    def test_check_exception_handled(self, mock_iter):
        """Exception during process_iter is caught and sets status False."""
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': True, 'process': 'nginx', 'min_count': 1},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'nginx' in items
        assert items['nginx']['status'] is False
        assert 'Error' in items['nginx']['message']

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_item_zero_uses_module_min_count(self, mock_iter):
        """Item min_count=0 falls back to the module-level min_count."""
        mock_iter.return_value = [_make_proc('nginx'), _make_proc('nginx')]
        config = {'watchfuls.process': {
            'min_count': 3,
            'list': {
                'nginx': {'enabled': True, 'process': 'nginx', 'min_count': 0},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        # 2 instances found, module min_count=3 → not enough → False
        assert result.list['nginx']['status'] is False
        assert result.list['nginx']['other_data']['min_count'] == 3

    @patch('watchfuls.process.psutil.process_iter')
    def test_check_module_min_count_default(self, mock_iter):
        """When item and module both omit min_count, default of 1 is used."""
        mock_iter.return_value = [_make_proc('nginx')]
        config = {'watchfuls.process': {
            'list': {
                'nginx': {'enabled': True, 'process': 'nginx'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert result.list['nginx']['status'] is True
        assert result.list['nginx']['other_data']['min_count'] == 1


class TestProcessDiscover:

    def setup_method(self):
        from watchfuls.process import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.process.psutil.process_iter')
    def test_discover_returns_list(self, mock_iter):
        """discover() returns a list of dicts with name, display_name, status."""
        mock_iter.return_value = [_make_proc('nginx'), _make_proc('sshd')]
        result = self.Watchful.discover()
        assert isinstance(result, list)
        assert all('name' in r and 'display_name' in r and 'status' in r for r in result)

    @patch('watchfuls.process.psutil.process_iter')
    def test_discover_counts_instances(self, mock_iter):
        """discover() counts multiple instances of the same process name."""
        mock_iter.return_value = [_make_proc('nginx'), _make_proc('nginx'), _make_proc('sshd')]
        result = self.Watchful.discover()
        nginx = next(r for r in result if r['name'] == 'nginx')
        assert nginx['status'] == '×2'

    @patch('watchfuls.process.psutil.process_iter')
    def test_discover_sorted_by_name(self, mock_iter):
        """discover() returns processes sorted alphabetically (case-insensitive)."""
        mock_iter.return_value = [_make_proc('zsh'), _make_proc('bash'), _make_proc('nginx')]
        result = self.Watchful.discover()
        names = [r['name'] for r in result]
        assert names == sorted(names, key=str.lower)

    @patch('watchfuls.process.psutil.process_iter', side_effect=Exception('boom'))
    def test_discover_exception_returns_empty(self, _):
        """discover() returns [] on any exception."""
        assert self.Watchful.discover() == []

    @patch('watchfuls.process.psutil.process_iter')
    def test_discover_skips_empty_names(self, mock_iter):
        """Processes with empty name are excluded from discover results."""
        mock_iter.return_value = [_make_proc(''), _make_proc('nginx')]
        result = self.Watchful.discover()
        assert all(r['name'] for r in result)
