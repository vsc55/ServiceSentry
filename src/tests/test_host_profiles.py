#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host connection-profile catalog (lib/host_profiles.py)."""

from lib.host_profiles import (
    host_profiles_catalog,
    module_host_fields,
    module_host_multiple,
)


class TestCatalog:

    def test_protocols_discovered(self):
        cat = host_profiles_catalog()
        # The annotated modules contribute their protocols.
        for proto in ('snmp', 'ssh', 'db', 'icmp', 'tls', 'ntp'):
            assert proto in cat, proto

    def test_snmp_profile_fields_and_meta(self):
        cat = host_profiles_catalog()
        snmp = cat['snmp']
        assert snmp['module'] == 'snmp'
        assert snmp['address_field'] == 'host'
        names = [f['name'] for f in snmp['fields']]
        assert 'community' in names and 'snmpv3_auth_key' in names
        # Field metadata is carried through (options, secret, i18n labels).
        auth_key = next(f for f in snmp['fields'] if f['name'] == 'snmpv3_auth_key')
        assert auth_key.get('secret') is True
        version = next(f for f in snmp['fields'] if f['name'] == 'version')
        assert version.get('options')  # the SNMP version dropdown

    def test_datastore_has_two_protocols(self):
        cat = host_profiles_catalog()
        assert cat['ssh']['module'] == 'datastore'
        assert cat['db']['module'] == 'datastore'
        assert cat['ssh']['address_field'] is None      # ssh_host lives in the profile
        assert cat['db']['address_field'] == 'host'
        ssh_pass = next(f for f in cat['ssh']['fields'] if f['name'] == 'ssh_password')
        assert ssh_pass.get('sensitive') or ssh_pass.get('secret')

    def test_module_host_fields(self):
        m = module_host_fields()
        assert 'host' in m['ping']
        assert set(['host', 'port']) <= set(m['ssl_cert'])
        assert 'community' in m['snmp']
        # datastore host-owns the address + the ssh tunnel; the per-DB
        # connection (user/password/port) stays on each check, not the host.
        assert 'host' in m['datastore'] and 'ssh_host' in m['datastore']
        assert 'password' not in m['datastore'] and 'user' not in m['datastore']

    def test_module_host_multiple(self):
        # Multiple checks per host is opt-in via __host_multiple__ in the schema.
        m = module_host_multiple()
        assert m.get('datastore') is True   # mysql + postgres on one server
        assert m.get('web') is True         # several URLs on one host
        assert m.get('ping') is False       # one ping per host
        assert m.get('ntp') is False and m.get('snmp') is False
        assert 'dns' not in m               # not host-capable

    def test_missing_dir_is_empty(self, tmp_path):
        assert host_profiles_catalog(str(tmp_path / 'nope')) == {}
        assert module_host_fields(str(tmp_path / 'nope')) == {}
