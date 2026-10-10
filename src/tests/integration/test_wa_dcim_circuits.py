#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The site's circuits for the 3D, and a floor's core — through the API.

Asked for: power and network drawn as layers over the room, floor and building in 3D, and the
stairs and lifts marked so the building shows the shaft through its floors. What these pin:

- the network is one run per PAIR of racks, with how many cables and of what kind; a cable
  inside one rack is not a run;
- every strip comes with its rack, branch and source, and a source that is a UPS item in a rack
  says that rack — its only physical place;
- a reader without access gets nothing;
- the site contents carry each rack's used U, for colouring by occupancy;
- a floor's core is stairs, a lift or nothing, and is saved where it was clicked.
"""

from __future__ import annotations

import pytest

from tests.conftest import _login

pytest.importorskip('flask')


def _sede(c):
    site = c.post('/api/v1/dcim/sites', json={'name': 'Circ'}).get_json()['uid']
    floor = c.post('/api/v1/dcim/floors', json={'site_uid': site, 'name': 'P0', 'level': 0}).get_json()['uid']
    room = c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD', 'floor_uid': floor}).get_json()['uid']
    racks = [c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': n, 'u_height': 20}).get_json()['uid']
             for n in ('R1', 'R2', 'R3')]
    item = lambda rack, u, role='server', label='srv': c.post(  # noqa: E731
        '/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': u, 'label': label, 'role': role}).get_json()['uid']
    a1, a2, b1 = item(racks[0], 1), item(racks[0], 3), item(racks[1], 1)
    c3 = item(racks[2], 1)
    for a, b, kind in ((a1, b1, 'copper'), (a2, b1, 'fiber'), (a1, a2, 'copper'), (a2, c3, 'copper')):
        c.post('/api/v1/dcim/cables', json={'a_item': a, 'b_item': b, 'kind': kind})
    sai = item(racks[2], 10, 'ups', 'SAI-1')
    mains = c.post('/api/v1/dcim/sources', json={'site_uid': site, 'name': 'Acometida', 'kind': 'mains'}).get_json()['uid']
    ups = c.post('/api/v1/dcim/sources', json={'site_uid': site, 'name': 'SAI', 'kind': 'ups',
                                               'upstream_uid': mains, 'item_uid': sai}).get_json()['uid']
    c.post('/api/v1/dcim/pdus', json={'rack_uid': racks[0], 'name': 'PDU-A', 'feed': 'a', 'source_uid': ups})
    return {'site': site, 'floor': floor, 'racks': racks, 'mains': mains, 'ups': ups}


class TestTheCircuits:
    def test_one_run_per_pair_of_racks_with_its_kinds(self, admin, client):
        _login(client)
        s = _sede(client)
        d = client.get(f"/api/v1/dcim/sites/{s['site']}/circuits").get_json()
        r1, r2, r3 = s['racks']
        runs = {tuple(sorted((x['a'], x['b']))): x for x in d['net']}
        assert set(runs) == {tuple(sorted((r1, r2))), tuple(sorted((r1, r3)))}, 'the in-rack cable is no run'
        par = runs[tuple(sorted((r1, r2)))]
        assert par['total'] == 2 and par['kinds'] == {'copper': 1, 'fiber': 1}

    def test_every_strip_with_its_source_and_a_ups_says_its_rack(self, admin, client):
        _login(client)
        s = _sede(client)
        d = client.get(f"/api/v1/dcim/sites/{s['site']}/circuits").get_json()
        assert [(p['rack'], p['feed'], p['source']) for p in d['power']] == [(s['racks'][0], 'a', s['ups'])]
        fuentes = {x['uid']: x for x in d['sources']}
        assert fuentes[s['ups']]['rack'] == s['racks'][2]
        assert fuentes[s['ups']]['upstream'] == s['mains']
        assert fuentes[s['mains']]['rack'] == ''

    def test_unknown_site_and_no_session(self, admin, client):
        _login(client)
        assert client.get('/api/v1/dcim/sites/nope/circuits').status_code == 404
        anon = admin.app.test_client()
        assert anon.get('/api/v1/dcim/sites/nope/circuits').status_code in (302, 401, 403)

    def test_the_contents_carry_the_used_u(self, admin, client):
        _login(client)
        s = _sede(client)
        d = client.get(f"/api/v1/dcim/sites/{s['site']}/contents").get_json()
        racks = [r for room in d['rooms'].values() for r in room['racks']]
        assert all('used_u' in r for r in racks)
        assert {r['name']: r['used_u'] for r in racks}['R1'] == 2


class TestTheRoomsRacksToo:
    def test_a_rooms_racks_carry_the_used_u(self, admin, client):
        """Seen in the browser: «Colorear por → Ocupación» left every rack grey in the room's
        3D — the room asks /racks?room=, which did not say how full each rack is."""
        _login(client)
        s = _sede(client)
        room = client.get(f"/api/v1/dcim/sites/{s['site']}/contents").get_json()['rooms']
        uid = next(iter(room))
        racks = client.get(f'/api/v1/dcim/racks?room={uid}').get_json()['racks']
        assert {r['name']: r['used_u'] for r in racks}['R1'] == 2


class TestAFloorsCore:
    def test_stairs_or_a_lift_saved_where_clicked(self, admin, client):
        _login(client)
        s = _sede(client)
        r = client.put(f"/api/v1/dcim/floors/{s['floor']}", json={'core_kind': 'lift', 'core_x': 12000, 'core_y': 3500})
        assert r.status_code == 200, r.get_json()
        f = client.get(f"/api/v1/dcim/sites/{s['site']}/floors").get_json()['floors'][0]
        assert (f['core_kind'], f['core_x'], f['core_y']) == ('lift', 12000, 3500)

    def test_anything_else_is_refused(self, admin, client):
        _login(client)
        s = _sede(client)
        assert client.put(f"/api/v1/dcim/floors/{s['floor']}", json={'core_kind': 'tobogan'}).status_code == 400
