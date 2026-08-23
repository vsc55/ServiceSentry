#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The map, and the line it must not cross.

A picture of a network is read as a picture of cables. This one is not: it is built out of the
addresses each machine claims, the prefix beside each one, and the next hop the machine says it
uses for what it cannot deliver itself. Nothing here asks a device anything — a map that cost a
fresh conversation with forty machines is a map somebody turns off.

That makes the arithmetic the easy half and the HONESTY the hard one. Two devices with an
address on one network can reach each other, which is worth drawing; it is not the same claim
as "these two are plugged together", which is LLDP and which nothing in this fleet serves yet.
So every edge carries how it was arrived at, and the tests below are mostly about the cases
where the temptation is to say more than is known: an address with no prefix, a gateway nobody
has registered, a machine that has never answered.
"""

from lib.core.infra import topology


def _host(uid, name, address='', status='up', device_type='server'):
    return {'uid': uid, 'name': name, 'address': address, 'status': status,
            'device_type': device_type}


def _attrs(ip='', gateway='', row=''):
    out = []
    if ip:
        out.append({'key': 'ip', 'value': ip, 'row': row})
    if gateway:
        out.append({'key': 'gateway', 'value': gateway, 'row': row})
    return out


class TestWhereAnAddressLives:

    def test_a_network_is_arithmetic_and_not_a_convention(self):
        """192.168.250.21/24 is on 192.168.250.0/24 on every machine ever made. The prefix is
        what makes it knowable — and it is why the address is paired with its mask at the
        point it is read."""
        assert topology.network_of('192.168.250.21', 24) == '192.168.250.0/24'
        assert topology.network_of('172.20.13.7', 16) == '172.20.0.0/16'
        assert topology.network_of('10.1.2.3', 8) == '10.0.0.0/8'
        assert topology.network_of('192.168.1.130', 25) == '192.168.1.128/25'

    def test_an_address_with_no_prefix_is_not_placed(self):
        """Assuming /24 because most of them are is how a map puts two machines on one
        network that cannot reach each other. Saying nothing is the honest answer."""
        assert topology.network_of('192.168.1.10', 0) == ''
        assert topology.network_of('192.168.1.10', 33) == ''

    def test_something_that_is_not_an_address_is_not_one(self):
        for bad in ('', 'nas-01', '192.168.1', '1.2.3.4.5', '999.1.1.1',
                    'fe80::1', 'a.b.c.d'):
            assert topology.network_of(bad, 24) == '', bad


class TestWhatEndsUpOnThePicture:

    def test_a_machine_is_placed_by_what_it_answered(self):
        out = topology.build([_host('a', 'erebor')],
                             {'a': _attrs('192.168.250.21/24, 172.20.0.1/16')})
        node = out['nodes'][0]
        assert node['networks'] == ['172.20.0.0/16', '192.168.250.0/24']
        assert [n['net'] for n in out['networks']] == ['172.20.0.0/16', '192.168.250.0/24']

    def test_the_loopback_does_not_put_the_whole_fleet_on_one_network(self):
        """Every machine has 127.0.0.1. Believing it would draw the entire estate as one
        segment, which is both wrong and the most confident-looking thing on the screen."""
        out = topology.build([_host('a', 'a'), _host('b', 'b')],
                             {'a': _attrs('127.0.0.1/8, 10.0.0.1/24'),
                              'b': _attrs('127.0.0.1/8, 10.0.0.2/24')})
        assert [n['net'] for n in out['networks']] == ['10.0.0.0/24']

    def test_a_machine_that_never_answered_is_still_on_the_map(self):
        """Placed by the address somebody typed into the registry — which is a fact about the
        RECORD and not about the device, so it names the node and never claims a network."""
        out = topology.build([_host('a', 'nuevo', address='192.168.1.5')], {'a': []})
        assert out['nodes'][0]['addresses'] == ['192.168.1.5']
        assert out['nodes'][0]['networks'] == []
        assert out['unplaced'] == ['a'], 'and it is counted as unplaced rather than hidden'

    def test_a_fact_belonging_to_a_disk_is_not_a_fact_about_the_machine(self):
        """Row-bound facts are something else's. A machine is not on a network because one of
        its disks answered something with a slash in it."""
        out = topology.build([_host('a', 'a')],
                             {'a': _attrs('10.0.0.1/24', row='Drive 1')})
        assert out['nodes'][0]['networks'] == []


class TestTheEdgesSayWhatKindTheyAre:

    def test_a_gateway_that_is_a_machine_we_know_joins_two_nodes(self):
        out = topology.build(
            [_host('a', 'erebor'), _host('g', 'router')],
            {'a': _attrs('192.168.250.21/24', '192.168.250.254'),
             'g': _attrs('192.168.250.254/24')})
        assert out['edges'] == [{'from': 'a', 'to': 'g',
                                 'address': '192.168.250.254', 'kind': 'gateway'}]

    def test_a_gateway_nobody_registered_is_drawn_as_the_outside(self):
        """Inventing a node for it would put a machine on the fleet that nobody is watching,
        and the map is the wrong place to acquire inventory."""
        out = topology.build([_host('b', 'pve01')],
                             {'b': _attrs('192.168.200.11/24', '192.168.200.254')})
        assert out['edges'][0]['kind'] == 'exit' and out['edges'][0]['to'] == ''
        assert out['edges'][0]['address'] == '192.168.200.254'

    def test_a_machine_with_no_default_route_contributes_no_edge(self):
        """Rather than an edge to nowhere. A device that did not say is not a device that
        said "none"."""
        out = topology.build([_host('a', 'a')], {'a': _attrs('10.0.0.1/24')})
        assert out['edges'] == []

    def test_a_next_hop_of_nothing_is_not_a_gateway(self):
        """`0.0.0.0` in a next-hop column means "directly attached", not a router at the
        unspecified address."""
        out = topology.build([_host('a', 'a')], {'a': _attrs('10.0.0.1/24', '0.0.0.0')})
        assert out['edges'] == []

    def test_the_first_of_several_default_routes_is_the_one_drawn(self):
        """A machine with two is a machine with two, and the map draws one rather than
        picking a winner it has no basis to pick."""
        out = topology.build([_host('a', 'a')],
                             {'a': _attrs('10.0.0.1/24', '10.0.0.254, 10.0.0.253')})
        assert [e['address'] for e in out['edges']] == ['10.0.0.254']


class TestItIsReadableWithoutBeingRead:

    def test_the_networks_come_out_in_address_order(self):
        """The order a routing table reads in. Alphabetical would put 10.0.0.0/8 after
        1.1.1.0/24 and 192.168.9.0/24 after 192.168.10.0/24."""
        out = topology.build(
            [_host(str(i), str(i)) for i in range(3)],
            {'0': _attrs('192.168.10.1/24'), '1': _attrs('192.168.9.1/24'),
             '2': _attrs('10.0.0.1/8')})
        assert [n['net'] for n in out['networks']] == [
            '10.0.0.0/8', '192.168.9.0/24', '192.168.10.0/24']

    def test_a_network_lists_everybody_on_it(self):
        out = topology.build([_host('a', 'a'), _host('b', 'b')],
                             {'a': _attrs('10.0.0.1/24'), 'b': _attrs('10.0.0.2/24')})
        assert out['networks'][0]['members'] == ['a', 'b']

    def test_nothing_at_all_is_an_answer_and_not_a_crash(self):
        assert topology.build([], {}) == {'networks': [], 'nodes': [], 'edges': [],
                                          'unplaced': []}
