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
    'uid': 'h1', 'address': '10.0.0.9', 'kind': 'remote', 'maintenance': False,
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

    def test_snmp_inherits_only_address(self):
        # The host now provides only the address; SNMP settings (community,
        # version, v3 keys) are per-check, so the check's own values are kept.
        with patch.object(SnmpWatchful, '_startup_compile_mibs', return_value=None):
            s = SnmpWatchful(create_mock_monitor({'watchfuls.snmp': {}}))
        s._monitor._hosts_store = _FakeStore({'h1': _HOST})
        srv = s.resolve_host({'host_uid': 'h1', 'community': 'mine',
                              'version': '3', 'checks': {}})
        assert srv['host'] == '10.0.0.9'           # address inherited from host
        assert srv['community'] == 'mine'          # NOT overridden by the host
        assert srv['version'] == '3'

    def test_ssl_cert_host_address_port_stays_on_check(self):
        # The host owns only the address; each check has its own port (a server
        # can expose several TLS services).  A stale 'port' left in the stored
        # tls profile (pre-schema-evolution data) must NOT clobber the check's.
        mm = create_mock_monitor({'watchfuls.ssl_cert': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})
        out = ssl_cert.Watchful(mm).resolve_host({'host_uid': 'h1', 'port': 9443})
        assert out['host'] == '10.0.0.9'
        assert out['port'] == 9443          # check's own port preserved

    def test_ntp_host_address_port_stays_on_check(self):
        # The host owns only the address; the NTP port is a check setting
        # (Monitoring tab).  A stale 'port' in the stored ntp profile must not
        # clobber the check's value.
        mm = create_mock_monitor({'watchfuls.ntp': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})
        out = ntp.Watchful(mm).resolve_host({'host_uid': 'h1', 'port': 124})
        assert out['server'] == '10.0.0.9'
        assert out['port'] == 124

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
        # The SSH bridge connects to THIS server: ssh_host = host address (the
        # stale ssh_host stored in the profile is ignored — address_field wins).
        assert out['ssh_host'] == '10.0.0.9'
        assert out['ssh_user'] == 'jduser' and out['ssh_password'] == 'jp'
        assert out['user'] == 'pg' and out['password'] == 'pgpw' and out['port'] == 5432
        assert out['db_type'] == 'postgres'

    def test_web_inherits_only_address(self):
        # The host provides only the address (→ url); scheme/auth/etc. are
        # per-check now, so the check's own values are kept.
        mm = create_mock_monitor({'watchfuls.web': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})
        out = web.Watchful(mm).resolve_host(
            {'host_uid': 'h1', 'path': '/health', 'method': 'GET',
             'scheme': 'http', 'auth_user': 'me'})
        assert out['url'] == '10.0.0.9'          # address → url
        assert out['scheme'] == 'http'           # NOT overridden by the host
        assert out['auth_user'] == 'me'
        assert out['path'] == '/health' and out['method'] == 'GET'


class TestHostKindAndMaintenance:
    """Local/remote kind and maintenance mode are core host properties."""

    def test_local_host_skips_ssh_profile(self):
        # A local host is reached directly: its ssh profile must NOT be injected
        # (no tunnel / command bridge), even if one is stored.
        local = {**_HOST, 'kind': 'local'}
        mm = create_mock_monitor({'watchfuls.datastore': {}})
        mm._hosts_store = _FakeStore({'h1': local})
        out = datastore.Watchful(mm).resolve_host(
            {'host_uid': 'h1', 'db_type': 'postgres'})
        assert out['host'] == '10.0.0.9'          # address still inherited
        assert 'ssh_user' not in out              # ssh profile skipped for local

    def test_remote_host_injects_ssh_profile(self):
        mm = create_mock_monitor({'watchfuls.datastore': {}})
        mm._hosts_store = _FakeStore({'h1': _HOST})   # kind == remote
        out = datastore.Watchful(mm).resolve_host(
            {'host_uid': 'h1', 'db_type': 'postgres'})
        assert out['ssh_host'] == '10.0.0.9' and out['ssh_user'] == 'jduser'

    def test_maintenance_disables_check(self):
        # A host in maintenance disables every bound check (modules skip disabled).
        maint = {**_HOST, 'maintenance': True}
        w = _ping()
        w._monitor._hosts_store = _FakeStore({'h1': maint})
        out = w.resolve_host({'host_uid': 'h1', 'enabled': True})
        assert out['enabled'] is False
        assert out['_host_maintenance'] is True

    def test_no_maintenance_keeps_enabled(self):
        w = _ping()
        out = w.resolve_host({'host_uid': 'h1', 'enabled': True})
        assert out.get('enabled') is True
        assert '_host_maintenance' not in out

    def test_host_os_explicit_injected(self):
        w = _ping()
        w._monitor._hosts_store = _FakeStore({'h1': {**_HOST, 'os': 'windows'}})
        out = w.resolve_host({'host_uid': 'h1'})
        assert out['host_os'] == 'windows'

    def test_host_os_auto_local_resolves_to_platform(self):
        from lib import os_detect
        local = {**_HOST, 'kind': 'local', 'os': 'auto'}
        w = _ping()
        w._monitor._hosts_store = _FakeStore({'h1': local})
        out = w.resolve_host({'host_uid': 'h1'})
        assert out['host_os'] == os_detect.local_os()

    def test_host_os_auto_remote_stays_auto(self):
        # Remote 'auto' is resolved over SSH by the consumer, not at resolve time.
        w = _ping()
        w._monitor._hosts_store = _FakeStore({'h1': {**_HOST, 'os': 'auto'}})  # kind remote
        out = w.resolve_host({'host_uid': 'h1'})
        assert out['host_os'] == 'auto'


class TestDnsHostAware:
    """DNS is host-aware: it can bind to a host to run the query over SSH (so a
    host that reaches the DNS server resolves), while inline checks still run on
    the daemon."""

    def test_dns_has_ssh_host_profile(self):
        import watchfuls.dns as dns
        hp = (dns.Watchful.ITEM_SCHEMA or {}).get('__host_profile__')
        assert isinstance(hp, dict) and hp.get('key') == 'ssh'

    def test_dns_in_module_host_fields(self):
        from lib.host_profiles import module_host_fields
        assert 'ssh_host' in module_host_fields().get('dns', [])


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
        assert item['ssh_host'] == '10.0.0.9'     # ssh bridge targets this host
        assert item['ssh_user'] == 'jduser'       # tunnel credentials from host
        # the per-DB connection stays on the check
        assert item['user'] == 'pg' and item['password'] == 'pgpw' and item['port'] == 5432

    def test_resolved_item_inline_unchanged(self):
        cfg = {'watchfuls.datastore': {'list': {
            'db2': {'host': 'inline.local', 'db_type': 'mysql', 'enabled': True}}}}
        mm = create_mock_monitor(cfg)
        mm._hosts_store = _FakeStore({'h1': _HOST})
        dw = datastore.Watchful(mm)
        assert dw._resolved_item('db2')['host'] == 'inline.local'
