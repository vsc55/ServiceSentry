#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which of a module's results belong to a host — the join behind "Latest data" and /infra.

A module records results under keys of its own choosing; a host knows which ITEMS are bound to
it. Everything both screens show comes from matching one to the other, and the failure mode of
getting it wrong is the quiet kind: the rows are recorded correctly, charted correctly and named
correctly, and simply never appear. Nothing errors, and the screen reads as a machine that has
never reported anything.

That is exactly what happened to SNMP device-profile sampling. It files one result per table row
— ``<item>/eth0``, ``<item>/volume1`` — using the composite convention the rest of the product
already speaks (history's ``check_label`` resolves it the same way), and this join knew only two
shapes: the key that IS the item, and the older ``<item>_<suffix>`` derived form. Every sampled
row was dropped on the way to the screen built to show it.
"""

from lib.core.hosts.service import build_host_status


def _live(**rows):
    """One module's live status block, as the status store holds it."""
    return {'snmp': {k: {'status': True, 'message': '', 'ts': '2026-08-20T10:00:00',
                         'other_data': v} for k, v in rows.items()}}


BOUND = {'snmp': {'srv-uid': 'nas-01'}}


class TestWhichResultsBelongToTheHost:

    def test_a_key_that_is_the_item(self):
        """The plain case: an inline check whose result key is the item itself."""
        rows = build_host_status(BOUND, _live(**{'srv-uid': {'value': 1}}), {})
        assert [r['key'] for r in rows] == ['srv-uid']

    def test_a_composite_key_reaches_the_screen(self):
        """`<item>/<detail>` — one item producing several rows, which is what a device profile
        does when it samples a table. This is the regression: they were dropped in silence."""
        rows = build_host_status(BOUND, _live(**{'srv-uid/metrics': {'cpu': 41}}), {})
        assert [r['key'] for r in rows] == ['srv-uid/metrics']
        assert rows[0]['data'] == {'cpu': 41}

    def test_every_row_of_one_item_reaches_it(self):
        """A switch has forty ports and they are forty rows of one bound item. A join that
        kept only the first would show one port and look like it was working."""
        rows = build_host_status(
            BOUND, _live(**{'srv-uid/eth0': {'if_in': 1}, 'srv-uid/eth1': {'if_in': 2},
                            'srv-uid/metrics': {'uptime': 9}}), {})
        assert {r['key'] for r in rows} == {'srv-uid/eth0', 'srv-uid/eth1', 'srv-uid/metrics'}

    def test_a_detail_containing_a_slash_still_resolves(self):
        """Only the FIRST segment is the item — proxmox files `<uid>/node/pve04`, and splitting
        on the last slash would look for an item called `<uid>/node`."""
        rows = build_host_status(BOUND, _live(**{'srv-uid/node/pve04': {'x': 1}}), {})
        assert [r['key'] for r in rows] == ['srv-uid/node/pve04']

    def test_the_older_derived_shape_still_works(self):
        """ram_swap records `<uid>_ram` and `<uid>_swap`. Adding a shape must not cost one."""
        bound = {'ram_swap': {'uid': 'nas-01'}}
        raw = {'ram_swap': {'uid_ram': {'status': True, 'other_data': {'used': 1}},
                            'uid_swap': {'status': True, 'other_data': {'used': 2}}}}
        assert {r['key'] for r in build_host_status(bound, raw, {})} == {'uid_ram', 'uid_swap'}

    def test_a_result_of_another_host_is_not_borrowed(self):
        """The join is what scopes a module's results to THIS machine; a loose match would
        put another host's disks on this host's page."""
        rows = build_host_status(BOUND, _live(**{'other-uid/metrics': {'cpu': 1}}), {})
        assert rows == []

    def test_an_item_key_that_looks_like_a_prefix_is_not_one(self):
        """`srv-uid2/metrics` splits to `srv-uid2`, which is not `srv-uid`. Matching on
        startswith would have made it one."""
        rows = build_host_status(BOUND, _live(**{'srv-uid2/metrics': {'cpu': 1}}), {})
        assert rows == []


class TestWhenThereIsNoLiveValue:

    def test_history_fills_in_for_a_composite_key_too(self):
        """A host in maintenance has had its live records purged, and "nothing here" would read
        as a machine that never reported. The fallback has to understand the same shapes."""
        hist = {'snmp': [{'key': 'srv-uid/eth0', 'last_status': True,
                          'last_data': {'if_in': 5}, 'last_ts': '2026-08-20T09:00:00'}]}
        rows = build_host_status(BOUND, {}, hist)
        assert [(r['key'], r['source']) for r in rows] == [('srv-uid/eth0', 'history')]

    def test_a_live_row_is_not_duplicated_by_its_own_history(self):
        hist = {'snmp': [{'key': 'srv-uid/eth0', 'last_status': True, 'last_data': {}}]}
        rows = build_host_status(BOUND, _live(**{'srv-uid/eth0': {'if_in': 1}}), hist)
        assert len(rows) == 1 and rows[0]['source'] == 'live'


class TestWhatTheRowIsCalled:

    def test_the_result_names_itself_when_it_can(self):
        """A sampled row carries the name the device gave it — "eth0", not the item's label,
        which would make forty ports forty rows all called "nas-01"."""
        raw = {'snmp': {'srv-uid/eth0': {'status': True, 'other_data': {'name': 'eth0'}}}}
        assert build_host_status(BOUND, raw, {})[0]['name'] == 'eth0'

    def test_it_falls_back_to_the_bound_items_label(self):
        rows = build_host_status(BOUND, _live(**{'srv-uid/metrics': {}}), {})
        assert rows[0]['name'] == 'nas-01'
