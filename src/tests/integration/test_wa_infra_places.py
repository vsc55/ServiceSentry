#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where each machine IS, for the two network maps and the list's site filter.

Both maps group by site: three hundred machines on one canvas is a picture of nothing, and
"which building" is the first question anybody reading a network diagram asks. The inventory
already knows it — an item bound to a device (`dc_item.device_uid`) sits in a rack, in a room, in
a site — and `infra.service.places` reads it in bulk for the map payload and the fleet rows.

What it must not do is say where something is to somebody who may not know: the caller needs
`dcim_view` to read the inventory at all, and each item is kept only if its owning company is
visible to them — exactly the rule the device's own Location tab applies.
"""

from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash

from tests.conftest import _login

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


def _as(admin, username, perms):
    role = f'r-{username}'
    admin._custom_roles[role] = {
        'uid': role, 'name': role, 'description': '', 'permissions': list(perms),
        'enabled': True, 'created_at': '2026-10-17T00:00:00Z',
        'updated_at': '2026-10-17T00:00:00Z', 'updated_by': 'test'}
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash('pw-secret')}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': 'pw-secret'},
           follow_redirects=True)
    return c


@pytest.fixture()
def fleet(admin, client):
    """Two sites, a machine racked in each, one more in the north and one racked nowhere — and
    the inventory's link between the two sites, terminated by the two racked routers."""
    _login(client)
    c = client
    out = {}
    for key, name in (('n', 'Sede Norte'), ('s', 'Sede Sur')):
        site = _uid(c.post('/api/v1/dcim/sites', json={'name': name}))
        room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD ' + key}))
        rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R-' + key,
                                                       'u_height': 42}))
        out[key] = {'site': site, 'room': room, 'rack': rack}
    devs = {}
    for name, addr in (('rtr-n', '10.0.1.1'), ('srv-n', '10.0.1.2'), ('rtr-s', '10.0.2.1'),
                       ('loose', '10.0.3.1')):
        devs[name] = _uid(c.post('/api/v1/devices', json={'name': name, 'address': addr}))
    store = admin._dcim_store
    items = {}
    for name, key, u in (('rtr-n', 'n', 40), ('srv-n', 'n', 10), ('rtr-s', 's', 40)):
        items[name] = store.items.create({'rack_uid': out[key]['rack'], 'label': name,
                                          'u_start': u, 'u_height': 1, 'face': 'front',
                                          'device_uid': devs[name]}, actor='t')
    store.links.create({'a_site': out['n']['site'], 'b_site': out['s']['site'],
                        'a_item': items['rtr-n'], 'b_item': items['rtr-s'], 'kind': 'mpls',
                        'label': 'Norte-Sur', 'provider': 'Carrier'}, actor='t')
    out['dev'] = devs
    out['items'] = items
    return out


def _nodes(payload):
    return {n['name']: n for n in payload['nodes']}


class TestTheMapKnowsWhereEachMachineIs:

    def test_a_racked_machine_carries_its_site_room_and_rack(self, client, fleet):
        m = client.get('/api/v1/infra/map').get_json()
        n = _nodes(m)
        assert n['rtr-n']['site'] == fleet['n']['site']
        assert (n['rtr-n']['room'], n['rtr-n']['rack']) == ('CPD n', 'R-n')
        assert n['rtr-s']['site'] == fleet['s']['site']

    def test_one_racked_nowhere_has_no_site_and_is_still_on_the_map(self, client, fleet):
        n = _nodes(client.get('/api/v1/infra/map').get_json())
        assert n['loose']['site'] == '' and n['loose']['rack'] == ''

    def test_the_sites_are_named_beside_the_networks(self, client, fleet):
        m = client.get('/api/v1/infra/map').get_json()
        assert [s['name'] for s in m['sites']] == ['Sede Norte', 'Sede Sur']

    def test_the_link_between_two_sites_is_an_edge_between_their_machines(self, client, fleet):
        m = client.get('/api/v1/infra/map').get_json()
        edges = [e for e in m['edges'] if e['kind'] == 'site']
        assert len(edges) == 1
        e = edges[0]
        assert {e['from'], e['to']} == {fleet['dev']['rtr-n'], fleet['dev']['rtr-s']}
        assert (e['via'], e['label'], e['provider']) == ('mpls', 'Norte-Sur', 'Carrier')

    def test_and_its_state_is_the_worse_of_the_machines_that_terminate_it(self, admin, fleet):
        """A circuit has no state of its own; the router that terminates it does — the
        inventory's own rule (`dcim.service.links_roll`)."""
        from lib.core.infra import service as infra_svc             # noqa: PLC0415
        perms = {'dcim_view', 'orgs_all_view'}
        a, b = fleet['dev']['rtr-n'], fleet['dev']['rtr-s']
        for sa, sb, want in (('ok', 'error', 'error'), ('warning', 'ok', 'warning'),
                             ('ok', 'ok', 'ok'), ('', '', '')):
            got = infra_svc.annotate_places(admin, {'nodes': [{'uid': a, 'status': sa},
                                                             {'uid': b, 'status': sb}],
                                                   'edges': []}, perms)
            assert [e['state'] for e in got['edges']] == [want], (sa, sb)

    def test_the_fleet_rows_carry_it_too_for_the_list_filter(self, client, fleet):
        d = client.get('/api/v1/infra/devices').get_json()
        rows = {r['name']: r for r in d['devices']}
        assert rows['srv-n']['site'] == fleet['n']['site']
        assert rows['srv-n']['site_name'] == 'Sede Norte'
        assert rows['loose']['site'] == '' and rows['loose']['site_name'] == ''
        assert {s['name'] for s in d['sites']} == {'Sede Norte', 'Sede Sur'}


class TestWhatTheCallerMayNotSeeIsNotSaid:

    def test_without_the_inventory_there_is_no_place_at_all(self, admin, fleet):
        c = _as(admin, 'only-infra', ['infra_view', 'devices_view'])
        m = c.get('/api/v1/infra/map').get_json()
        assert m['sites'] == []
        assert all(n['site'] == '' for n in m['nodes'])
        assert not [e for e in m['edges'] if e['kind'] == 'site']
        d = c.get('/api/v1/infra/devices').get_json()
        assert all(r['site'] == '' for r in d['devices']) and d['sites'] == []

    def test_a_rack_of_another_company_does_not_place_its_machines(self, admin, client, fleet):
        """Somebody of company B sees the north's machines (they are in the registry) and not
        where they are racked: that rack is company A's. The south's rack is unclaimed, which
        anyone who may open the inventory sees."""
        a = _uid(client.post('/api/v1/orgs', json={'name': 'Empresa A', 'short': 'EA'}))
        b = _uid(client.post('/api/v1/orgs', json={'name': 'Empresa B', 'short': 'EB'}))
        r = client.post('/api/v1/orgs/owner', json={'scope': 'rack', 'uid': fleet['n']['rack'],
                                                    'org_uid': a})
        assert r.status_code == 200, r.get_json()
        c = _as(admin, 'de-b', ['infra_view', 'devices_view', 'dcim_view', f'org.{b}.view'])
        n = _nodes(c.get('/api/v1/infra/map').get_json())
        assert n['rtr-n']['site'] == '' and n['srv-n']['site'] == ''
        assert n['rtr-s']['site'] == fleet['s']['site']
        m = c.get('/api/v1/infra/map').get_json()
        # …nor the circuit one of whose ends it may not see.
        assert not [e for e in m['edges'] if e['kind'] == 'site']
        assert [s['name'] for s in m['sites']] == ['Sede Sur']
