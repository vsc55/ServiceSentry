#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/core/hosts/resolve.py — shared host-resolution primitives."""

from lib.core.hosts.resolve import (HOST_RESULT_PREFIX, host_profile_specs,
                                    host_result_key, host_uid_from_key, resolve_os)
from lib.util.os_detect import local_os


class TestHostProfileSpecs:

    def test_dict_becomes_single_element_list(self):
        spec = {'key': 'proprietary', 'address_field': 'addr'}
        assert host_profile_specs(spec) == [spec]

    def test_list_is_kept_dropping_non_dicts(self):
        a, b = {'key': 'proprietary'}, {'key': 'db'}
        assert host_profile_specs([a, 'nope', b, None]) == [a, b]

    def test_none_and_other_types_give_empty(self):
        assert host_profile_specs(None) == []
        assert host_profile_specs('x') == []
        assert host_profile_specs(123) == []

    def test_a_core_owned_protocol_brings_its_own_fields(self):
        """A module names the protocol it binds to; WHICH fields that protocol has is not
        the module's to state. Eleven of them stated it anyway — ten repeating the same
        seven SSH names — and the catalogue overrode every copy for the form it draws, so a
        copy that drifted did not change the form: it changed which values a bound host was
        allowed to push onto the check, silently."""
        from lib.core.hosts.profiles import core_profile_field_names
        [spec] = host_profile_specs({'key': 'ssh', 'address_field': 'ssh_host'})
        assert spec['fields'] == ['ssh_host'] + list(core_profile_field_names('ssh'))
        assert spec['address_field'] == 'ssh_host', 'the module still says where it lands'

    def test_the_address_field_is_part_of_it(self):
        """It is the field that RECEIVES the host's address, so a bound check must not draw
        it or keep its own value in it. `datastore` has a real ``ssh_host`` box on its
        items, and leaving it out of the list would put that box back on a bound check."""
        [spec] = host_profile_specs({'key': 'snmp', 'address_field': 'host'})
        assert spec['fields'][0] == 'host'

    def test_a_protocol_the_core_does_not_own_is_left_alone(self):
        """``web`` declares ``http`` and no fields, and its ``server`` box is visible on
        purpose: one host behind a reverse proxy serves several FQDNs. Filling in a list the
        core never declared would hide it."""
        spec = {'key': 'http', 'address_field': 'server', 'fields': []}
        assert host_profile_specs(spec) == [spec]


class TestResolveOs:

    def test_concrete_value_is_lowercased(self):
        assert resolve_os('Linux', is_remote=False) == 'linux'
        assert resolve_os('WINDOWS', is_remote=True) == 'windows'

    def test_auto_local_resolves_to_platform(self):
        assert resolve_os('auto', is_remote=False) == local_os()
        # blank/None behave as 'auto'
        assert resolve_os('', is_remote=False) == local_os()
        assert resolve_os(None, is_remote=False) == local_os()

    def test_auto_remote_keeps_auto_by_default(self):
        # The monitor keeps 'auto' to resolve later over SSH.
        assert resolve_os('auto', is_remote=True) == 'auto'

    def test_auto_remote_honours_remote_default(self):
        # The web discovery flow assumes 'linux'.
        assert resolve_os('auto', is_remote=True, remote_auto='linux') == 'linux'


class TestAResultThatBelongsToAHost:
    """Some results have no check behind them: a device the panel reads because the HOST says
    it is one. They still belong to a host, and the Servers tab has to be able to say so — or
    a device can be sampled, found down, and still show a neutral dash."""

    def test_a_key_round_trips(self):
        assert host_uid_from_key(host_result_key('abc123')) == 'abc123'

    def test_the_composite_suffix_is_tolerated(self):
        """The recorders already file `<key>/<metric>`, so this has to read through it."""
        assert host_uid_from_key('host.abc123/metrics') == 'abc123'

    def test_a_check_key_names_no_host(self):
        """The two namespaces must never be confused: an item key is a bare uid, and
        answering a host uid for one would attribute a check to a machine at random."""
        for key in ('abc123', 'abc123/metrics', 'srv_1.chk_2', '', None):
            assert host_uid_from_key(key) == ''

    def test_a_key_that_merely_starts_with_the_word_is_not_one(self):
        """The prefix ends in a separator for this reason: without it, an item somebody
        named `hostname` would be read as the host `name`."""
        assert host_result_key('x').startswith(HOST_RESULT_PREFIX)
        assert host_uid_from_key('hostname') == ''
        assert host_uid_from_key('hostile/metrics') == ''
