#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/proxmox from the second 2026-10-12 audit (WF-12).

An IPv6 node address went into ``https://2001:db8::5:8006`` - not a URL anything can
connect to - and the SSRF guard parsed that host as ``2001``, which does not resolve and so
was let through (an IPv6 link-local or metadata address was never checked). No request is
made: the token path builds the connection without calling the API.
"""

import pytest

from watchfuls.proxmox.client import PveClient, PveError, url_host


class TestUrlHost:

    @pytest.mark.parametrize('host, want', [
        ('2001:db8::5', '[2001:db8::5]'), ('[2001:db8::5]', '[2001:db8::5]'),
        ('192.0.2.5', '192.0.2.5'), ('pve.example.test', 'pve.example.test')])
    def test_brackets_only_ipv6(self, host, want):
        assert url_host(host) == want


class TestConnectUrl:

    def _connect(self, host):
        return PveClient._connect(host, 8006, True, 5, 'token', 'root@pam!t', 'secret', '', '')

    def test_ipv6_base_url_is_bracketed(self):
        conn = self._connect('2001:db8::5')
        assert conn['base'] == 'https://[2001:db8::5]:8006/api2/json'

    def test_ipv6_link_local_is_refused_by_the_guard(self):
        with pytest.raises(PveError) as exc:
            self._connect('fe80::1')
        assert 'link-local' in str(exc.value)

    def test_ipv4_unchanged(self):
        assert self._connect('192.0.2.5')['base'] == 'https://192.0.2.5:8006/api2/json'
