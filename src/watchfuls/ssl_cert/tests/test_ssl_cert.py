#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/ssl_cert."""

import time
import pytest
from unittest.mock import patch, MagicMock
from conftest import create_mock_monitor


def _make_cert(not_after_str):
    """Build a minimal cert dict with a notAfter field."""
    return {'notAfter': not_after_str}


class TestSslCertInit:

    def test_init(self):
        from watchfuls.ssl_cert import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.ssl_cert': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.ssl_cert'


class TestSslCertCheck:

    def setup_method(self):
        from watchfuls.ssl_cert import Watchful
        self.Watchful = Watchful

    def test_check_disabled_returns_empty(self):
        """Disabled module returns empty dict_return."""
        config = {'watchfuls.ssl_cert': {'enabled': False}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_empty_list_returns_empty(self):
        """Empty list returns empty dict_return."""
        config = {'watchfuls.ssl_cert': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    def test_check_disabled_item_skipped(self):
        """Disabled list item is skipped."""
        config = {'watchfuls.ssl_cert': {
            'warning_days': 30,
            'list': {
                'example.com': {'enabled': False, 'host': 'example.com', 'port': 443},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        assert len(result.items()) == 0

    @patch('watchfuls.ssl_cert.ssl.cert_time_to_seconds')
    @patch('watchfuls.ssl_cert.ssl.create_default_context')
    @patch('watchfuls.ssl_cert.socket.create_connection')
    def test_check_cert_valid_ok(self, mock_conn, mock_ctx_cls, mock_time_to_sec):
        """Certificate with plenty of days left → status True."""
        # 60 days left
        future_ts = time.time() + 60 * 86400
        mock_time_to_sec.return_value = future_ts

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = _make_cert('Jun  1 00:00:00 2030 GMT')
        mock_ssock.__enter__ = lambda s: s
        mock_ssock.__exit__ = MagicMock(return_value=False)

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = mock_ssock
        mock_ctx_cls.return_value = mock_ctx

        config = {'watchfuls.ssl_cert': {
            'warning_days': 30,
            'list': {
                'example.com': {'enabled': True, 'host': 'example.com', 'port': 443},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'example.com' in items
        assert items['example.com']['status'] is True

    @patch('watchfuls.ssl_cert.ssl.cert_time_to_seconds')
    @patch('watchfuls.ssl_cert.ssl.create_default_context')
    @patch('watchfuls.ssl_cert.socket.create_connection')
    def test_check_cert_within_warning_window(self, mock_conn, mock_ctx_cls, mock_time_to_sec):
        """Certificate expiring within warning window → status False."""
        # 10 days left, warning is 30 days
        future_ts = time.time() + 10 * 86400
        mock_time_to_sec.return_value = future_ts

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = _make_cert('Jan 10 00:00:00 2026 GMT')
        mock_ssock.__enter__ = lambda s: s
        mock_ssock.__exit__ = MagicMock(return_value=False)

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = mock_ssock
        mock_ctx_cls.return_value = mock_ctx

        config = {'watchfuls.ssl_cert': {
            'warning_days': 30,
            'list': {
                'example.com': {'enabled': True, 'host': 'example.com', 'port': 443},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['example.com']['status'] is False
        assert 'warning threshold' in items['example.com']['message']

    @patch('watchfuls.ssl_cert.ssl.cert_time_to_seconds')
    @patch('watchfuls.ssl_cert.ssl.create_default_context')
    @patch('watchfuls.ssl_cert.socket.create_connection')
    def test_check_cert_expired(self, mock_conn, mock_ctx_cls, mock_time_to_sec):
        """Expired certificate → status False with EXPIRED message."""
        # -5 days (expired)
        past_ts = time.time() - 5 * 86400
        mock_time_to_sec.return_value = past_ts

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = _make_cert('Jan  1 00:00:00 2020 GMT')
        mock_ssock.__enter__ = lambda s: s
        mock_ssock.__exit__ = MagicMock(return_value=False)

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = mock_ssock
        mock_ctx_cls.return_value = mock_ctx

        config = {'watchfuls.ssl_cert': {
            'warning_days': 30,
            'list': {
                'example.com': {'enabled': True, 'host': 'example.com', 'port': 443},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert items['example.com']['status'] is False
        assert 'EXPIRED' in items['example.com']['message']

    @patch('watchfuls.ssl_cert.socket.create_connection', side_effect=ConnectionRefusedError('refused'))
    def test_check_connection_error_handled(self, mock_conn):
        """Connection error is caught and sets status False."""
        config = {'watchfuls.ssl_cert': {
            'warning_days': 30,
            'list': {
                'example.com': {'enabled': True, 'host': 'example.com', 'port': 443},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        assert 'example.com' in items
        assert items['example.com']['status'] is False
        assert 'Error' in items['example.com']['message']

    @patch('watchfuls.ssl_cert.ssl.cert_time_to_seconds')
    @patch('watchfuls.ssl_cert.ssl.create_default_context')
    @patch('watchfuls.ssl_cert.socket.create_connection')
    def test_check_other_data_populated(self, mock_conn, mock_ctx_cls, mock_time_to_sec):
        """other_data contains host, port, days_left, expires."""
        future_ts = time.time() + 90 * 86400
        mock_time_to_sec.return_value = future_ts

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = _make_cert('Aug  1 00:00:00 2026 GMT')
        mock_ssock.__enter__ = lambda s: s
        mock_ssock.__exit__ = MagicMock(return_value=False)

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = mock_ssock
        mock_ctx_cls.return_value = mock_ctx

        config = {'watchfuls.ssl_cert': {
            'warning_days': 30,
            'list': {
                'example.com': {'enabled': True, 'host': 'example.com', 'port': 8443},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        od = items['example.com']['other_data']
        assert od['host'] == 'example.com'
        assert od['port'] == 8443
        assert 'days_left' in od
        assert 'expires' in od

    @patch('watchfuls.ssl_cert.ssl.cert_time_to_seconds')
    @patch('watchfuls.ssl_cert.ssl.create_default_context')
    @patch('watchfuls.ssl_cert.socket.create_connection')
    def test_check_per_item_warning_days_overrides_module(self, mock_conn, mock_ctx_cls, mock_time_to_sec):
        """Per-item warning_days overrides module-level setting."""
        # 20 days left; item warning_days=10 → ok; module warning_days=30 → not ok
        future_ts = time.time() + 20 * 86400
        mock_time_to_sec.return_value = future_ts

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = _make_cert('Feb  1 00:00:00 2026 GMT')
        mock_ssock.__enter__ = lambda s: s
        mock_ssock.__exit__ = MagicMock(return_value=False)

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_sock

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = mock_ssock
        mock_ctx_cls.return_value = mock_ctx

        config = {'watchfuls.ssl_cert': {
            'warning_days': 30,
            'list': {
                'example.com': {'enabled': True, 'host': 'example.com', 'port': 443, 'warning_days': 10},
            }
        }}
        w = self.Watchful(create_mock_monitor(config))
        result = w.check()
        items = result.list
        # 20 days > per-item threshold 10 → ok
        assert items['example.com']['status'] is True
