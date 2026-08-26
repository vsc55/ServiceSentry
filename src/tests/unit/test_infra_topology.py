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


def _host(uid, name, address='', status='up', device_type='server', watch=None):
    return {'uid': uid, 'name': name, 'address': address, 'status': status,
            'device_type': device_type, 'watch': list(watch or ())}


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
        assert out['edges'] == [{'from': 'a', 'to': 'g', 'address': '192.168.250.254',
                                 # …and no port, because nobody declared one: the next hop
                                 # says where it goes, only a mark says which cable.
                                 'port': '', 'said': False, 'kind': 'gateway'}]

    def test_a_port_somebody_DECLARED_is_the_way_out(self):
        """No MIB answers which of thirty ports carries the office's line. It is knowledge
        about the installation, written down where the rest of it is — and read here rather
        than deduced, because the deduction is a different claim: a next hop is what the
        routing table happens to say today."""
        out = topology.build(
            [_host('r', 'router', watch=[{'module': 'snmp', 'row': 'ether1', 'role': 'wan'}])],
            {'r': _attrs('10.0.0.1/24', '10.0.0.254')})
        assert out['nodes'][0]['wan'] == 'ether1'
        assert out['edges'][0]['port'] == 'ether1'
        assert out['edges'][0]['said'] is True

    def test_and_it_is_drawn_even_where_the_device_states_no_next_hop(self):
        """A switch states none — most of them do — so a machine carrying the line would have
        contributed nothing to the picture while carrying it."""
        out = topology.build(
            [_host('s', 'sw', watch=[{'module': 'snmp', 'row': 'sfp1', 'role': 'wan'}])],
            {'s': _attrs('10.0.0.2/24')})
        assert [e['kind'] for e in out['edges']] == ['exit']
        assert out['edges'][0]['port'] == 'sfp1'

    def test_an_ordinary_mark_declares_nothing(self):
        """`watch` says "tell me about this row". Only the role says what the row IS."""
        out = topology.build(
            [_host('r', 'router', watch=[{'module': 'snmp', 'row': 'ether1'}])],
            {'r': _attrs('10.0.0.1/24', '10.0.0.254')})
        assert out['nodes'][0]['wan'] == ''
        assert out['edges'][0]['said'] is False

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


def _neigh(*pairs):
    """A device's LLDP rows: one per neighbour and port, as the profile files them.

    Two or three: `(neighbour, its port)` is what a report names by itself, and the third is
    the reporter's OWN port — which the MIB keeps in the row's index and the profile digs out
    of there.
    """
    out = []
    for row_spec in pairs:
        who, port, mine = (list(row_spec) + [''])[:3]
        row = f'{who} / {port}'
        out.append({'key': 'neighbour', 'value': who, 'row': row})
        out.append({'key': 'port_desc', 'value': port, 'row': row})
        if mine:
            out.append({'key': 'local_port', 'value': mine, 'row': row})
    return out


def _agg(**ports):
    """What the LAG MIB answers, as the profile files it: one row per PORT of this device,
    carrying the aggregate it is a member of."""
    return [{'key': 'aggregate', 'value': agg, 'row': port} for port, agg in ports.items()]


class TestTheEdgesThatAreNotInferred:
    """LLDP is the only thing in SNMP that answers the topology question exactly.

    Everything else on this map says who can REACH whom. A device reporting an LLDP neighbour
    is saying it sees that machine down one of its own cables, which is a different and much
    stronger claim — so these edges are found first, kept apart by `kind`, and the drawing is
    expected to show the difference.
    """

    def test_a_neighbour_that_is_a_machine_we_know_becomes_a_link(self):
        """`from` and `to` are the two ENDS, in a stable order, and not a direction: being
        plugged together is symmetric and the drawing has no arrowhead on it."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3')),
             's': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp']
        assert len(wired) == 1 and wired[0]['from'] == 'a' and wired[0]['to'] == 's'
        assert wired[0]['ports'] == {'s': ['Gi1/0/3']}, (
            'the port a report names belongs to the NEIGHBOUR, not to the reporter')

    def test_one_cable_is_one_line_however_many_ends_reported_it(self):
        """A cable with an agent at both ends is reported twice, once from each side. Two
        lines between two boxes would say there are two cables."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3')),
             's': _attrs('10.0.0.2/24') + _neigh(('erebor', 'eth0'))})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp']
        assert len(wired) == 1
        assert wired[0]['ports'] == {'s': ['Gi1/0/3'], 'a': ['eth0']}, (
            'the two reports are what fill in both ends of the cable')
        assert wired[0]['bundle'] == 1
        assert wired[0]['confirmed'] is True

    def test_one_end_reporting_is_still_a_link_and_says_so(self):
        """The far end may run no LLDP agent. That is not a reason to leave the cable out —
        it is a reason to draw it as the weaker statement it is."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24'),
             's': _attrs('10.0.0.2/24') + _neigh(('erebor', 'eth0'))})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp']
        assert len(wired) == 1 and wired[0]['confirmed'] is False
        assert wired[0]['by'] == ['s']

    def test_a_neighbour_nobody_registered_is_not_acquired_as_inventory(self):
        """It is real, and the map is the wrong place to add machines to the fleet."""
        out = topology.build([_host('s', 'sw01')],
                             {'s': _attrs('10.0.0.2/24') + _neigh(('un-portatil', 'Gi1/0/24'))})
        assert [e for e in out['edges'] if e['kind'] == 'lldp'] == []

    def test_the_domain_is_not_a_difference(self):
        """LLDP reports a hostname and the registry holds whatever somebody typed. Refusing to
        join "erebor" to "erebor.cerebelum.lan" would draw every link missing on precisely the
        fleets that have a search domain."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + [{'key': 'name', 'value': 'erebor.cerebelum.lan',
                                            'row': ''}],
             's': _attrs('10.0.0.2/24') + _neigh(('EREBOR.cerebelum.lan', 'Gi1/0/3'))})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp']
        assert len(wired) == 1 and {wired[0]['from'], wired[0]['to']} == {'a', 's'}

    def test_a_machine_seeing_itself_is_not_a_link(self):
        """A cable back into the same box, or a name index that matched the reporter. Either
        way a line from a node to itself is a drawing artefact, not a fact."""
        out = topology.build([_host('a', 'erebor')],
                             {'a': _attrs('10.0.0.1/24') + _neigh(('erebor', 'eth1'))})
        assert [e for e in out['edges'] if e['kind'] == 'lldp'] == []

    def test_every_port_of_a_trunk_is_kept_and_counted(self):
        """The reported one, from a real rack: four cables between a router and a switch, and
        the map drew ONE line naming ONE port. Three of the four reports went on the floor.

        Both devices' own neighbour tables list four rows — the router saw the switch on
        ether11-14, the switch saw the router on GE25-28 — so every one of those ports is a
        thing that was said, and `bundle` is how many cables either side could see.
        """
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/4'), ('sw01', 'Gi1/0/3'),
                                                 ('sw01', 'Gi1/0/12'), ('sw01', 'Gi1/0/2')),
             's': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp']
        assert len(wired) == 1, 'the pairing of which port faces which is not knowable here'
        assert wired[0]['bundle'] == 4
        # …and in an order somebody can check against the front of the switch: 12 comes after
        # 3, which a plain sort does not do.
        assert wired[0]['ports']['s'] == ['Gi1/0/2', 'Gi1/0/3', 'Gi1/0/4', 'Gi1/0/12']

    def test_it_does_not_claim_the_four_are_an_aggregate(self):
        """Whether cables are a LAG is a configuration fact, and counting them is not reading
        it. Four separate links and a four-port aggregate answer the neighbour table
        identically — so a device that did not say leaves the map with a count and no claim.
        """
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3'), ('sw01', 'Gi1/0/4')),
             's': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['bundle'] == 2
        assert 'lag' not in wired and 'aggregate' not in wired

    def test_but_it_carries_it_where_the_DEVICE_said(self):
        """The answer exists in exactly one place — IEEE8023-LAG-MIB, where a port states the
        aggregator it is attached to — and the `lag` profile reads it. Reported off the
        screen: a trunk showed `ether11-14` on the router, which names its bond in every port
        path, beside four bare `gigabitethernet` chips on the switch, which names nothing.
        """
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3'), ('sw01', 'Gi1/0/4')),
             's': _attrs('10.0.0.2/24') + _agg(**{'Gi1/0/3': 'Po1', 'Gi1/0/4': 'Po1'})})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['lag'] == {'s': {'Gi1/0/3': 'Po1', 'Gi1/0/4': 'Po1'}}

    def test_and_only_for_the_ports_of_THIS_cable(self):
        """A switch has an aggregate for its uplink and one for its stack, and the panel is
        looking at one pair of machines. Every port the device named would put the other
        cable's LAG on this cable's banner."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3')),
             's': _attrs('10.0.0.2/24') + _agg(**{'Gi1/0/3': 'Po1', 'Gi1/0/9': 'Po2'})})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['lag'] == {'s': {'Gi1/0/3': 'Po1'}}

    def test_a_port_that_said_nothing_is_absent_and_not_empty(self):
        """"Did not say" and "said no" are different answers, and the screen reads the first
        as a reason to stay quiet. A port present with an empty aggregate would make the
        banner draw a nameless LAG chip."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3'), ('sw01', 'Gi1/0/4')),
             's': _attrs('10.0.0.2/24') + _agg(**{'Gi1/0/3': 'Po1'})})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['lag'] == {'s': {'Gi1/0/3': 'Po1'}}, 'Gi1/0/4 never answered'

    def test_the_larger_side_is_the_count(self):
        """A side that reported fewer is a side that SAW fewer, not a rack with fewer wires."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3'), ('sw01', 'Gi1/0/4'),
                                                 ('sw01', 'Gi1/0/5')),
             's': _attrs('10.0.0.2/24') + _neigh(('erebor', 'eth0'))})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['bundle'] == 3

    def test_the_shipped_profile_asks_the_right_table(self):
        from lib.core.snmp import profiles as _p                  # noqa: PLC0415
        cat = _p.catalog()
        assert 'lldp' in cat, 'nothing asks a device who it can see'
        keys = {m['key']: m for m in cat['lldp']['metrics']}
        assert keys['lldp_sysname']['walk'] == '1.0.8802.1.1.2.1.4.1.1.9'
        assert keys['lldp_sysname']['role'] == 'neighbour'
        assert keys['lldp_portid']['role'] == 'port'
        # Named by the neighbour AND the port: a device with two cables to one switch is two
        # rows, and either column alone would merge them.
        assert isinstance(keys['lldp_sysname']['index_label'], list)
        assert 'lldp' in _p.expand(cat, ['grp_network']), 'a switch is not asked'
        assert 'lldp' in _p.expand(cat, ['grp_proxmox']), 'a hypervisor is not asked'


def _macs(*macs):
    """A machine's interface MACs, as the interface profile files them: one per row."""
    return [{'key': 'mac', 'value': m, 'row': f'eth{i}'} for i, m in enumerate(macs)]


class TestAMachineThatSpeaksNoLldpCanStillBePlaced:
    """The case the whole thing exists for: a NAS.

    An appliance whose vendor never shipped an LLDP agent cannot say who it is plugged into,
    and there is no installing one — DSM has no apt, and even a container would not help,
    because the panel reads LLDP out of the device's OWN snmpd. What CAN answer is the switch:
    it has learned that MAC on one of its ports, and the fleet already records every machine's
    interface MACs. That join is the only thing that will ever put such a device on a port.
    """

    def _ev(self, fdb, ports=None, names=None):
        return {'fdb': {'sw': fdb}, 'bridgeport': {'sw': ports or {}},
                'ifname': {'sw': names or {}}}

    def test_a_mac_alone_on_a_port_is_a_machine_on_that_port(self):
        out = topology.build(
            [_host('nas', 'erebor'), _host('sw', 'sw01')],
            {'nas': _attrs('10.0.0.5/24') + _macs('bc:24:11:0e:90:5f'),
             'sw': _attrs('10.0.0.2/24')},
            self._ev({'bc:24:11:0e:90:5f': '8'}, {'8': '8'}, {'8': 'GigabitEthernet1/0/8'}))
        wired = [e for e in out['edges'] if e['kind'] == 'port']
        assert len(wired) == 1 and {wired[0]['from'], wired[0]['to']} == {'nas', 'sw'}
        assert wired[0]['ports'] == {'sw': 'GigabitEthernet1/0/8'}, (
            'the chain MAC -> bridge port -> interface -> name did not complete')

    def test_the_same_address_written_four_ways_is_one_address(self):
        """SNMP answers MACs as raw octets, as 0x…, colon-separated, dot-separated, and with
        leading zeros dropped — the same address, from four agents, on one network. A
        comparison that is not normalised is a map with no links and nothing saying why."""
        for written in ('0xbc24110e905f', 'BC-24-11-0E-90-5F', 'bc24.110e.905f',
                        'bc:24:11:e:90:5f'):
            out = topology.build(
                [_host('nas', 'erebor'), _host('sw', 'sw01')],
                {'nas': _attrs('10.0.0.5/24') + _macs('bc:24:11:0e:90:5f'),
                 'sw': _attrs('10.0.0.2/24')},
                self._ev({written: '8'}))
            assert [e for e in out['edges'] if e['kind'] == 'port'], written

    def test_a_port_with_two_known_machines_is_an_uplink(self):
        """Reachable through a port is not the same as plugged into it: everything behind
        another switch is reachable through the port that switch is on. Two machines the panel
        knows cannot both be on one access port, so the port is dropped rather than drawn as a
        fan of cables that do not exist."""
        out = topology.build(
            [_host('a', 'a'), _host('b', 'b'), _host('sw', 'sw01')],
            {'a': _attrs('10.0.0.5/24') + _macs('aa:aa:aa:aa:aa:aa'),
             'b': _attrs('10.0.0.6/24') + _macs('bb:bb:bb:bb:bb:bb'),
             'sw': _attrs('10.0.0.2/24')},
            self._ev({'aa:aa:aa:aa:aa:aa': '24', 'bb:bb:bb:bb:bb:bb': '24'}))
        assert [e for e in out['edges'] if e['kind'] == 'port'] == []

    def test_a_hypervisor_is_not_mistaken_for_an_uplink(self):
        """Its guests each have a MAC on the same port, and none of them is a machine the
        panel knows. A rule counting MACs would throw away exactly the machine somebody is
        looking for; counting KNOWN machines does not."""
        out = topology.build(
            [_host('pve', 'pve01'), _host('sw', 'sw01')],
            {'pve': _attrs('10.0.0.7/24') + _macs('06:8c:62:81:85:94'),
             'sw': _attrs('10.0.0.2/24')},
            self._ev({'06:8c:62:81:85:94': '12', 'de:ad:be:ef:00:01': '12',
                      'de:ad:be:ef:00:02': '12', 'de:ad:be:ef:00:03': '12'}))
        assert [e['to'] for e in out['edges'] if e['kind'] == 'port'] == ['sw']

    def test_a_mac_nobody_owns_places_nothing(self):
        """A switch learns hundreds. The map draws the ones it can name and stays quiet about
        the rest — acquiring them as nodes would be the map doing inventory."""
        out = topology.build([_host('sw', 'sw01')], {'sw': _attrs('10.0.0.2/24')},
                             self._ev({'de:ad:be:ef:00:01': '3'}))
        assert [e for e in out['edges'] if e['kind'] == 'port'] == []

    def test_lldp_wins_over_a_port_sighting_for_the_same_pair(self):
        """Both are true and they are one link. The neighbour identifying itself is the
        stronger of the two, and two lines between two boxes would say there are two cables."""
        out = topology.build(
            [_host('a', 'erebor'), _host('sw', 'sw01')],
            {'a': _attrs('10.0.0.5/24') + _macs('aa:aa:aa:aa:aa:aa') + _neigh(('sw01', 'Gi1/0/8')),
             'sw': _attrs('10.0.0.2/24')},
            self._ev({'aa:aa:aa:aa:aa:aa': '8'}))
        kinds = [e['kind'] for e in out['edges'] if e['kind'] in ('lldp', 'port')]
        assert kinds == ['lldp']

    def test_the_switch_has_to_be_a_machine_we_know(self):
        """Evidence filed under a uid nobody has registered is evidence about nothing — and
        the far end of those edges would be a box the map invented."""
        out = topology.build([_host('nas', 'erebor')],
                             {'nas': _attrs('10.0.0.5/24') + _macs('aa:aa:aa:aa:aa:aa')},
                             self._ev({'aa:aa:aa:aa:aa:aa': '8'}))
        assert [e for e in out['edges'] if e['kind'] == 'port'] == []

    def test_no_evidence_at_all_is_a_map_without_ports(self):
        out = topology.build([_host('a', 'a')], {'a': _attrs('10.0.0.5/24')}, None)
        assert [e for e in out['edges'] if e['kind'] == 'port'] == []


class TestTwoMachinesCannotHoldOneAddress:
    """Reported from the map: two NAS both showed as living in 172.17.0.0/16, drawn as
    neighbours, and they cannot reach each other. It is `docker0` — every machine running
    containers has one, every one of them is 172.17.0.1, and they are as many separate
    networks as there are machines.

    Detected from something universally true rather than from knowing what Docker is: two
    machines cannot hold the same address on one network. If they both claim 172.17.0.1,
    either it is not the same network or one of them is unreachable — and drawing them as
    neighbours is a lie in both cases.
    """

    @staticmethod
    def _attrs(ip):
        return [{'row': '', 'key': 'ip', 'value': ip}]

    def _map(self, *pairs):
        hosts = [{'uid': u, 'name': u} for u, _ip in pairs]
        return topology.build(hosts, {u: self._attrs(ip) for u, ip in pairs})

    def test_the_same_address_twice_is_not_one_network(self):
        out = self._map(('erebor', '172.17.0.1/16'), ('isen', '172.17.0.1/16'))
        net = [n for n in out['networks'] if n['net'] == '172.17.0.0/16'][0]
        assert net['private'] is True
        assert sorted(net['members']) == ['erebor', 'isen'], (
            'the machines were dropped instead of the claim about them')

    def test_a_real_network_is_still_a_real_network(self):
        out = self._map(('a', '192.168.1.10/24'), ('b', '192.168.1.11/24'))
        net = [n for n in out['networks'] if n['net'] == '192.168.1.0/24'][0]
        assert net['private'] is False
        assert sorted(net['members']) == ['a', 'b']

    def test_one_machine_alone_is_not_a_contradiction(self):
        """A private range with a single member joins nothing, so it says nothing wrong."""
        out = self._map(('a', '172.18.0.1/16'))
        net = [n for n in out['networks'] if n['net'] == '172.18.0.0/16'][0]
        assert net['private'] is False

    def test_the_flag_is_per_network_and_not_per_fleet(self):
        """A fleet with one contradictory range must not have its real networks marked too."""
        out = self._map(('erebor', '172.17.0.1/16'), ('isen', '172.17.0.1/16'),
                        ('pve', '192.168.180.10/24'))
        flags = {n['net']: n['private'] for n in out['networks']}
        assert flags['172.17.0.0/16'] is True
        assert flags['192.168.180.0/24'] is False

    def test_the_working_key_does_not_reach_the_payload(self):
        """`claims` is how the answer is worked out and is nobody else's business — a screen
        that found it there would start using it."""
        out = self._map(('a', '10.0.0.1/24'))
        assert all('claims' not in n for n in out['networks'])

class TestTheEndTheReportDoesNotName:
    """One report, and BOTH ends of the cable.

    Reported from the rack, with a screenshot of the router's own neighbour list open beside
    the panel: a MikroTik that plainly knows its Proxmox host is on `ether8` drew a cable
    whose own end read "port not identified". Not a gap in what was answered — a gap in what
    was asked. LLDP says "I see that one, and this is the port IT answered on", never "and I
    answered on mine", so the reporter's own port is in no column of `lldpRemTable`: it is the
    second component of the row's INDEX, and nothing had gone looking for it there.
    """

    def test_one_reporter_names_both_ends(self):
        out = topology.build(
            [_host('r', 'rt01'), _host('p', 'srv01')],
            {'r': _attrs('10.0.0.1/24') + _neigh(('srv01', 'enx00005e005301', 'ether8')),
             'p': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['ports']['p'] == ['enx00005e005301'], 'the far end, as it always was'
        assert wired['ports']['r'] == ['ether8'], 'and the end that reported it'

    def test_a_report_that_does_not_say_leaves_it_unsaid(self):
        """An agent that serves no local-port table, or a row where it is blank. The end goes
        back to being unnamed, which is what the screen already knows how to draw — an empty
        string there would be a port called nothing."""
        out = topology.build(
            [_host('r', 'rt01'), _host('p', 'srv01')],
            {'r': _attrs('10.0.0.1/24') + _neigh(('srv01', 'enx00005e005301')),
             'p': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert 'r' not in wired['ports']

    def test_a_devices_own_name_for_its_own_port_wins(self):
        """They are usually the same string and occasionally are not — one end reports a
        description, the other an id. Merging the two would list one port twice and turn one
        cable into two."""
        out = topology.build(
            [_host('r', 'rt01'), _host('p', 'srv01')],
            {'r': _attrs('10.0.0.1/24') + _neigh(('srv01', 'eno1', 'ether8')),
             'p': _attrs('10.0.0.2/24') + _neigh(('rt01', 'ether8 (uplink)', 'eno1'))})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['ports']['r'] == ['ether8'], wired['ports']
        assert wired['ports']['p'] == ['eno1'], wired['ports']
        assert wired['bundle'] == 1, 'one cable, named twice, is still one cable'

    def test_both_ends_speaking_is_still_one_line(self):
        """The reason the link is keyed by the PAIR and not by a port. Now that each report
        carries both ends, keying by either would be twice as tempting and twice as wrong."""
        out = topology.build(
            [_host('r', 'rt01'), _host('p', 'srv01')],
            {'r': _attrs('10.0.0.1/24') + _neigh(('srv01', 'eno1', 'ether8')),
             'p': _attrs('10.0.0.2/24') + _neigh(('rt01', 'ether8', 'eno1'))})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp']
        assert len(wired) == 1 and wired[0]['confirmed'] is True

    def test_a_trunk_keeps_every_port_of_its_own(self):
        """Four rows, four local ports — and the reporter's side is now as complete as the
        far side was."""
        out = topology.build(
            [_host('r', 'rt01'), _host('s', 'sw01')],
            {'r': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3', 'ether11'),
                                                 ('sw01', 'Gi1/0/4', 'ether12'),
                                                 ('sw01', 'Gi1/0/12', 'ether13')),
             's': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['ports']['r'] == ['ether11', 'ether12', 'ether13']
        assert wired['ports']['s'] == ['Gi1/0/3', 'Gi1/0/4', 'Gi1/0/12']
        assert wired['bundle'] == 3

    def test_a_local_port_that_arrived_as_a_MAC_is_still_resolved(self):
        """The same rule the far end has had all along, and it has to be the same rule: an
        agent with no port description answers its portId, which on most of them is that
        port's hardware address — on both sides of the row."""
        rows = _attrs('10.0.0.1/24') + [
            {'key': 'mac', 'value': '00:00:5E:00:53:01', 'row': 'ether8'}]
        out = topology.build(
            [_host('r', 'rt01'), _host('p', 'srv01')],
            {'r': rows + _neigh(('srv01', 'eno1', '00:00:5E:00:53:01')),
             'p': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['ports']['r'] == ['ether8']

    def test_and_only_when_the_MAC_is_that_machines_own(self):
        """`by_mac` is fleet-wide. A local port resolved through somebody else's interface
        would print a neighbour's port name on this device."""
        rows = _attrs('10.0.0.2/24') + [
            {'key': 'mac', 'value': '00:00:5E:00:53:01', 'row': 'eno1'}]
        out = topology.build(
            [_host('r', 'rt01'), _host('p', 'srv01')],
            {'r': _attrs('10.0.0.1/24') + _neigh(('srv01', 'eno1', '00:00:5E:00:53:01')),
             'p': rows})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp'][0]
        assert wired['ports']['r'] == ['00:00:5E:00:53:01'], 'left as it arrived'


class TestWhereSomebodyPutTheBoxes:
    """An arrangement of the link map, on the way to and from an account.

    Two copies exist and they answer different questions: the browser's, written as the hand
    moves a box, which is what makes dragging instant and needs no account at all; and this
    one, written by a button, which is the copy that follows somebody to another machine.

    Checked HERE and not at either end, because both ends are the same browser. A coordinate
    that is not a number puts a box at NaN, which draws nothing at all and reads as a device
    that has vanished — the same failure the browser guards against on the way out of its own
    store, and the reason the server does not simply trust what it wrote.
    """

    def _norm(self, raw):
        from lib.core.infra import service as svc              # noqa: PLC0415
        return svc.normalise_link_layout(raw)

    def test_a_pair_of_numbers_per_device(self):
        assert self._norm({'a': {'x': 10, 'y': -20.5}}) == {'a': {'x': 10.0, 'y': -20.5}}

    def test_negative_is_a_real_place(self):
        """The drawing's own origin moves to wherever its leftmost box is, so there is no
        top-left to fall off. Rejecting negatives here would put the boxes back inside a
        boundary the picture no longer has."""
        assert self._norm({'a': {'x': -900, 'y': -900}}) == {'a': {'x': -900.0, 'y': -900.0}}

    def test_what_is_not_a_coordinate_is_dropped(self):
        for bad in ({'x': 'nope', 'y': 1}, {'x': 1}, {'y': 1}, {}, None, 5, 'x', [1, 2]):
            assert self._norm({'a': bad}) == {}, bad

    def test_and_neither_is_infinity(self):
        """`float('nan')` and the infinities are floats and pass every type check. One of them
        in a viewBox is a map that cannot be zoomed back out of."""
        for bad in (float('nan'), float('inf'), float('-inf'), 10 ** 9):
            assert self._norm({'a': {'x': bad, 'y': 0}}) == {}, bad
            assert self._norm({'a': {'x': 0, 'y': bad}}) == {}, bad

    def test_a_uid_has_to_look_like_one(self):
        assert self._norm({'': {'x': 1, 'y': 1}}) == {}
        assert self._norm({'  ': {'x': 1, 'y': 1}}) == {}
        assert self._norm({'u' * 65: {'x': 1, 'y': 1}}) == {}
        assert self._norm({'u' * 64: {'x': 1, 'y': 1}}) != {}

    def test_it_is_an_arrangement_and_not_a_key_value_store(self):
        """Past a few hundred boxes it is not a picture anybody reads, and an account is not
        somewhere to put a megabyte through a UI preference."""
        from lib.core.infra import service as svc              # noqa: PLC0415
        many = {f'u{i}': {'x': i, 'y': i} for i in range(svc.LINK_LAYOUT_MAX + 50)}
        assert len(self._norm(many)) == svc.LINK_LAYOUT_MAX

    def test_nothing_at_all_is_not_an_arrangement(self):
        for bad in (None, [], 'x', 7):
            assert self._norm(bad) == {}, bad


class TestAnArrangementThatWasAlreadySaved:
    """A rename that loses somebody's arrangement is a rename that broke something.

    The field held one drawing's boxes when there was one drawing. The day a second map took
    an arrangement it became keyed by drawing — and the boxes went back to their generated
    places, with nothing on screen to press to get them back. Reported from the screen in
    exactly those words.

    So the old field is read once and written forward, and it is read HERE rather than off the
    record, so the day it finally goes there is one place that stops mentioning it.
    """

    def _of(self, user):
        from lib.core.infra import service as svc              # noqa: PLC0415
        return svc.map_layouts_of(user)

    def test_the_field_it_replaced_is_still_read(self):
        got = self._of({'infra_link_layout': {'a': {'x': 1, 'y': 2}}})
        assert got == {'infraLinkSvg': {'a': {'x': 1.0, 'y': 2.0}}}

    def test_but_never_over_the_top_of_the_one_that_replaced_it(self):
        """Whichever was written last is the new field, because writing it is what clears the
        old one. Reading the old one over it would undo the most recent save."""
        got = self._of({'infra_link_layout': {'a': {'x': 1, 'y': 2}},
                        'infra_map_layouts': {'infraLinkSvg': {'a': {'x': 9, 'y': 9}}}})
        assert got['infraLinkSvg'] == {'a': {'x': 9.0, 'y': 9.0}}

    def test_and_a_second_drawing_is_untouched_by_either(self):
        got = self._of({'infra_link_layout': {'a': {'x': 1, 'y': 2}},
                        'infra_map_layouts': {'infraNetSvg': {'b': {'x': 3, 'y': 4}}}})
        assert sorted(got) == ['infraLinkSvg', 'infraNetSvg']

    def test_an_account_with_nothing_has_nothing(self):
        for empty in ({}, None, {'infra_map_layouts': {}}, {'infra_link_layout': 'nonsense'}):
            assert self._of(empty) == {}, empty

    def test_a_drawing_has_to_be_named_like_one(self):
        from lib.core.infra import service as svc              # noqa: PLC0415
        for bad in ('', '  ', 'x' * 65, 'not a name', '../etc'):
            assert svc.normalise_map_layouts({bad: {'a': {'x': 1, 'y': 1}}}) == {}, bad

    def test_and_an_account_holds_a_few_of_them_and_not_a_thousand(self):
        from lib.core.infra import service as svc              # noqa: PLC0415
        many = {f'c{i}': {'a': {'x': 1, 'y': 1}} for i in range(svc.LINK_LAYOUT_CANVASES + 5)}
        assert len(svc.normalise_map_layouts(many)) == svc.LINK_LAYOUT_CANVASES


class TestWhichPortsMakeUpAnAggregate:
    """The MIB answers this one way round only.

    A PORT says which aggregator it is attached to; the aggregator says nothing at all. So the
    device page showed eight rows called Po1…Po8 and the only way to learn what was in one was
    to read twenty-eight port rows looking for it. Reported from the screen.

    Turned round on THIS side, for the reason every other join on this path is: a second
    implementation of "which ports are in that bond" is free to disagree with the first, and
    the day it did the map and the device page would say different things about one switch.
    """

    def _attr(self, row, key, value, src='lag'):
        return {'module': 'snmp', 'row': row, 'item': 'sw', 'source': src,
                'source_label': 'Aggregation', 'source_short': 'LAG',
                'key': key, 'value': value}

    def _members(self, attrs):
        from lib.core.infra import service as svc              # noqa: PLC0415
        svc._aggregate_members(attrs)
        return {a['row']: a['value'] for a in attrs if a['key'] == 'aggregate_members'}

    def test_the_aggregate_gets_the_list_of_its_ports(self):
        attrs = [self._attr('Po1', 'if_alias', ''),
                 self._attr('gi3', 'aggregate', 'Po1'),
                 self._attr('gi4', 'aggregate', 'Po1')]
        assert self._members(attrs) == {'Po1': 'gi3, gi4'}

    def test_in_an_order_somebody_can_check_against_the_switch(self):
        """12 after 3, which an alphabetical sort does not do."""
        attrs = [self._attr('Po1', 'x', ''),
                 *[self._attr(f'gi{n}', 'aggregate', 'Po1') for n in (12, 3, 4)]]
        assert self._members(attrs) == {'Po1': 'gi3, gi4, gi12'}

    def test_two_aggregates_are_two_lists(self):
        attrs = [self._attr('Po1', 'x', ''), self._attr('Po2', 'x', ''),
                 self._attr('gi3', 'aggregate', 'Po1'),
                 self._attr('gi9', 'aggregate', 'Po2')]
        assert self._members(attrs) == {'Po1': 'gi3', 'Po2': 'gi9'}

    def test_an_aggregate_the_device_did_not_report_as_a_row_gets_nothing(self):
        """A name that matches no row is an interface the panel is not reading, and inventing
        a row for it would put a heading on the screen with nothing under it."""
        attrs = [self._attr('gi3', 'aggregate', 'Po7')]
        assert self._members(attrs) == {}

    def test_and_a_device_with_no_aggregate_at_all_is_untouched(self):
        attrs = [self._attr('gi3', 'if_alias', 'uplink')]
        before = len(attrs)
        assert self._members(attrs) == {}
        assert len(attrs) == before, 'it added something to a switch that aggregates nothing'

    def test_the_list_is_filed_under_the_profile_that_knew_it(self):
        """Not on the interface card. It came from the LAG MIB and it belongs beside the rest
        of what that MIB said, or the card headings stop meaning anything."""
        from lib.core.infra import service as svc              # noqa: PLC0415
        attrs = [self._attr('Po1', 'x', '', src='if_generic'),
                 self._attr('gi3', 'aggregate', 'Po1')]
        svc._aggregate_members(attrs)
        made = [a for a in attrs if a['key'] == 'aggregate_members'][0]
        assert made['source'] == 'lag' and made['source_short'] == 'LAG'

    def test_a_port_named_twice_is_named_once(self):
        """Two profiles can file the same fact for one row, and "gi3, gi3" is not a list."""
        attrs = [self._attr('Po1', 'x', ''),
                 self._attr('gi3', 'aggregate', 'Po1'),
                 self._attr('gi3', 'aggregate', 'Po1')]
        assert self._members(attrs) == {'Po1': 'gi3'}

    def test_and_it_reaches_the_screen_with_a_word_on_it(self):
        """A key with no label renders as `aggregate_members`, which is the same failure the
        card title had one screen up."""
        import io as _io, os as _os                             # noqa: PLC0415
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        for lang in ('en_EN', 'es_ES'):
            with _io.open(_os.path.join(root, 'lib', 'i18n', 'lang', lang + '.py'),
                          encoding='utf-8') as fh:
                assert "'attr_aggregate_members'" in fh.read(), lang
