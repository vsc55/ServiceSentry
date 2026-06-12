#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for host-centric config resolution (Phase 2).

A check (or, for SNMP, a server) may carry a ``host_uid`` instead of inline
connection fields; ``ModuleBase.resolve_host`` merges the referenced host's
address + per-protocol credential profile(s) over it.  Inline items (no
``host_uid``) must be returned unchanged so both styles coexist.
"""

from unittest.mock import patch

from conftest import create_mock_monitor

import watchfuls.ping as ping
import watchfuls.ssl_cert as ssl_cert
import watchfuls.ntp as ntp
import watchfuls.datastore as datastore
import watchfuls.web as web
from watchfuls.snmp import Watchful as SnmpWatchful


class _FakeStore:
    def __init__(self, hosts):
        self._h = hosts

    def get(self, uid):
        return self._h.get(uid)


_HOST = {
    'uid': 'h1', 'address': '10.0.0.9',
    'profiles': {
        'icmp': {},
        'tls':  {'port': 8443},
        'ntp':  {'port': 1230},
        'snmp': {'community': 'sec', 'version': '2c', 'port': 161,
                 'snmpv3_auth_key': 'authk'},
        # datastore: only the address + SSH tunnel are host-owned; the per-DB
        # connection (port/user/password) lives on each check.
        'ssh':  {'ssh_host': 'jump.local', 'ssh_user': 'jduser', 'ssh_password': 'jp'},
        'http': {'scheme': 'https', 'verify_ssl': True,
                 'auth_enabled': True, 'auth_user': 'web', 'auth_password': 'wp'},
    },
}


def _ping(monitor_cfg=None):
    mm = create_mock_monitor({'watchfuls.ping': monitor_cfg or {}})
    mm._hosts_store = _FakeStore({'h1': _HOST})
    return ping.Watchful(mm)


class TestResolveHostGeneric:

    def test_inline_item_unchanged(self):
        w = _ping()
        item = {'host': '1.2.3.4', 'enabled': True}
        assert w.resolve_host(item) == item

    def test_no_store_returns_item(self):
        mm = create_mock_monitor({'watchfuls.ping': {}})
        mm._hosts_store = None
        w = ping.Watchful(mm)
        item = {'host_uid': 'h1'}
        assert w.resolve_host(item) == item

    def test_unknown_host_returns_item(self):
        mm = create_mock_monitor({'watchfuls.ping': {}})
        mm._hosts_store = _FakeStore({})
        w = ping.Watchful(mm)
        item = {'host_uid': 'h1'}
        assert w.resolve_host(item) == item

    def test_address_injected_and_host_wins(self):
        w = _ping()
        # The item's stale (empty) host must be overridden by the host address.
        out = w.resolve_host({'host_uid': 'h1', 'host': '', 'enabled': True})
        assert out['host'] == '10.0.0.9'
        assert out['enabled'] is True   # non-connection field preserved


class TestPerModuleProfiles:

    def test_snmp_merges_community_and_v3(self):
        with patch.object(SnmpWatchful, '_startup_compile_mibs', return_value=None):
            s = SnmpWatchful(create_mock_monitor({'watchfuls.snmp': {}}))
        s._monitor._hosts_store = _FakeStore({'h1': _HOST})
        srv = s.resolve_host({'host_uid': 'h1', 'checks': {}})
        assert srv['host'] == '10.0.0.9'
        assert srv['community'] == 'sec'
        assert srv['version'] == '2c'
        assert srv['snmpv3_auth_key'] == 'authk'

    def test_ssl_cert_merges_host_and_port(self):
        mm = create_mock_monitor({'watchfuls.ssl_cert': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})
        out = ssl_cert.Watchful(mm).resolve_host({'host_uid': 'h1'})
        assert out['host'] == '10.0.0.9' and out['port'] == 8443

    def test_ntp_merges_server_and_port(self):
        mm = create_mock_monitor({'watchfuls.ntp': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})
        out = ntp.Watchful(mm).resolve_host({'host_uid': 'h1'})
        assert out['server'] == '10.0.0.9' and out['port'] == 1230

    def test_datastore_address_and_ssh_from_host_db_creds_from_check(self):
        mm = create_mock_monitor({'watchfuls.datastore': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})
        # The check carries its own per-DB connection (port/user/password); only
        # the address + SSH tunnel come from the host.  This is what lets one host
        # run several DB checks (mysql + postgres) with different credentials.
        out = datastore.Watchful(mm).resolve_host(
            {'host_uid': 'h1', 'db_type': 'postgres',
             'user': 'pg', 'password': 'pgpw', 'port': 5432})
        assert out['host'] == '10.0.0.9'                       # address from host
        assert out['ssh_host'] == 'jump.local'                 # ssh tunnel from host
        assert out['user'] == 'pg' and out['password'] == 'pgpw' and out['port'] == 5432
        assert out['db_type'] == 'postgres'

    def test_web_merges_http_profile_and_keeps_path(self):
        mm = create_mock_monitor({'watchfuls.web': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})
        out = web.Watchful(mm).resolve_host(
            {'host_uid': 'h1', 'path': '/health', 'method': 'GET'})
        assert out['url'] == '10.0.0.9'          # address → url
        assert out['scheme'] == 'https'
        assert out['auth_user'] == 'web' and out['auth_password'] == 'wp'
        assert out['path'] == '/health'          # check field preserved
        assert out['method'] == 'GET'


class TestNonHostModules:
    """DNS targets a domain (no server/credentials) → it must NOT be host-capable."""

    def test_dns_has_no_host_profile(self):
        import watchfuls.dns as dns
        assert '__host_profile__' not in (dns.Watchful.ITEM_SCHEMA or {})

    def test_catalog_excludes_dns(self):
        from lib.host_profiles import host_profiles_catalog, module_host_fields
        cat = host_profiles_catalog()
        assert not any(v['module'] == 'dns' for v in cat.values())
        assert 'dns' not in module_host_fields()


class TestDatastoreResolvedItem:
    """The datastore reads fields via _resolved_item, which must merge the host."""

    def test_resolved_item_inherits_host(self):
        cfg = {'watchfuls.datastore': {'list': {
            'db1': {'host_uid': 'h1', 'db_type': 'postgres', 'enabled': True,
                    'user': 'pg', 'password': 'pgpw', 'port': 5432}}}}
        mm = create_mock_monitor(cfg)
        mm._hosts_store = _FakeStore({'h1': _HOST})
        dw = datastore.Watchful(mm)
        item = dw._resolved_item('db1')
        assert item['host'] == '10.0.0.9'         # address from host
        assert item['ssh_host'] == 'jump.local'   # ssh tunnel from host
        # the per-DB connection stays on the check
        assert item['user'] == 'pg' and item['password'] == 'pgpw' and item['port'] == 5432

    def test_resolved_item_inline_unchanged(self):
        cfg = {'watchfuls.datastore': {'list': {
            'db2': {'host': 'inline.local', 'db_type': 'mysql', 'enabled': True}}}}
        mm = create_mock_monitor(cfg)
        mm._hosts_store = _FakeStore({'h1': _HOST})
        dw = datastore.Watchful(mm)
        assert dw._resolved_item('db2')['host'] == 'inline.local'
