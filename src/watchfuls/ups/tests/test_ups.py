#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/ups."""

import pytest
from unittest.mock import patch, MagicMock, call
from conftest import create_mock_monitor

import watchfuls.ups as ups_module


def _make_vars(status, charge='100', runtime='3600', load='20'):
    """Build a NUT variables dict with common fields."""
    return {
        'ups.status': status,
        'battery.charge': charge,
        'battery.runtime': runtime,
        'ups.load': load,
    }


class TestNutQuery:
    """Unit tests for the _nut_query helper function."""

    def _mock_fileobj(self, lines):
        """Return a mock file object whose readline() and iteration yield lines."""
        mock_f = MagicMock()
        mock_f.readline.side_effect = lines + ['']
        mock_f.__iter__ = lambda s: iter(lines)
        mock_f.__enter__ = lambda s: s
        mock_f.__exit__ = MagicMock(return_value=False)
        return mock_f

    @patch('watchfuls.ups.socket.create_connection')
    def test_nut_query_ol_status(self, mock_conn):
        """Successful LIST VAR response with OL status is parsed correctly."""
        nut_response = [
            'BEGIN LIST VAR ups\n',
            'VAR ups ups.status "OL"\n',
            'VAR ups battery.charge "100"\n',
            'VAR ups battery.runtime "3600"\n',
            'VAR ups ups.load "20"\n',
            'END LIST VAR ups\n',
        ]
        mock_sock = MagicMock()
        mock_sock.makefile.return_value = self._mock_fileobj(nut_response)
        mock_conn.return_value = mock_sock

        variables = ups_module._nut_query('localhost', 3493, 'ups', '', '', 10)
        assert variables.get('ups.status') == 'OL'
        assert variables.get('battery.charge') == '100'

    @patch('watchfuls.ups.socket.create_connection')
    def test_nut_query_err_raises(self, mock_conn):
        """NUT ERR response raises ConnectionError."""
        nut_response = [
            'ERR ACCESS-DENIED\n',
        ]
        mock_sock = MagicMock()
        mock_sock.makefile.return_value = self._mock_fileobj(nut_response)
        mock_conn.return_value = mock_sock

        with pytest.raises(ConnectionError, match='NUT error'):
            ups_module._nut_query('localhost', 3493, 'ups', '', '', 10)

    @patch('watchfuls.ups.socket.create_connection', side_effect=ConnectionRefusedError('refused'))
    def test_nut_query_connection_error(self, mock_conn):
        """Connection failure propagates to caller."""
        with pytest.raises(ConnectionRefusedError):
            ups_module._nut_query('localhost', 3493, 'ups', '', '', 10)


class TestUpsInit:

    def test_init(self):
        from watchfuls.ups import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.ups': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.ups'


class TestUpsCheck:

    def setup_method(self):
        from watchfuls.ups import Watchful
        self.Watchful = Watchful

    def test_check_disabled_returns_empty(self):
        """Disabled module returns empty dict_return."""
        config = {'watchfuls.ups': {'enabled': False}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_empty_list_returns_empty(self):
        """Empty list returns empty dict_return."""
        config = {'watchfuls.ups': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_item_without_host_skipped(self):
        """Item with empty host is skipped."""
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': True, 'host': '', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_item_skipped(self):
        """Disabled list item is skipped."""
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': False, 'host': '192.168.1.10', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.ups._nut_query', return_value=_make_vars('OL'))
    def test_check_ol_status_ok(self, mock_query):
        """OL (online) status → status True."""
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': True, 'host': '192.168.1.10', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'myups' in items
        assert items['myups']['status'] is True
        assert 'Online' in items['myups']['message']

    @patch('watchfuls.ups._nut_query', return_value=_make_vars('OB'))
    def test_check_ob_status_warning(self, mock_query):
        """OB (on battery) status → status False with on-battery message."""
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': True, 'host': '192.168.1.10', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['myups']['status'] is False
        assert 'battery' in items['myups']['message'].lower()

    @patch('watchfuls.ups._nut_query', return_value=_make_vars('OB LB'))
    def test_check_lb_status_critical(self, mock_query):
        """OB LB (on battery, low battery) → status False with LOW BATTERY message."""
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': True, 'host': '192.168.1.10', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['myups']['status'] is False
        assert 'LOW BATTERY' in items['myups']['message']

    @patch('watchfuls.ups._nut_query', side_effect=ConnectionRefusedError('refused'))
    def test_check_connection_error_handled(self, mock_query):
        """Connection error is caught and sets status False."""
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': True, 'host': '192.168.1.10', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'myups' in items
        assert items['myups']['status'] is False
        assert 'Error' in items['myups']['message']

    @patch('watchfuls.ups._nut_query', return_value=_make_vars('OL', charge='95', runtime='1800', load='30'))
    def test_check_other_data_populated(self, mock_query):
        """other_data contains host, ups_name, status, battery_charge, runtime, load."""
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': True, 'host': '192.168.1.10', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        od = result.list['myups']['other_data']
        assert od['host'] == '192.168.1.10'
        assert od['ups_name'] == 'ups'
        assert od['status'] == 'OL'
        assert od['battery_charge'] == '95'
        assert od['runtime'] == '1800'
        assert od['load'] == '30'

    @patch('watchfuls.ups._nut_query', return_value=_make_vars('OL'))
    def test_check_ol_lb_combination_is_not_ok(self, mock_query):
        """OL + LB combination (unusual but possible) → status False due to LB."""
        # Simulate OL CHRG LB
        mock_query.return_value = _make_vars('OL LB')
        config = {'watchfuls.ups': {
            'list': {
                'myups': {'enabled': True, 'host': '192.168.1.10', 'ups_name': 'ups'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['myups']['status'] is False
