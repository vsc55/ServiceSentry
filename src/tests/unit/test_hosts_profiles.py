#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host connection-profile catalog (lib/core/hosts/profiles.py)."""

from lib.core.hosts.profiles import (
    host_profiles_catalog,
    module_host_collections,
    module_host_fields,
    module_host_multiple,
)


class TestCatalog:

    def test_protocols_discovered(self):
        cat = host_profiles_catalog()
        # The annotated modules contribute their protocols.  'db' is NOT here:
        # datastore's DB endpoint is address-only (it stays an editable per-check
        # field, like web's 'url'), so it carries no configurable profile.
        for proto in ('snmp', 'ssh', 'icmp', 'tls', 'ntp'):
            assert proto in cat, proto

    def test_snmp_profile_is_address_only(self):
        # SNMP settings (community/version/v3) are per-check now; the host
        # profile only carries the address.
        cat = host_profiles_catalog()
        snmp = cat['snmp']
        assert snmp['module'] == 'snmp'
        assert snmp['address_field'] == 'host'
        assert [f['name'] for f in snmp['fields']] == ['host']

    def test_ssh_is_core_builtin(self):
        # SSH is a property of the server itself, so the core owns it: the
        # catalog always exposes ssh as a built-in profile (module '__host__'),
        # overriding any module-declared ssh.
        cat = host_profiles_catalog()
        assert cat['ssh']['module'] == '__host__'
        assert cat['ssh'].get('builtin') is True
        assert cat['ssh']['address_field'] == 'ssh_host'   # fed from host.address
        names = [f['name'] for f in cat['ssh']['fields']]
        assert 'ssh_key_string' in names                   # inline private key support
        for fn in ('ssh_password', 'ssh_key_string'):
            f = next(x for x in cat['ssh']['fields'] if x['name'] == fn)
            assert f.get('sensitive') or f.get('secret')
        # Auth-method selector (password / file / text), defaulting to password.
        meth = next(x for x in cat['ssh']['fields'] if x['name'] == 'ssh_auth_method')
        assert meth['default'] == 'password'
        assert set(meth['options']) == {'password', 'file', 'text'}
        # The credential fields are gated by the method.
        for fn, m in (('ssh_password', 'password'), ('ssh_key', 'file'), ('ssh_key_string', 'text')):
            f = next(x for x in cat['ssh']['fields'] if x['name'] == fn)
            assert f.get('show_when', {}).get('ssh_auth_method') == [m]

    def test_datastore_db_endpoint_is_not_a_profile(self):
        # datastore's DB endpoint ('host') is an editable per-check field (like
        # web's 'url'), not a host-owned profile — so it never auto-hides when a
        # server is bound (SSH-tunnelled DBs may target a different box).
        cat = host_profiles_catalog()
        assert 'db' not in cat

    def test_module_host_specs_preserves_datastore_ssh(self):
        # The migration relies on the module's own __host_profile__ (not the
        # catalog) so datastore's ssh tunnel fields are still recognised.
        from lib.core.hosts.profiles import module_host_specs
        specs = module_host_specs()
        protos = {p for p, _, _ in specs.get('datastore', [])}
        assert 'ssh' in protos   # the ssh tunnel is the host-owned profile

    def test_module_host_fields(self):
        m = module_host_fields()
        assert 'host' in m['ping']
        # Host-owned = the address only (per-protocol settings live on the
        # check now — there is no Credentials section anymore).
        assert m['ssl_cert'] == ['host']
        assert m['snmp'] == ['host']           # community/version are per-check
        # web hides nothing: 'url' stays visible so one host (a reverse proxy)
        # can carry several FQDNs — blank url falls back to the host address.
        assert 'web' not in m or 'url' not in m['web']
        # datastore host-owns ONLY the ssh tunnel; 'host' (the DB endpoint) stays
        # an editable per-check field so an SSH-tunnelled DB can target another
        # box (docker/internal), and the per-DB creds stay on the check too.
        assert 'ssh_host' in m['datastore']
        assert 'host' not in m.get('datastore', [])
        assert 'password' not in m['datastore'] and 'user' not in m['datastore']

    def test_module_host_multiple(self):
        # Multiple checks per host is opt-in via __host_multiple__ in the schema.
        m = module_host_multiple()
        assert m.get('datastore') is True   # mysql + postgres on one server
        assert m.get('web') is True         # several URLs on one host
        assert m.get('ssl_cert') is True    # several TLS services / ports
        assert m.get('ping') is False       # one ping per host
        assert m.get('ntp') is False and m.get('snmp') is False
        assert m.get('dns') is True         # host-aware: query via SSH from a host

    def test_module_host_multi_bind(self):
        # One check binding to several hosts is opt-in via __host_multiple_bind__.
        from lib.core.hosts.profiles import module_host_multi_bind
        m = module_host_multi_bind()
        assert m.get('proxmox') is True     # cluster: one check spans member nodes
        assert m.get('ping') is False       # single-host check
        assert m.get('datastore') is False  # several checks per host, but one host each

    def test_module_member_fields(self):
        # A multi-bind module may declare a per-node member field (__member_field__).
        from lib.core.hosts.profiles import module_member_fields
        m = module_member_fields()
        assert m.get('keepalived') == 'priority'   # keepalived's per-node weight
        assert 'proxmox' not in m                  # proxmox uses the node <select>
        assert 'ping' not in m

    def test_module_status_render(self):
        # Status-card decorations are opt-in via __status_render__ (discovered).
        from lib.core.hosts.profiles import module_status_render
        m = module_status_render()
        assert m.get('web') == [{'type': 'badge', 'field': 'code', 'prefix': 'HTTP '}]
        fs = m.get('filesystemusage')
        assert fs and fs[0]['type'] == 'bar' and fs[0]['value'] == 'used'
        assert 'ping' not in m                     # no decoration declared

    def test_module_host_collections(self):
        m = module_host_collections()
        # Every host-centric module exposes a host-capable item collection, so the
        # host picker appears on ALL module items (not just those with inline
        # connection fields).
        for mod in ('ups', 'cpu', 'dns', 'ram_swap', 'web', 'ping', 'ssl_cert',
                    'ntp', 'datastore', 'process', 'raid', 'service_status',
                    'temperature', 'hddtemp', 'filesystemusage'):
            assert m.get(mod) == ['list'], f'{mod}: {m.get(mod)}'
        # snmp binds at the 'servers' level; its nested 'checks' never binds.
        assert m.get('snmp') == ['servers']

    def test_missing_dir_is_empty(self, tmp_path):
        assert host_profiles_catalog(str(tmp_path / 'nope')) == {}
        assert module_host_fields(str(tmp_path / 'nope')) == {}
        assert module_host_collections(str(tmp_path / 'nope')) == {}
