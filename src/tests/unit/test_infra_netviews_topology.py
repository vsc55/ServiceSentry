#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the network maps are told beyond the cables: which ones are down, and where a machine
says it is.

A cable that stops carrying traffic drops out of both neighbour tables, so the map simply has
one line fewer — and a missing line reads as nothing at all. Reported from the demo: CORE-2's
uplink down, a server whose NIC lost its link, and the map looking exactly like a healthy one.
What survives is the PORT: administratively up, operationally down, and still carrying the
description somebody gave it, which on most networks names whatever is at the other end. Both
are the device's own statements, so `topology.build` draws a `down` edge from them — and only
from them: a description that names no machine, or an admin-down port, says nothing.
"""

from lib.core.infra import service as infra_svc
from lib.core.infra import topology


def _dev(uid, name):
    return {'uid': uid, 'name': name, 'address': '', 'status': 'ok', 'device_type': '',
            'watch': []}


def _port(row, alias='', neighbour='', port=''):
    out = []
    if alias:
        out.append({'row': row, 'key': 'alias', 'value': alias})
    if neighbour:
        out.append({'row': row, 'key': 'neighbour', 'value': neighbour})
        if port:
            out.append({'row': row, 'key': 'port', 'value': port})
    return out


def _map(attrs, down=None):
    devices = [_dev('a', 'CORE-1'), _dev('b', 'CORE-2'), _dev('c', 'srv-01')]
    return topology.build(devices, attrs, None, down)


class TestADeadCableIsStillOnTheMap:

    def test_a_down_port_that_names_a_machine_is_a_down_edge(self):
        out = _map({'b': _port('Te1/0/47', alias='CORE-1')}, {'b': {'Te1/0/47'}})
        down = [e for e in out['edges'] if e['kind'] == 'down']
        assert len(down) == 1
        e = down[0]
        assert (e['from'], e['to']) == ('a', 'b') and e['state'] == 'down'
        assert e['ports'] == {'b': ['Te1/0/47']} and e['by'] == ['b']
        assert e['confirmed'] is False

    def test_both_ends_saying_so_is_confirmed_and_one_line(self):
        out = _map({'a': _port('Te1/0/47', alias='CORE-2'),
                    'b': _port('Te1/0/47', alias='CORE-1')},
                   {'a': {'Te1/0/47'}, 'b': {'Te1/0/47'}})
        down = [e for e in out['edges'] if e['kind'] == 'down']
        assert len(down) == 1, down
        assert down[0]['confirmed'] is True and sorted(down[0]['by']) == ['a', 'b']
        assert down[0]['ports'] == {'a': ['Te1/0/47'], 'b': ['Te1/0/47']}

    def test_the_name_is_matched_the_way_neighbours_are(self):
        """Case and a search domain are not a difference — the same rule LLDP is joined by."""
        out = _map({'c': _port('eth0', alias='Core-1.example.lan')}, {'c': {'eth0'}})
        assert [(e['from'], e['to']) for e in out['edges'] if e['kind'] == 'down'] == [('a', 'c')]

    def test_a_description_naming_nobody_says_nothing(self):
        out = _map({'c': _port('eth0', alias='uplink to the old office')}, {'c': {'eth0'}})
        assert not [e for e in out['edges'] if e['kind'] == 'down']

    def test_a_port_that_is_up_is_not_down(self):
        out = _map({'c': _port('eth0', alias='CORE-1')}, {})
        assert not [e for e in out['edges'] if e['kind'] == 'down']

    def test_a_port_naming_its_own_machine_is_not_a_cable(self):
        out = _map({'c': _port('eth0', alias='srv-01')}, {'c': {'eth0'}})
        assert not [e for e in out['edges'] if e['kind'] == 'down']

    def test_a_pair_that_still_has_a_live_cable_is_degraded_not_doubled(self):
        """One dead member of a trunk is a degraded link, not a second, missing one."""
        attrs = {'a': _port('Te1/0/1', neighbour='CORE-2', port='Te1/0/1')
                 + _port('Te1/0/2', alias='CORE-2'),
                 'b': _port('Te1/0/1', neighbour='CORE-1', port='Te1/0/1')}
        out = _map(attrs, {'a': {'Te1/0/2'}})
        edges = [e for e in out['edges'] if {e['from'], e['to']} == {'a', 'b'}]
        assert len(edges) == 1 and edges[0]['kind'] == 'lldp'
        assert edges[0]['state'] == 'degraded' and edges[0]['down'] == {'a': ['Te1/0/2']}

    def test_the_output_does_not_depend_on_the_order_things_arrive_in(self):
        attrs = {'a': _port('p1', alias='srv-01'), 'b': _port('p9', alias='srv-01')}
        one = _map(attrs, {'a': {'p1'}, 'b': {'p9'}})['edges']
        two = _map(dict(reversed(list(attrs.items()))), {'b': {'p9'}, 'a': {'p1'}})['edges']
        assert one == two


class TestWhereAMachineSaysItIs:

    def test_the_location_it_declares_is_on_its_node(self):
        out = topology.build([_dev('a', 'CORE-1')],
                             {'a': [{'row': '', 'key': 'location',
                                     'value': 'Madrid › CPD › R-04'}]})
        assert out['nodes'][0]['location'] == 'Madrid › CPD › R-04'

    def test_and_none_is_an_empty_string(self):
        assert topology.build([_dev('a', 'x')], {})['nodes'][0]['location'] == ''


class TestWhichPortsAreDown:

    def _r(self, row, oper, admin=1):
        data = {'if_oper': oper}
        if admin is not None:
            data['if_admin'] = admin
        return {'module': 'snmp', 'row': row, 'data': data}

    def test_up_and_meant_to_be_up_but_not_running(self):
        got = infra_svc.ports_down([self._r('eth0', 2), self._r('eth1', 1),
                                    self._r('eth2', 7), self._r('eth3', 5)])
        assert got == {'eth0', 'eth2'}

    def test_a_port_shut_on_purpose_is_a_decision_not_an_incident(self):
        assert infra_svc.ports_down([self._r('eth0', 2, admin=2)]) == set()

    def test_a_port_with_no_admin_state_is_taken_as_meant_up(self):
        assert infra_svc.ports_down([self._r('eth0', '2', admin=None)]) == {'eth0'}

    def test_what_is_not_an_interface_is_not_read(self):
        assert infra_svc.ports_down([{'row': 'disk1', 'data': {'temp': 40}},
                                     {'row': '', 'data': {'if_oper': 2}},
                                     {'row': 'x', 'data': 'nope'}, 'junk', None]) == set()
