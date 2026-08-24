#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the host connection-profile catalog (lib/core/hosts/profiles.py)."""

from lib.core.hosts.profiles import (
    core_profiles,
    host_profiles_catalog,
    module_host_collections,
    module_host_fields,
    module_host_multiple,
    profile_sampled_modules,
)


class TestCatalog:

    def test_protocols_discovered(self):
        cat = host_profiles_catalog()
        # The annotated modules contribute their protocols.  'db' is NOT here:
        # datastore's DB endpoint is address-only (it stays an editable per-check
        # field, like web's 'url'), so it carries no configurable profile.
        for proto in ('snmp', 'ssh', 'icmp', 'tls', 'ntp'):
            assert proto in cat, proto

    def test_snmp_profile_carries_the_device_identity(self):
        """SNMP is a property of the DEVICE, like SSH: its address, its port, and who you
        have to be to ask it anything.  Carrying only the address made every check re-enter
        the same community, and made the panel's own screens ask for it again.

        The field METADATA comes from the module's own schema — options, show_when, the
        secret flag — so the host form renders v3 exactly as the module tab does, without
        core holding a second copy of what an SNMP credential looks like."""
        cat = host_profiles_catalog()
        snmp = cat['snmp']
        assert snmp['module'] == 'snmp'
        assert snmp['address_field'] == 'host'
        names = [f['name'] for f in snmp['fields']]
        assert names[0] == 'host'
        assert {'port', 'version', 'community', 'device_profiles'} <= set(names)
        assert {'snmpv3_username', 'snmpv3_auth_key', 'snmpv3_priv_key'} <= set(names)
        # How long we wait and how often we retry is not WHO the device is: it stays on
        # the check, or two entries for one box would migrate into two hosts.
        assert 'timeout' not in names and 'retries' not in names
        by_name = {f['name']: f for f in snmp['fields']}
        assert by_name['community'].get('secret') is True
        assert by_name['version'].get('options') == ['1', '2c', '3']
        assert by_name['snmpv3_auth_key'].get('show_when') == {'version': ['3']}
        assert by_name['device_profiles'].get('multi') is True

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
        # SNMP host-owns its identity as well as its address (see the catalog test):
        # the device is who you authenticate to, not a setting of each check.
        assert {'host', 'community', 'version', 'device_profiles'} <= set(m['snmp'])
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



class TestWhatMakesAHostADevice:
    """A connection profile can say that carrying it IS the monitoring.

    A switch, a router or a UPS read over SNMP has no check and no module item: the device
    profiles assigned to it are what gets collected every cycle. Anything asking "what would
    run against this machine" has to be able to answer that BEFORE the first cycle, which is
    exactly when it is asked — and the only answer available until now was what had already
    been recorded, which for a device that has never been sampled is nothing.

    Reported from the screen: a NAS whose module item had just been removed offered to collect
    its ping and left out the collection, so the button that exists to take the first sample
    was the one thing that could not take it.
    """

    def test_a_host_with_device_profiles_is_sampled_by_the_module_that_declared_them(self):
        assert profile_sampled_modules(
            {'profiles': {'snmp': {'cred_uid': 'c', 'device_profiles': 'grp_synology'}}}
        ) == {'snmp'}

    def test_the_field_is_read_in_both_shapes_it_is_stored_in(self):
        """Edited as chips, stored as text — and both reach here."""
        assert profile_sampled_modules(
            {'profiles': {'snmp': {'device_profiles': ['a', 'b']}}}) == {'snmp'}
        assert profile_sampled_modules(
            {'profiles': {'snmp': {'device_profiles': 'a, b'}}}) == {'snmp'}

    def test_the_profile_alone_is_not_enough(self):
        """A community with nothing assigned to it is a device somebody can ASK things of,
        not one anybody is charting: `devices_to_sample` skips it, so this must too, or the
        collection would offer a module that then samples nothing."""
        for empty in ('', '   ', [], ['  '], None):
            assert profile_sampled_modules(
                {'profiles': {'snmp': {'community': 'public', 'device_profiles': empty}}}
            ) == set(), empty

    def test_a_profile_that_declares_no_such_field_never_counts(self):
        """SSH is a way IN, not a collection. Reading "has a profile" as "is sampled" would
        put every machine with credentials on it into every collection."""
        assert profile_sampled_modules(
            {'profiles': {'ssh': {'ssh_user': 'root', 'ssh_password': 'x'}}}) == set()

    def test_a_record_with_nothing_to_go_on(self):
        for host in ({}, None, {'profiles': None}, {'profiles': 'nope'}, {'profiles': {}}):
            assert profile_sampled_modules(host) == set(), host

    def test_the_declared_field_is_the_one_the_module_actually_parses(self):
        """The declaration and the sampler must name the SAME field. They are two files —
        the core reads `samples_when` to decide what to offer, and SNMP reads the field
        itself to decide what to walk — so a rename on one side would produce a button that
        offers a collection nobody runs, with nothing raising anywhere.
        """
        from lib.core.snmp.manifest import HOST_PROFILE          # noqa: PLC0415
        from lib.core.snmp.profiles import assigned              # noqa: PLC0415
        field = HOST_PROFILE['samples_when']
        assert field in {f['name'] for f in HOST_PROFILE['fields']}, (
            'it declares a field the profile does not have')
        assert assigned({field: 'grp_x'}) == ['grp_x'], (
            'the sampler does not read the field the declaration names')
        assert not assigned({field: ''})

    def test_it_is_carried_by_the_catalogue_and_not_invented_here(self):
        core = core_profiles()
        assert core['snmp']['samples_when'] == 'device_profiles'
        assert not core['ssh']['samples_when']
