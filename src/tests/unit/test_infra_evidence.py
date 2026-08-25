#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A sighting is not a check, and the difference decides where it is kept.

A switch's forwarding table and a machine's ARP cache are the two things that say what is
really on the other end of a wire. They are also the two that do not fit anywhere else this
panel keeps data, and the temptation is to file them as ordinary readings — a row per MAC,
like a row per disk. The cost of that is invisible until somebody has a switch with four
hundred entries on it: four hundred `check_state` rows and four hundred history series, most
of them a laptop that connected once, created and pruned every cycle, alerting nobody.

So they get a table of their own that holds only the CURRENT picture. These tests are about
the two properties that makes it worth having: that a device's sightings are replaced whole
rather than merged, and that nothing about them can take a cycle down.
"""

from lib.db import get_connector
from lib.core.infra.evidence import EvidenceStore, SCHEMA


def _store():
    return EvidenceStore(get_connector(None, default_sqlite_path=':memory:'))


class TestItKeepsTheCurrentPicture:

    def test_what_was_seen_comes_back(self):
        s = _store()
        s.replace('sw', 'fdb', {'bc:24:11:0e:90:5f': '8', 'aa:bb:cc:dd:ee:ff': '12'})
        assert s.by_device('fdb') == {
            'sw': {'bc:24:11:0e:90:5f': '8', 'aa:bb:cc:dd:ee:ff': '12'}}

    def test_a_second_look_replaces_the_first_entirely(self):
        """Not a merge. That an entry has GONE is information: a MAC that aged out of a switch
        is a machine that is no longer on that port, and merging would leave the map drawing a
        cable somebody unplugged last week."""
        s = _store()
        s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '8', 'bb:bb:bb:bb:bb:bb': '9'})
        s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '11'})
        assert s.by_device('fdb') == {'sw': {'aa:aa:aa:aa:aa:aa': '11'}}
        assert s.count() == 1, 'the rows that went were deleted, not left behind'

    def test_a_device_seeing_nothing_is_recorded_as_seeing_nothing(self):
        """A switch whose table is empty is a switch whose table is empty. Skipping the write
        would leave last cycle's picture standing as if it were current."""
        s = _store()
        s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'})
        s.replace('sw', 'fdb', {})
        assert s.by_device('fdb') == {} and s.count() == 0

    def test_the_kinds_do_not_tread_on_each_other(self):
        """One device answers several: its forwarding table, its bridge ports, its ARP cache.
        Replacing one must not touch the others."""
        s = _store()
        s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'})
        s.replace('sw', 'arp', {'10.0.0.5': 'aa:aa:aa:aa:aa:aa'})
        s.replace('sw', 'fdb', {'bb:bb:bb:bb:bb:bb': '9'})
        assert s.by_device('arp') == {'sw': {'10.0.0.5': 'aa:aa:aa:aa:aa:aa'}}
        assert s.by_device('fdb') == {'sw': {'bb:bb:bb:bb:bb:bb': '9'}}

    def test_two_devices_can_see_the_same_thing(self):
        """Two switches both know a MAC. Keyed by who saw it, or the second would overwrite
        the first and the map would lose half its ports."""
        s = _store()
        s.replace('sw1', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'})
        s.replace('sw2', 'fdb', {'aa:aa:aa:aa:aa:aa': '24'})
        assert s.by_device('fdb') == {'sw1': {'aa:aa:aa:aa:aa:aa': '8'},
                                      'sw2': {'aa:aa:aa:aa:aa:aa': '24'}}

    def test_everything_at_once_is_asked_for_by_kind(self):
        s = _store()
        s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'})
        s.replace('nas', 'arp', {'10.0.0.1': 'bb:bb:bb:bb:bb:bb'})
        assert set(s.by_device()) == {'sw', 'nas'}, 'no kind means all of them'

    def test_a_machine_leaving_takes_its_sightings_with_it(self):
        s = _store()
        s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'})
        s.replace('nas', 'arp', {'10.0.0.1': 'bb:bb:bb:bb:bb:bb'})
        s.forget('sw')
        assert set(s.by_device()) == {'nas'}


class TestItCannotTakeACycleDown:
    """Evidence is a nicety on top of the cycle. A map that misses a link is a worse map; a
    monitoring run that fails because of one is a worse panel."""

    def test_a_write_that_cannot_happen_says_so_and_does_not_raise(self):
        s = _store()
        s._db.execute(f'DROP TABLE {SCHEMA.name}')
        assert s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'}) is False

    def test_a_read_that_cannot_happen_is_an_empty_picture(self):
        s = _store()
        s.replace('sw', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'})
        s._db.execute(f'DROP TABLE {SCHEMA.name}')
        assert s.by_device('fdb') == {} and s.count() == 0

    def test_a_sighting_with_no_key_is_not_a_sighting(self):
        s = _store()
        s.replace('sw', 'fdb', {'': '8', '  ': '9', 'aa:aa:aa:aa:aa:aa': '10'})
        assert s.by_device('fdb') == {'sw': {'aa:aa:aa:aa:aa:aa': '10'}}

    def test_it_refuses_to_file_something_under_nobody(self):
        """A sighting with no device is one nobody can place — and it would be indexed under
        the empty string, where it would join every other orphan."""
        s = _store()
        assert s.replace('', 'fdb', {'aa:aa:aa:aa:aa:aa': '8'}) is False
        assert s.replace('sw', '', {'aa:aa:aa:aa:aa:aa': '8'}) is False
        assert s.count() == 0
