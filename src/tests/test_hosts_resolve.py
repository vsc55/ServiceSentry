#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/core/hosts/resolve.py — shared host-resolution primitives."""

from lib.core.hosts.resolve import host_profile_specs, resolve_os
from lib.util.os_detect import local_os


class TestHostProfileSpecs:

    def test_dict_becomes_single_element_list(self):
        spec = {'key': 'ssh', 'address_field': 'ssh_host'}
        assert host_profile_specs(spec) == [spec]

    def test_list_is_kept_dropping_non_dicts(self):
        a, b = {'key': 'ssh'}, {'key': 'db'}
        assert host_profile_specs([a, 'nope', b, None]) == [a, b]

    def test_none_and_other_types_give_empty(self):
        assert host_profile_specs(None) == []
        assert host_profile_specs('x') == []
        assert host_profile_specs(123) == []


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
