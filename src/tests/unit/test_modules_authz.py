#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Who may write which check — the one save in the panel that crosses domains.

A check belongs to a module and is BOUND to a host, so "may this person write here" cannot
be answered by the module flag alone: a per-server permission (`server.<uid>.edit`) exists
precisely to confine somebody to their own machines. These tests pin the boundary of that
confinement, which is where an authorisation bug hides in plain sight — the screen looks the
same either way.

No app, no DB, no HTTP: `authorize_module_write` is given the permission set and the two
payloads, which is exactly how the route calls it.
"""

from lib.core.modules import authz

MINE = {'server.mine.edit', 'server.mine.add'}


def _mod(**items):
    return {'list': items}


class TestAPerServerHolderStaysOnTheirOwnHosts:

    def test_they_may_edit_a_check_on_their_host(self):
        old = _mod(i1={'uid': 'i1', 'host_uid': 'mine', 'label': 'a'})
        new = _mod(i1={'uid': 'i1', 'host_uid': 'mine', 'label': 'b'})
        assert authz.authorize_module_write('ping', old, new, MINE) is True

    def test_they_may_add_one_to_their_host(self):
        old = _mod()
        new = _mod(i2={'uid': 'i2', 'host_uid': 'mine', 'label': 'a'})
        assert authz.authorize_module_write('ping', old, new, MINE) is True

    def test_they_may_not_edit_a_check_on_another_host(self):
        old = _mod(i3={'uid': 'i3', 'host_uid': 'victim', 'label': 'a'})
        new = _mod(i3={'uid': 'i3', 'host_uid': 'victim', 'label': 'CHANGED'})
        assert authz.authorize_module_write('ping', old, new, MINE) is False

    def test_they_may_not_move_their_check_onto_another_host(self):
        old = _mod(i4={'uid': 'i4', 'host_uid': 'mine', 'label': 'a'})
        new = _mod(i4={'uid': 'i4', 'host_uid': 'victim', 'label': 'a'})
        assert authz.authorize_module_write('ping', old, new, MINE) is False

    def test_they_may_not_take_another_hosts_check_onto_their_own(self):
        """Found by audit, 2026-08-15. The binding was read from the NEW item only, so a
        rebind was authorised by where the check LANDS — and this was allowed while the
        very same edit made in place was refused.

        The damage is not on the attacker's host: the check leaves the other one, which
        stops being monitored, and nothing in the permission model said that could happen.
        """
        old = _mod(i5={'uid': 'i5', 'host_uid': 'victim', 'label': 'prod db'})
        new = _mod(i5={'uid': 'i5', 'host_uid': 'mine', 'label': 'mine now'})
        assert authz.authorize_module_write('ping', old, new, MINE) is False

    def test_they_may_not_remove_a_check_from_another_host(self):
        old = _mod(i6={'uid': 'i6', 'host_uid': 'victim', 'label': 'a'})
        new = _mod()
        assert authz.authorize_module_write('ping', old, new, MINE) is False

    def test_a_global_devices_edit_holder_may_rebind(self):
        """The global permission is not confined to a host, so moving a check between two
        of them is exactly what it authorises."""
        old = _mod(i7={'uid': 'i7', 'host_uid': 'a', 'label': 'x'})
        new = _mod(i7={'uid': 'i7', 'host_uid': 'b', 'label': 'x'})
        assert authz.authorize_module_write('ping', old, new, {'devices_edit'}) is True

    def test_an_unbound_check_still_needs_the_global_permission(self):
        """No host means no per-server permission can speak for it."""
        old = _mod(i8={'uid': 'i8', 'label': 'x'})
        new = _mod(i8={'uid': 'i8', 'label': 'y'})
        assert authz.authorize_module_write('ping', old, new, MINE) is False
        assert authz.authorize_module_write('ping', old, new, {'devices_edit'}) is True
