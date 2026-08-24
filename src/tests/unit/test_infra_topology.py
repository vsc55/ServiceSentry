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


def _neigh(*pairs):
    """A device's LLDP rows: one per neighbour and port, as the profile files them."""
    out = []
    for who, port in pairs:
        row = f'{who} / {port}'
        out.append({'key': 'neighbour', 'value': who, 'row': row})
        out.append({'key': 'port_desc', 'value': port, 'row': row})
    return out


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
        assert wired[0]['ports'] == {'s': 'Gi1/0/3'}, (
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
        assert wired[0]['ports'] == {'s': 'Gi1/0/3', 'a': 'eth0'}, (
            'the two reports are what fill in both ends of the cable')
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

    def test_two_cables_to_the_same_switch_are_two_reports_and_one_line(self):
        """Which is a compromise the drawing makes and the data does not have to: the ports
        are both there, and a second line between the same two boxes would be unreadable."""
        out = topology.build(
            [_host('a', 'erebor'), _host('s', 'sw01')],
            {'a': _attrs('10.0.0.1/24') + _neigh(('sw01', 'Gi1/0/3'), ('sw01', 'Gi1/0/4')),
             's': _attrs('10.0.0.2/24')})
        wired = [e for e in out['edges'] if e['kind'] == 'lldp']
        assert len(wired) == 1 and wired[0]['ports'] == {'s': 'Gi1/0/3'}

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
