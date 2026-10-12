#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/dns from the second 2026-10-12 audit (WF-1/NET-1, NET-5).

The record type reached a command line unquoted (`Resolve-DnsName -Type A;<cmd>` in a local
PowerShell on a Windows panel), and the remote `nslookup` relied on cmd.exe double quotes,
which PowerShell expands. Nothing here starts a process or touches the network: the
command builders are pure, and `subprocess.run` / `device_exec` are patched.
"""

import json
import os
from unittest.mock import patch

import pytest

from conftest import create_mock_monitor

from watchfuls.dns import client, tables

_PAYLOAD = "$(New-Item -ItemType File -Path 'pwn')"


class _FakeStore:
    def __init__(self, devices):
        self._d = devices

    def get(self, uid, **_kw):
        return self._d.get(uid)


def _windows_device():
    return {'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'os': 'windows',
            'maintenance': False, 'profiles': {'ssh': {'ssh_user': 'admin'}}}


class TestRecordTypeWhitelist:

    @pytest.mark.parametrize('bad', ['A;calc', 'A | whoami', "A'", 'A`', '$(x)', 'HINFO', ''])
    def test_unknown_type_is_refused(self, bad):
        with pytest.raises(ValueError):
            tables.safe_record_type(bad)

    def test_known_types_pass_upper_cased(self):
        assert tables.safe_record_type(' mx ') == 'MX'
        assert tables.safe_record_type('caa') == 'CAA'

    def test_resolve_win_never_runs_a_bad_type(self):
        with patch.object(client.subprocess, 'run') as run:
            with pytest.raises(ValueError):
                client._resolve_win('example.test', 'A;calc', '', 5)
        run.assert_not_called()

    def test_remote_command_refuses_a_bad_type(self):
        for os_ in ('windows', 'linux'):
            with pytest.raises(ValueError):
                client._remote_dns_cmd(os_, 'example.test', 'A&calc', '', 5)

    def test_check_reports_error_without_running_anything(self):
        from watchfuls.dns import Watchful
        mm = create_mock_monitor({'watchfuls.dns': {'list': {
            'c': {'enabled': True, 'host': 'example.test', 'record_type': 'A;calc',
                  'device_uid': 'h1'}}}})
        mm._devices_store = _FakeStore({'h1': _windows_device()})
        w = Watchful(mm)
        with patch.object(w, 'device_exec') as de, \
                patch.object(client.subprocess, 'run') as run:
            items = w.check().list
        de.assert_not_called()
        run.assert_not_called()
        assert items['c']['status'] is False

    def test_schema_options_are_all_known_types(self):
        """The dropdown and the whitelist are one list: a type the schema offers but the
        whitelist refuses would be a check that can be saved and can never run."""
        here = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        with open(os.path.join(here, 'schema.json'), encoding='utf-8') as f:
            opts = json.load(f)['list']['record_type']['options']
        assert set(opts) <= tables._KNOWN_TYPES
        # Discovery stores CAA/SRV records: the save must accept what discovery offers.
        assert {'CAA', 'SRV'} <= set(opts)


class TestRemoteWindowsQuoting:
    """The remote shell may be cmd.exe or PowerShell: the values are restricted, since no
    quoting is safe in both."""

    def test_host_with_powershell_subexpression_is_refused(self):
        with pytest.raises(ValueError):
            client._remote_dns_cmd('windows', _PAYLOAD, 'A', '', 5)

    @pytest.mark.parametrize('bad', ['a"b', 'a%PATH%', 'a&b', 'a`b', 'a b', '-opt'])
    def test_nameserver_with_shell_characters_is_refused(self, bad):
        with pytest.raises(ValueError):
            client._remote_dns_cmd('windows', 'example.test', 'A', bad, 5)

    def test_hostname_ipv6_and_srv_labels_still_work(self):
        cmd = client._remote_dns_cmd('windows', '_sip._tcp.example.test', 'srv', '2001:db8::53', 5)
        assert cmd == 'nslookup -type=SRV "_sip._tcp.example.test" "2001:db8::53"'
        assert '$' not in cmd

    def test_bound_check_with_injected_host_runs_nothing(self):
        from watchfuls.dns import Watchful
        mm = create_mock_monitor({'watchfuls.dns': {'list': {
            'c': {'enabled': True, 'host': _PAYLOAD, 'record_type': 'A', 'device_uid': 'h1'}}}})
        mm._devices_store = _FakeStore({'h1': _windows_device()})
        w = Watchful(mm)
        with patch.object(w, 'device_exec') as de:
            items = w.check().list
        de.assert_not_called()
        assert items['c']['status'] is False


class TestNslookupAnyLanguage:
    """A/AAAA answers are read by shape, not by a localised 'Address' label."""

    _FR = ("Serveur :   dns.example.test\nAddress:  192.0.2.53\n\n"
           "Réponse ne faisant pas autorité :\nNom :    www.example.test\n"
           "Adresses:  192.0.2.10\n          192.0.2.11\n\n")
    _DE = ("Server:  dns.example.test\nAddress:  192.0.2.53\n\n"
           "Nicht autorisierende Antwort:\nName:    www.example.test\n"
           "Adresse:  192.0.2.30\n\n")

    def test_french_addresses(self):
        assert client._parse_nslookup('A', self._FR) == ['192.0.2.10', '192.0.2.11']

    def test_german_address(self):
        assert client._parse_nslookup('A', self._DE) == ['192.0.2.30']

    def test_server_block_is_still_skipped(self):
        assert '192.0.2.53' not in client._parse_nslookup('A', self._DE)

    def test_aliases_line_is_not_an_answer(self):
        out = ("Server:  dns.example.test\nAddress:  192.0.2.53\n\n"
               "Name:    real.example.test\nAddress:  192.0.2.40\n"
               "Aliases:  www.example.test\n\n")
        assert client._parse_nslookup('A', out) == ['192.0.2.40']


class TestDiscoveryStaysInsideTheWhitelist:

    def test_probe_types_drop_unknown_entries(self):
        from watchfuls.dns import Watchful
        with patch.dict('watchfuls.dns.actions._SCHEMA',
                        {'list': {'__discovery_probe_types__': ['A', 'A;calc', 'TXT']}}):
            assert Watchful._probe_types() == ['A', 'TXT']

    def test_remote_windows_probe_refuses_injected_domain(self):
        from watchfuls.dns import Watchful
        with patch('lib.core.devices.runner.run') as run:
            assert Watchful._discover_probe_remote({'os': 'windows'}, _PAYLOAD, 5) == []
        run.assert_not_called()
