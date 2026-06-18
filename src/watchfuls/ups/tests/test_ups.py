#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/ups."""

import pytest
from unittest.mock import patch, MagicMock
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
        # Numeric metrics for history: charge %, runtime in MINUTES, load %.
        assert od['battery_charge'] == 95.0
        assert od['runtime'] == 30.0           # 1800s / 60
        assert od['load'] == 30.0
        assert od['on_battery'] is False and od['low_battery'] is False

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


class TestUpsThresholds:
    """Configurable alert thresholds (battery %, runtime min, load %, on-battery)."""

    Watchful = ups_module.Watchful

    def _run(self, vars_, item):
        config = {'watchfuls.ups': {'list': {'u': {
            'enabled': True, 'host': '10.0.0.1', 'ups_name': 'ups', **item}}}}
        with patch('watchfuls.ups._nut_query', return_value=vars_):
            return ups_module.Watchful(create_mock_monitor(config)).check().list['u']

    def test_low_battery_charge_triggers(self):
        r = self._run(_make_vars('OL', charge='15'), {'alert_battery': 20})
        assert r['status'] is False and 'battery' in r['message'].lower()

    def test_charge_above_threshold_ok(self):
        r = self._run(_make_vars('OL', charge='80'), {'alert_battery': 20})
        assert r['status'] is True

    def test_low_runtime_triggers(self):
        # 300s = 5 min, below the 10-min threshold.
        r = self._run(_make_vars('OL', runtime='300'), {'alert_runtime': 10})
        assert r['status'] is False and 'runtime' in r['message'].lower()

    def test_on_battery_alerts_by_default(self):
        r = self._run(_make_vars('OB'), {})
        assert r['status'] is False

    def test_on_battery_alert_can_be_disabled(self):
        # OB but alert_on_battery off and charge/runtime healthy → OK.
        r = self._run(_make_vars('OB', charge='100', runtime='3600'),
                      {'alert_on_battery': False})
        assert r['status'] is True

    def test_load_threshold_triggers(self):
        r = self._run(_make_vars('OL', load='95'), {'alert_load': 80})
        assert r['status'] is False and 'load' in r['message'].lower()

    def test_load_threshold_disabled_by_default(self):
        # Default alert_load=0 → high load alone does not alert.
        r = self._run(_make_vars('OL', load='99'), {})
        assert r['status'] is True


class TestTestConnection:
    """Web-UI test_connection action."""

    @patch('watchfuls.ups._nut_query', return_value=_make_vars('OL'))
    def test_ok(self, mock_query):
        res = ups_module.Watchful.test_connection(
            {'host': '192.168.1.10', 'port': 3493, 'ups_name': 'ups'})
        assert res['ok'] is True
        assert '192.168.1.10:3493' in res['message']
        assert 'OL' in res['message']
        # On success it returns ALL NUT variables for the info modal.
        assert res['info']['ups.status'] == 'OL'
        assert 'battery.charge' in res['info'] and 'ups.load' in res['info']

    @patch('watchfuls.ups._nut_query', side_effect=ConnectionRefusedError('refused'))
    def test_failure_returns_message(self, mock_query):
        res = ups_module.Watchful.test_connection({'host': '10.0.0.9'})
        assert res['ok'] is False
        assert 'refused' in res['message']

    def test_no_host(self):
        res = ups_module.Watchful.test_connection({'host': '', 'port': 3493})
        assert res['ok'] is False

    @patch('watchfuls.ups._nut_query', return_value=_make_vars('OB'))
    def test_host_from_bound_host_ctx(self, mock_query):
        """Empty host falls back to the bound host's address (__host__)."""
        res = ups_module.Watchful.test_connection(
            {'host': '', '__host__': {'address': '172.16.0.5'}})
        assert res['ok'] is True
        assert '172.16.0.5' in res['message']
        assert mock_query.call_args.kwargs['host'] == '172.16.0.5'
