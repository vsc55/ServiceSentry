#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for watchfuls/dns."""

import socket
import pytest
from unittest.mock import patch, MagicMock
from conftest import create_mock_monitor


@pytest.fixture(autouse=True)
def _force_non_windows(monkeypatch):
    """Most tests exercise the cross-platform dnspython/socket resolution; force
    the non-Windows path so they don't dispatch to Resolve-DnsName on a Windows
    CI/dev box (the Windows path has its own dedicated tests)."""
    import watchfuls.dns as _d
    monkeypatch.setattr(_d, '_IS_WINDOWS', False)


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
        mock_resolve.assert_called_once_with('example.com', 'MX', 5, '')

    @patch('watchfuls.dns._resolve_socket')
    @patch('watchfuls.dns._resolve_dns', return_value=['1.2.3.4'])
    def test_check_a_with_nameserver_uses_dnspython(self, mock_dns, mock_sock):
        """An A check with an explicit nameserver queries that server via dnspython,
        not the stdlib socket (which can't target a server)."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'example.com': {'enabled': True, 'host': 'example.com', 'record_type': 'A',
                            'nameserver': '192.168.1.1'},
        }}}
        item = self.Watchful(create_mock_monitor(config)).check().list['example.com']
        assert item['status'] is True
        mock_dns.assert_called_once_with('example.com', 'A', 5, '192.168.1.1')
        mock_sock.assert_not_called()

    def test_nameserver_ips_passes_through_ip(self):
        from watchfuls.dns import _nameserver_ips
        assert _nameserver_ips('192.168.1.1') == ['192.168.1.1']
        assert _nameserver_ips('') == []

    def test_resolve_dns_targets_specified_nameserver(self):
        """When a nameserver is given, the query is sent to that server only."""
        from watchfuls import dns as dns_mod
        fake_resolver = MagicMock()
        fake_resolver.resolve.return_value = ['1.2.3.4']
        fake_mod = MagicMock()
        fake_mod.Resolver.return_value = fake_resolver
        fake_mod.NXDOMAIN = type('NXDOMAIN', (Exception,), {})
        fake_mod.NoAnswer = type('NoAnswer', (Exception,), {})
        with patch('watchfuls.dns._load_dns_resolver', return_value=fake_mod):
            out = dns_mod._resolve_dns('cerebelum.lan', 'A', 5, '192.168.110.253')
        assert fake_resolver.nameservers == ['192.168.110.253']
        assert out == ['1.2.3.4']

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


class TestDnsHardening:
    """Regression tests for the timeout / matching / error-reporting fixes."""

    def setup_method(self):
        from watchfuls.dns import Watchful
        self.Watchful = Watchful

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_a_expected_requires_exact_match(self, mock_getaddrinfo):
        """A-record 'expected' must match exactly, not as a substring
        ('1.2.3.4' must NOT match '11.2.3.40')."""
        mock_getaddrinfo.return_value = [_addrinfo4('11.2.3.40')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'x': {'enabled': True, 'host': 'x', 'record_type': 'A', 'expected': '1.2.3.4'},
        }}}
        assert self.Watchful(create_mock_monitor(config)).check().list['x']['status'] is False

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_other_data_has_response_time(self, mock_getaddrinfo):
        """other_data exposes a numeric response_time (ms) for the latency chart."""
        mock_getaddrinfo.return_value = [_addrinfo4('1.1.1.1')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'x': {'enabled': True, 'host': 'x'},
        }}}
        od = self.Watchful(create_mock_monitor(config)).check().list['x']['other_data']
        assert isinstance(od.get('response_time'), (int, float))

    @patch('watchfuls.dns.socket.getaddrinfo')
    def test_non_numeric_timeout_does_not_crash(self, mock_getaddrinfo):
        """A bad (non-numeric) timeout in config must not abort the whole check."""
        mock_getaddrinfo.return_value = [_addrinfo4('1.1.1.1')]
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'x': {'enabled': True, 'host': 'x', 'timeout': 'abc'},
        }}}
        assert self.Watchful(create_mock_monitor(config)).check().list['x']['status'] is True

    @patch('watchfuls.dns.socket.getaddrinfo', side_effect=OSError('network down'))
    def test_socket_network_error_is_reported(self, _):
        """A non-resolution OSError is surfaced as an error, not 'no results'."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'x': {'enabled': True, 'host': 'x'},
        }}}
        item = self.Watchful(create_mock_monitor(config)).check().list['x']
        assert item['status'] is False
        assert 'network down' in item['message']

    @patch('watchfuls.dns.socket.getaddrinfo', side_effect=socket.gaierror('name not found'))
    def test_socket_gaierror_is_no_results(self, _):
        """A name that does not resolve (gaierror) → 'no results', not an error."""
        config = {'watchfuls.dns': {'timeout': 5, 'list': {
            'x': {'enabled': True, 'host': 'x'},
        }}}
        item = self.Watchful(create_mock_monitor(config)).check().list['x']
        assert item['status'] is False
        assert 'no results' in item['message'].lower()


class TestDnsDiscovery:
    """Discovery action: apex record-type probe + optional AXFR zone transfer."""

    def setup_method(self):
        from watchfuls.dns import Watchful
        self.Watchful = Watchful

    def test_actions_declared_and_read_only(self):
        assert 'discover' in self.Watchful.WATCHFUL_ACTIONS
        assert 'discover' in self.Watchful.READ_ONLY_ACTIONS

    def test_empty_domain_returns_empty(self):
        assert self.Watchful.discover({'_discovery_input': {}}) == []
        assert self.Watchful.discover({}) == []

    @patch('watchfuls.dns._resolve_dns')
    def test_probe_returns_existing_types(self, mock_resolve):
        """Probe returns one entry per record type that resolves; empties skipped."""
        mock_resolve.side_effect = lambda host, rt, to: {
            'A': ['1.2.3.4'], 'MX': ['10 mail.example.com'],
        }.get(rt, [])
        res = self.Watchful.discover(
            {'timeout': 5, '_discovery_input': {'domain': 'example.com'}})
        by_type = {r['record_type']: r for r in res}
        assert set(by_type) == {'A', 'MX'}
        assert by_type['A']['name'] == 'example.com'
        assert by_type['A']['category'] == 'address'
        assert '1.2.3.4' in by_type['A']['value']
        # fill_value is the clean first record used to pre-fill "expected".
        assert by_type['A']['fill_value'] == '1.2.3.4'

    @patch('watchfuls.dns.Watchful._discover_probe', return_value=[{'name': 'probe'}])
    @patch('watchfuls.dns.Watchful._discover_axfr', return_value=[{'name': 'axfr'}])
    def test_axfr_flag_selects_mode(self, mock_axfr, mock_probe):
        off = self.Watchful.discover(
            {'_discovery_input': {'domain': 'example.com', 'axfr': False}})
        assert off == [{'name': 'probe'}]
        on = self.Watchful.discover(
            {'_discovery_input': {'domain': 'example.com', 'axfr': True}})
        assert on == [{'name': 'axfr'}]
        # String "true" (from a form checkbox round-trip) also enables AXFR.
        on2 = self.Watchful.discover(
            {'_discovery_input': {'domain': 'example.com', 'axfr': 'true'}})
        assert on2 == [{'name': 'axfr'}]

    @patch('watchfuls.dns.Watchful._discover_axfr', side_effect=Exception('refused'))
    def test_axfr_failure_returns_empty(self, _):
        """AXFR is best-effort: a refused/timed-out transfer yields [] (no 500)."""
        assert self.Watchful.discover(
            {'_discovery_input': {'domain': 'example.com', 'axfr': True}}) == []


class _FakeStore:
    def __init__(self, hosts):
        self._h = hosts
    def get(self, uid, **_kw):
        return self._h.get(uid)


def _remote_host(os='linux'):
    return {'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': os,
            'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'root'}}}


def _local_host(os='linux'):
    return {'uid': 'h1', 'address': '127.0.0.1', 'kind': 'local', 'os': os,
            'maintenance': False, 'profiles': {}}


class TestDnsRemote:
    """Host-aware DNS: the query runs ON the bound host via SSH (dig/nslookup)."""

    def _w(self, items, host=None):
        from watchfuls.dns import Watchful
        mm = create_mock_monitor({'watchfuls.dns': {'list': items}})
        mm._hosts_store = _FakeStore({'h1': host or _remote_host()})
        return Watchful(mm)

    def test_remote_a_via_dig_targets_nameserver(self):
        w = self._w({'c': {'enabled': True, 'host': 'cerebelum.lan', 'record_type': 'A',
                           'host_uid': 'h1', 'nameserver': '192.168.110.253'}})
        with patch.object(w, 'host_exec', return_value=('192.168.110.10\n', '', 0)) as he:
            items = w.check().list
        cmd = he.call_args.args[1]
        assert 'dig' in cmd and '@192.168.110.253' in cmd
        assert items['c']['status'] is True
        assert items['c']['other_data']['resolved'] == ['192.168.110.10']

    def test_local_host_also_uses_dig(self):
        from watchfuls.dns import Watchful
        mm = create_mock_monitor({'watchfuls.dns': {'list': {
            'c': {'enabled': True, 'host': 'x.lan', 'record_type': 'A', 'host_uid': 'h1'}}}})
        mm._hosts_store = _FakeStore({'h1': _local_host()})
        w = Watchful(mm)
        with patch.object(w, 'host_exec', return_value=('1.2.3.4\n', '', 0)) as he:
            items = w.check().list
        assert 'dig' in he.call_args.args[1]   # local host runs dig too (not dnspython)
        assert items['c']['status'] is True

    def test_remote_failure_reports_error(self):
        w = self._w({'c': {'enabled': True, 'host': 'x.lan', 'record_type': 'NS',
                           'host_uid': 'h1'}})
        with patch.object(w, 'host_exec', return_value=('', ';; connection timed out', 9)):
            items = w.check().list
        assert items['c']['status'] is False
        assert 'timed out' in items['c']['message'].lower()

    def test_parse_dig_short(self):
        from watchfuls.dns import _parse_dig_short
        assert _parse_dig_short('A', '1.2.3.4\n5.6.7.8\n') == ['1.2.3.4', '5.6.7.8']
        assert _parse_dig_short('MX', '10 mail.example.com.\n') == ['10 mail.example.com']
        assert _parse_dig_short('TXT', '"v=spf1 ~all"\n') == ['v=spf1 ~all']
        assert _parse_dig_short('NS', 'ns1.example.com.\n') == ['ns1.example.com']

    def test_discover_probe_remote_parses_combined(self):
        from watchfuls.dns import Watchful
        out = "##A##\n1.2.3.4\n##AAAA##\n##MX##\n10 mail.x.\n"
        with patch('lib.host_runner.run', return_value=(out, '', 0)):
            recs = Watchful._discover_probe_remote(_remote_host(), 'x.lan', 5)
        types = {r['record_type'] for r in recs}
        assert 'A' in types and 'MX' in types and 'AAAA' not in types
        assert next(r for r in recs if r['record_type'] == 'A')['fill_value'] == '1.2.3.4'

    def test_discover_uses_host_via_ssh_when_remote(self):
        from watchfuls.dns import Watchful
        with patch('lib.host_runner.run', return_value=('##A##\n9.9.9.9\n', '', 0)):
            recs = Watchful.discover({'_discovery_input': {'domain': 'x.lan'},
                                      '__host__': _remote_host()})
        assert any(r['record_type'] == 'A' and r['fill_value'] == '9.9.9.9' for r in recs)


class TestDnsWindowsResolver:
    """Windows daemon resolves via the OS DNS Client (Resolve-DnsName), since
    python.exe's direct dnspython queries are commonly firewall-blocked."""

    def test_parse_resolve_dnsname(self):
        from watchfuls.dns import _parse_resolve_dnsname
        recs = [
            {"Type": 15, "NameExchange": "mx1.x.lan", "Preference": 10},
            {"Type": 1, "IPAddress": "1.2.3.4"},   # additional A — filtered out for MX
        ]
        assert _parse_resolve_dnsname('MX', recs) == ['10 mx1.x.lan']
        assert _parse_resolve_dnsname('A', [{"Type": 1, "IPAddress": "1.2.3.4"}]) == ['1.2.3.4']
        assert _parse_resolve_dnsname('TXT', [{"Type": 16, "Strings": ["v=spf1"]}]) == ['v=spf1']
        assert _parse_resolve_dnsname('NS', [{"Type": 2, "NameHost": "ns1.x.lan"}]) == ['ns1.x.lan']
        assert _parse_resolve_dnsname('SOA', [{"Type": 6, "PrimaryServer": "ns1.x.lan",
                                               "SerialNumber": 7}]) == ['ns1.x.lan serial=7']

    def test_resolve_win_invokes_resolve_dnsname(self):
        from watchfuls import dns as d
        out = '[{"Type":15,"NameExchange":"mx1.x.lan","Preference":10}]'
        with patch('watchfuls.dns.subprocess.run',
                   return_value=MagicMock(stdout=out, stderr='', returncode=0)) as run:
            res = d._resolve_win('x.lan', 'MX', '192.168.1.1', 5)
        assert res == ['10 mx1.x.lan']
        cmd = ' '.join(run.call_args.args[0])
        assert 'Resolve-DnsName' in cmd and "-Server '192.168.1.1'" in cmd

    def test_check_on_windows_uses_resolve_dnsname(self, monkeypatch):
        import watchfuls.dns as d
        monkeypatch.setattr(d, '_IS_WINDOWS', True)   # override the autouse fixture
        config = {'watchfuls.dns': {'list': {
            'c': {'enabled': True, 'host': 'x.lan', 'record_type': 'MX'}}}}
        w = d.Watchful(create_mock_monitor(config))
        with patch('watchfuls.dns._resolve_win', return_value=['10 mx1.x.lan']) as rw:
            items = w.check().list
        rw.assert_called_once()
        assert items['c']['status'] is True
        assert items['c']['other_data']['resolved'] == ['10 mx1.x.lan']
