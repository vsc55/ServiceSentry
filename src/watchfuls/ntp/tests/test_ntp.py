#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/ntp."""

import pytest
from unittest.mock import patch, MagicMock
from conftest import create_mock_monitor

import watchfuls.ntp as ntp_module


class TestNtpQuery:
    """Unit tests for the _ntp_query helper function."""

    def _build_ntp_response(self, t2_s, t2_f, t3_s, t3_f):
        """Build a minimal 48-byte NTP response packet."""
        import struct
        header = bytes(32)  # first 32 bytes (LI, VN, stratum, etc.)
        t2 = struct.pack('!II', t2_s, t2_f)
        t3 = struct.pack('!II', t3_s, t3_f)
        return header + t2 + t3

    @patch('watchfuls.ntp.socket.socket')
    def test_ntp_query_returns_offset_and_delay(self, mock_sock_cls):
        """_ntp_query returns (offset, delay) tuple on success."""
        import struct, time
        NTP_DELTA = ntp_module.NTP_DELTA
        now = time.time()
        # Simulate server timestamps very close to now
        t2_s = int(now) + NTP_DELTA
        t3_s = int(now) + NTP_DELTA

        data = self._build_ntp_response(t2_s, 0, t3_s, 0)
        mock_sock = MagicMock()
        mock_sock.recvfrom.return_value = (data, ('1.2.3.4', 123))
        mock_sock_cls.return_value = mock_sock

        offset, delay = ntp_module._ntp_query('pool.ntp.org', 5)
        assert isinstance(offset, float)
        assert isinstance(delay, float)
        assert offset >= 0

    @patch('watchfuls.ntp.socket.socket')
    def test_ntp_query_short_response_raises(self, mock_sock_cls):
        """Short response raises ValueError."""
        mock_sock = MagicMock()
        mock_sock.recvfrom.return_value = (b'\x00' * 10, ('1.2.3.4', 123))
        mock_sock_cls.return_value = mock_sock

        with pytest.raises(ValueError, match='too short'):
            ntp_module._ntp_query('pool.ntp.org', 5)

    @patch('watchfuls.ntp.socket.socket')
    def test_ntp_query_socket_error_propagates(self, mock_sock_cls):
        """Socket error propagates to caller."""
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = OSError('network unreachable')
        mock_sock_cls.return_value = mock_sock

        with pytest.raises(OSError):
            ntp_module._ntp_query('pool.ntp.org', 5)


class TestNtpInit:

    def test_init(self):
        from watchfuls.ntp import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.ntp': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.ntp'


class TestNtpCheck:

    def setup_method(self):
        from watchfuls.ntp import Watchful
        self.Watchful = Watchful

    def test_check_disabled_returns_empty(self):
        """Disabled module returns empty dict_return."""
        config = {'watchfuls.ntp': {'enabled': False}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_empty_list_returns_empty(self):
        """Empty list returns empty dict_return."""
        config = {'watchfuls.ntp': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_item_skipped(self):
        """Disabled list item is skipped."""
        config = {'watchfuls.ntp': {
            'list': {
                'pool': {'enabled': False, 'server': 'pool.ntp.org'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.ntp._ntp_query', return_value=(0.003, 0.012))
    def test_check_offset_within_threshold(self, mock_query):
        """Offset below max_offset → status True."""
        config = {'watchfuls.ntp': {
            'max_offset': 5.0,
            'list': {
                'pool': {'enabled': True, 'server': 'pool.ntp.org'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'pool' in items
        assert items['pool']['status'] is True

    @patch('watchfuls.ntp._ntp_query', return_value=(10.5, 0.012))
    def test_check_offset_exceeds_threshold(self, mock_query):
        """Offset above max_offset → status False."""
        config = {'watchfuls.ntp': {
            'max_offset': 5.0,
            'list': {
                'pool': {'enabled': True, 'server': 'pool.ntp.org'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['pool']['status'] is False
        assert 'exceeds' in items['pool']['message']

    @patch('watchfuls.ntp._ntp_query', side_effect=OSError('socket error'))
    def test_check_socket_error_handled(self, mock_query):
        """Socket error is caught and sets status False."""
        config = {'watchfuls.ntp': {
            'max_offset': 5.0,
            'list': {
                'pool': {'enabled': True, 'server': 'pool.ntp.org'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'pool' in items
        assert items['pool']['status'] is False
        assert 'Error' in items['pool']['message']

    @patch('watchfuls.ntp._ntp_query', return_value=(1.2, 0.050))
    def test_check_other_data_populated(self, mock_query):
        """other_data contains server, offset_seconds, delay_seconds, max_offset."""
        config = {'watchfuls.ntp': {
            'max_offset': 5.0,
            'list': {
                'pool': {'enabled': True, 'server': 'pool.ntp.org'},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        od = result.list['pool']['other_data']
        assert od['server'] == 'pool.ntp.org'
        assert od['offset_seconds'] == round(1.2, 3)
        assert od['delay_seconds'] == round(0.050, 3)
        assert od['max_offset'] == 5.0

    @patch('watchfuls.ntp._ntp_query', return_value=(1.0, 0.010))
    def test_check_per_item_max_offset_overrides_module(self, mock_query):
        """Per-item max_offset overrides the module-level setting."""
        # offset=1.0; item max_offset=0.5 → fail; module max_offset=5.0 → ok
        config = {'watchfuls.ntp': {
            'max_offset': 5.0,
            'list': {
                'pool': {'enabled': True, 'server': 'pool.ntp.org', 'max_offset': 0.5},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['pool']['status'] is False
