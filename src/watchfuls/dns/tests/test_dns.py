#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/dns."""

import socket
from unittest.mock import patch, MagicMock
from conftest import create_mock_monitor


# Minimal getaddrinfo result format: (family, type, proto, canonname, (addr, port))
def _addrinfo4(ip):
    return (socket.AF_INET, 1, 6, '', (ip, 0))

def _addrinfo6(ip):
    return (socket.AF_INET6, 1, 6, '', (ip, 0))


class TestDnsInit:

    def test_init(self):
        from watchfuls.dns import Watchful
        mock_monitor = create_mock_monitor({'watchfuls.dns': {}})
        w = Watchful(mock_monitor)
        assert w.name_module == 'watchfuls.dns'


class TestDnsCheck:

    def setup_method(self):
        from watchfuls.dns import Watchful
        self.Watchful = Watchful

    def test_check_disabled_returns_empty(self):
        config = {'watchfuls.dns': {'enabled': False}}
        w = self.Watchful(create_mock_monitor(config))
        assert len(w.check().items()) == 0

    def test_check_empty_list_returns_empty(self):
        config = {'watchfuls.dns': {'list': {}}}
        w = self.Watchful(create_mock_monitor(config))
        assert len(w.check().items()) == 0

    def test_check_disabled_item_skipped(self):
        config = {'watchfuls.dns': {'list': {
            'example.com': {'enabled': False, 'host': 'example.com'},
        }}}
        assert len(self.Watchful(create_mock_monitor(config)).check().items()) == 0

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_check_resolution_ok(self, mock_getaddrinfo):
        """Successful A resolution → status True."""
        mock_getaddrinfo.return_value = [_addrinfo4('93.184.216.34')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com'},
        }}}
        items = self.Watchful(create_mock_monitor(config)).check().list
        assert 'example.com' in items
        assert items['example.com']['status'] is True

    @patch('watchfuls.dns.socket.getaddrinfo', side_effect=OSError('resolution failed'))
    def test_check_resolution_fails(self, mock_getaddrinfo):
        """Failed A resolution → status False."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'nonexistent.invalid': {'enabled': True, 'host': 'nonexistent.invalid'},
        }}}
        items = self.Watchful(create_mock_monitor(config)).check().list
        assert items['nonexistent.invalid']['status'] is False

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_check_expected_match(self, mock_getaddrinfo):
        """Resolved value contains expected → status True."""
        mock_getaddrinfo.return_value = [_addrinfo4('93.184.216.34')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'expected': '93.184.216.34'},
        }}}
        assert self.Watchful(create_mock_monitor(config)).check().list['example.com']['status'] is True

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_check_expected_mismatch(self, mock_getaddrinfo):
        """Resolved value does not contain expected → status False."""
        mock_getaddrinfo.return_value = [_addrinfo4('93.184.216.34')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'expected': '1.2.3.4'},
        }}}
        item = self.Watchful(create_mock_monitor(config)).check().list['example.com']
        assert item['status'] is False
        assert 'expected' in item['message'].lower()

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_check_other_data_populated(self, mock_getaddrinfo):
        """other_data contains host, record_type, resolved, expected."""
        mock_getaddrinfo.return_value = [_addrinfo4('93.184.216.34')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'expected': ''},
        }}}
        od = self.Watchful(create_mock_monitor(config)).check().list['example.com']['other_data']
        assert od['host'] == 'example.com'
        assert od['record_type'] == 'A'
        assert '93.184.216.34' in od['resolved']
        assert od['expected'] == ''

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_check_deduplicates_ips(self, mock_getaddrinfo):
        """Duplicate IPs in getaddrinfo result are deduplicated."""
        mock_getaddrinfo.return_value = [_addrinfo4('1.1.1.1'), _addrinfo4('1.1.1.1')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'cloudflare.com': {'enabled': True, 'host': 'cloudflare.com'},
        }}}
        od = self.Watchful(create_mock_monitor(config)).check().list['cloudflare.com']['other_data']
        assert od['resolved'].count('1.1.1.1') == 1

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_check_empty_host_uses_key(self, mock_getaddrinfo):
        """Empty host field falls back to item key."""
        mock_getaddrinfo.return_value = [_addrinfo4('93.184.216.34')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': ''},
        }}}
        od = self.Watchful(create_mock_monitor(config)).check().list['example.com']['other_data']
        assert od['host'] == 'example.com'

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_check_record_type_aaaa(self, mock_getaddrinfo):
        """AAAA record type uses socket with AF_INET6 family."""
        mock_getaddrinfo.return_value = [_addrinfo6('2606:2800:220:1:248:1893:25c8:1946')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'record_type': 'AAAA'},
        }}}
        od = self.Watchful(create_mock_monitor(config)).check().list['example.com']['other_data']
        assert od['record_type'] == 'AAAA'
        assert od['resolved']
        # AF_INET6 was passed to getaddrinfo
        args = mock_getaddrinfo.call_args
        assert args[0][2] == socket.AF_INET6

    @patch('watchfuls.dns._resolve_dns', return_value=['mail.example.com'])
    def test_check_mx_record_via_dnspython(self, mock_resolve):
        """MX record type calls _resolve_dns (dnspython path)."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'record_type': 'MX'},
        }}}
        item = self.Watchful(create_mock_monitor(config)).check().list['example.com']
        assert item['status'] is True
        assert item['other_data']['record_type'] == 'MX'
        mock_resolve.assert_called_once_with('example.com', 'MX', 5)

    @patch('watchfuls.dns._resolve_dns', return_value=['v=spf1 include:example.com ~all'])
    def test_check_txt_expected_match(self, _):
        """TXT expected value matched as substring → status True."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {
                'enabled': True, 'host': 'example.com',
                'record_type': 'TXT', 'expected': 'v=spf1',
            },
        }}}
        assert self.Watchful(create_mock_monitor(config)).check().list['example.com']['status'] is True

    @patch('watchfuls.dns._resolve_dns', side_effect=ImportError('dnspython not installed'))
    def test_check_non_a_without_dnspython_returns_false(self, _):
        """Non-A/AAAA query without dnspython → status False with error message."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'record_type': 'MX'},
        }}}
        item = self.Watchful(create_mock_monitor(config)).check().list['example.com']
        assert item['status'] is False
        assert 'dnspython' in item['message'].lower()

    @patch('watchfuls.dns._resolve_dns', return_value=[])
    def test_check_dns_no_results_is_false(self, _):
        """Non-A query that returns empty list → status False."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'record_type': 'CNAME'},
        }}}
        assert self.Watchful(create_mock_monitor(config)).check().list['example.com']['status'] is False
