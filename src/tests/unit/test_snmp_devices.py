#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A device is a host that carries an SNMP profile — not a module entry about one.

This is the behaviour that makes "SNMP is configuration on the device" true rather than
merely tidy. Before it, giving a host a community and a set of device profiles bought
nothing until a SECOND thing existed — an entry in the SNMP module pointing back at that
host. The device held the configuration and the module decided it was worth reading.

The tests below pin both halves: that a configured host is sampled with nothing else
present, and the three things this must NOT do — resume a device somebody switched off,
re-sample one an item already covers, or claim a host that carries a community but has been
assigned nothing to measure.
"""

from lib.core.snmp.devices import device_key, devices_to_sample


class _Store:
    def __init__(self, hosts):
        self._hosts = hosts

    def list(self, decrypt=True):        # noqa: A003 - mirrors HostsStore
        return self._hosts


def _host(uid, name='box', profiles=None, **kw):
    h = {'uid': uid, 'name': name, 'address': '10.0.0.9',
         'profiles': profiles if profiles is not None else {}}
    h.update(kw)
    return h


_SNMP = {'community': 'public', 'version': '2c', 'device_profiles': 'sys_generic'}


class TestWhatCountsAsADevice:

    def test_a_host_with_profiles_assigned_is_sampled(self):
        out = devices_to_sample(_Store([_host('h1', 'erebor', {'snmp': _SNMP})]))
        assert len(out) == 1
        key, item = out[0]
        assert key == device_key('h1')
        assert item['host_uid'] == 'h1' and item['enabled'] is True
        assert item['label'] == 'erebor'

    def test_a_host_with_a_community_but_nothing_assigned_is_not(self):
        """Reachable is not the same as worth charting. A community with no profiles is a
        device somebody has not decided about yet, and sampling it would record nothing
        while looking like it worked."""
        prof = {'community': 'public', 'version': '2c'}
        assert devices_to_sample(_Store([_host('h1', profiles={'snmp': prof})])) == []

    def test_a_host_with_no_snmp_profile_is_not(self):
        assert devices_to_sample(_Store([_host('h1', profiles={'ssh': {'ssh_user': 'r'}})])) == []

    def test_an_empty_assignment_string_does_not_count(self):
        prof = dict(_SNMP, device_profiles='   ')
        assert devices_to_sample(_Store([_host('h1', profiles={'snmp': prof})])) == []

    def test_several_hosts_come_back_in_order(self):
        out = devices_to_sample(_Store([
            _host('h1', 'a', {'snmp': _SNMP}),
            _host('h2', 'b', {'ssh': {}}),
            _host('h3', 'c', {'snmp': _SNMP}),
        ]))
        assert [k for k, _ in out] == [device_key('h1'), device_key('h3')]


class TestWhatItRefusesToDecide:

    def test_a_host_an_item_already_speaks_for_is_left_alone(self):
        """Sampling it twice would be two answers to "what is this device doing", filed
        under two keys, with two independent counter baselines."""
        store = _Store([_host('h1', profiles={'snmp': _SNMP})])
        assert devices_to_sample(store, covered={'h1'}) == []

    def test_covering_is_by_uid_and_not_by_name(self):
        store = _Store([_host('h1', 'erebor', {'snmp': _SNMP})])
        assert len(devices_to_sample(store, covered={'erebor'})) == 1

    def test_maintenance_is_not_decided_here(self):
        """It is decided by resolve_host, which every sampled item goes through — one place
        where a host in maintenance stops being read, rather than two that must agree."""
        store = _Store([_host('h1', profiles={'snmp': _SNMP}, maintenance=True)])
        assert len(devices_to_sample(store)) == 1

    def test_it_returns_an_item_and_not_a_connection(self):
        """Building the connection here would be a second implementation of the merge that
        `resolve_host` already does — address, credential, profile fields — and the two would
        disagree the first time either changed."""
        _key, item = devices_to_sample(_Store([_host('h1', profiles={'snmp': _SNMP})]))[0]
        assert set(item) == {'host_uid', 'enabled', 'label'}
        assert 'community' not in item and 'device_profiles' not in item


class TestItCannotTakeACycleDown:

    def test_no_registry_means_no_extra_devices(self):
        assert devices_to_sample(None) == []

    def test_a_registry_that_raises_is_survived(self):
        class _Broken:
            def list(self, decrypt=True):        # noqa: A003
                raise RuntimeError('database is locked')
        assert devices_to_sample(_Broken()) == []

    def test_a_junk_row_is_skipped_not_fatal(self):
        out = devices_to_sample(_Store([None, 'nonsense', _host('h1', profiles={'snmp': _SNMP})]))
        assert [k for k, _ in out] == [device_key('h1')]

    def test_a_host_with_no_uid_is_skipped(self):
        assert devices_to_sample(_Store([_host('', profiles={'snmp': _SNMP})])) == []


class TestTheKeyIsStable:

    def test_it_is_derived_from_the_uid(self):
        """The counter state and the history rows of a device are filed under this key, so a
        key that changed between cycles would restart every rate and split every chart."""
        assert device_key('h1') == 'host.h1'

    def test_it_survives_a_rename(self):
        a = devices_to_sample(_Store([_host('h1', 'old', {'snmp': _SNMP})]))[0][0]
        b = devices_to_sample(_Store([_host('h1', 'new', {'snmp': _SNMP})]))[0][0]
        assert a == b

    def test_it_cannot_collide_with_a_module_item(self):
        """Item keys are bare uids; this one is prefixed, so the two namespaces never meet."""
        from lib.core.snmp.devices import KEY_PREFIX      # noqa: PLC0415
        assert device_key('h1').startswith(KEY_PREFIX) and KEY_PREFIX
