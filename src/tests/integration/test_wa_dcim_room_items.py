#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What is in a room and not in a rack: a desk's PC and phone, a printer, an access point on the
ceiling, a wall outlet (`dc_item` with ``placement = 'room'``).

Its own routes (``/rooms/<uid>/items``, ``/room-items/<uid>``), whose it is following the room,
a cable from it to a rack's patch panel, the trace that follows that cable through the outlet
and the panel to the switch port, and the horizontal bundle (`hnet`) the circuits report from
the room to its rack.

With app and session: what is checked is the routes' answer.
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle, plan2d_catalog_js  # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
    from tests.integration.test_wa_dcim import _as                  # noqa: E402
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


@pytest.fixture()
def office(client):
    """An office with a desk (outlet + PC) and a communications room whose rack holds a patch
    panel and a switch, cabled the way an installer would: PC → outlet A, outlet A-R → panel 7,
    panel 7-R → switch Gi1/0/7."""
    _login(client)
    c = client
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Oficina'}))
    floor = _uid(c.post('/api/v1/dcim/floors', json={'site_uid': site, 'name': 'P1'}))
    desk = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Open space',
                                                   'floor_uid': floor}))
    com = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Comunicaciones'}))
    rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': com, 'name': 'IDF-1',
                                                   'u_height': 42}))
    panel = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 40,
                                                    'u_height': 1, 'role': 'patch_panel',
                                                    'label': 'Panel A'}))
    sw = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 30, 'u_height': 1,
                                                 'role': 'switch', 'label': 'SW-1'}))
    outlet = _uid(c.post(f'/api/v1/dcim/rooms/{desk}/items',
                         json={'role': 'outlet', 'label': 'P.01', 'pos_x': 1000, 'pos_y': 0,
                               'mount': 'wall'}))
    pc = _uid(c.post(f'/api/v1/dcim/rooms/{desk}/items',
                     json={'role': 'pc', 'label': 'PC-01', 'pos_x': 1200, 'pos_y': 800}))
    cab = lambda a, ap, b, bp, **k: _uid(c.post('/api/v1/dcim/cables', json=dict(  # noqa: E731
        {'a_item': a, 'a_port': ap, 'b_item': b, 'b_port': bp}, **k)))
    cab(pc, 'eth0', outlet, 'A', length_mm=3000)
    cab(outlet, 'A-R', panel, '7', length_mm=42000, label='P01-A')
    cab(panel, '7-R', sw, 'Gi1/0/7', length_mm=500)
    return dict(site=site, desk=desk, com=com, rack=rack, panel=panel, sw=sw, outlet=outlet, pc=pc)


class TestTheRoutes:

    def test_listed_with_their_box_and_their_role_defaults(self, client, office):
        d = client.get(f'/api/v1/dcim/rooms/{office["desk"]}/items').get_json()
        por = {i['label']: i for i in d['items']}
        assert set(por) == {'P.01', 'PC-01'}
        assert por['PC-01']['placement'] == 'room' and not por['PC-01']['rack_uid']
        box = por['PC-01']['box']
        assert (box['x'], box['y'], box['mount']) == (1200, 800, 'desk')
        assert box['base'] > 0                     # a PC stands on the desk, not on the floor
        assert por['P.01']['box']['mount'] == 'wall'
        assert 'outlet' in d['roles'] and set(d['mounts']) == {'desk', 'wall', 'ceiling', 'floor'}

    def test_moved_turned_renamed_but_never_into_a_rack(self, client, office):
        pc = office['pc']
        assert client.put(f'/api/v1/dcim/room-items/{pc}',
                          json={'pos_x': 2500, 'rotation': 90, 'label': 'PC-02'}).status_code == 200
        i = next(x for x in client.get(f'/api/v1/dcim/rooms/{office["desk"]}/items').get_json()['items']
                 if x['uid'] == pc)
        assert (i['box']['x'], i['box']['rot'], i['label']) == (2500, 90, 'PC-02')
        # The rack's fields are not this route's to write.
        client.put(f'/api/v1/dcim/room-items/{pc}', json={'rack_uid': office['rack'], 'u_start': 5,
                                                         'placement': 'u'})
        i = client.get(f'/api/v1/dcim/rooms/{office["desk"]}/items').get_json()['items']
        assert any(x['uid'] == pc and x['placement'] == 'room' and not x['rack_uid'] for x in i)
        # And a rack item is not a room item.
        assert client.put(f'/api/v1/dcim/room-items/{office["sw"]}',
                          json={'pos_x': 1}).status_code == 404

    def test_bad_values_are_refused(self, client, office):
        url = f'/api/v1/dcim/rooms/{office["desk"]}/items'
        assert client.post(url, json={'role': 'toaster'}).status_code == 400
        assert client.post(url, json={'role': 'pc', 'mount': 'roof'}).status_code == 400
        assert client.post(url, json={'role': 'pc', 'pos_x': 'far'}).status_code == 400
        assert client.post(url, json={'role': 'pc', 'pos_x': 1e12}).status_code == 400
        assert client.post('/api/v1/dcim/rooms/nope/items', json={'role': 'pc'}).status_code == 404

    def test_carried_to_another_room_of_the_same_site_only(self, client, office):
        pc = office['pc']
        assert client.put(f'/api/v1/dcim/room-items/{pc}',
                          json={'room_uid': office['com']}).status_code == 200
        otra = _uid(client.post('/api/v1/dcim/sites', json={'name': 'Otra'}))
        lejos = _uid(client.post('/api/v1/dcim/rooms', json={'site_uid': otra, 'name': 'X'}))
        assert client.put(f'/api/v1/dcim/room-items/{pc}',
                          json={'room_uid': lejos}).status_code == 400

    def test_deleted_with_its_cables(self, client, office):
        assert client.delete(f'/api/v1/dcim/items/{office["outlet"]}').status_code == 200
        cables = client.get('/api/v1/dcim/cables').get_json()
        cables = cables.get('cables', cables) if isinstance(cables, dict) else cables
        assert not [k for k in cables if office['outlet'] in (k.get('a_item'), k.get('b_item'))]

    def test_the_plan_and_the_3d_get_them(self, client, office):
        f = client.get(f'/api/v1/dcim/rooms/{office["desk"]}/features').get_json()
        assert {i['label'] for i in f['items']} == {'P.01', 'PC-01'}
        c = client.get(f'/api/v1/dcim/sites/{office["site"]}/contents').get_json()
        assert {i['label'] for i in c['rooms'][office['desk']]['items']} == {'P.01', 'PC-01'}


class TestWhoseItIs:

    @pytest.fixture()
    def scoped(self, admin, client, office):
        org = _uid(client.post('/api/v1/orgs', json={'name': 'A', 'short': 'A'}))
        otra = _uid(client.post('/api/v1/orgs', json={'name': 'B', 'short': 'B'}))
        client.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': office['site'],
                                                'org_uid': otra})
        ua = _as(admin, 'ua', ['dcim_view', 'dcim_edit', 'dcim_cable_edit', f'org.{org}.view'])
        return ua

    def test_somebody_elses_room_is_not_read_nor_written(self, scoped, office):
        assert scoped.get(f'/api/v1/dcim/rooms/{office["desk"]}/items').status_code == 403
        assert scoped.post(f'/api/v1/dcim/rooms/{office["desk"]}/items',
                           json={'role': 'pc'}).status_code == 403
        assert scoped.put(f'/api/v1/dcim/room-items/{office["pc"]}',
                          json={'pos_x': 1}).status_code == 403
        assert scoped.get(f'/api/v1/dcim/items/{office["pc"]}/trace').status_code == 403


class TestTheTrace:

    def test_from_the_pc_through_outlet_and_panel_to_the_switch_port(self, client, office):
        d = client.get(f'/api/v1/dcim/items/{office["pc"]}/trace').get_json()
        assert len(d['paths']) == 1
        saltos = [(h['label'], h['port'], h.get('out', '')) for h in d['paths'][0]]
        assert saltos == [('PC-01', 'eth0', ''), ('P.01', 'A', 'A-R'),
                          ('Panel A', '7', '7-R'), ('SW-1', 'Gi1/0/7', '')]
        assert d['paths'][0][1]['where'] == 'Open space'
        assert d['paths'][0][2]['where'] == 'IDF-1'
        assert d['paths'][0][2]['cable']['length_mm'] == 42000

    def test_and_back_from_the_switch_to_the_pc(self, client, office):
        d = client.get(f'/api/v1/dcim/items/{office["sw"]}/trace').get_json()
        assert [h['label'] for h in d['paths'][0]] == ['SW-1', 'Panel A', 'P.01', 'PC-01']

    def test_one_port_only(self, client, office):
        assert client.get(f'/api/v1/dcim/items/{office["sw"]}/trace?port=Gi1/0/8') \
            .get_json()['paths'] == []

    def test_a_loop_of_patch_cords_does_not_hang_it(self, client, office):
        # The installer's mistake: the panel's back port cabled back to the outlet's front.
        client.post('/api/v1/dcim/cables', json={'a_item': office['panel'], 'a_port': '8',
                                                 'b_item': office['outlet'], 'b_port': 'B-R'})
        client.post('/api/v1/dcim/cables', json={'a_item': office['outlet'], 'a_port': 'B',
                                                 'b_item': office['panel'], 'b_port': '8-R'})
        d = client.get(f'/api/v1/dcim/items/{office["outlet"]}/trace?port=B').get_json()
        assert d['paths'] and all(len(p) <= 25 for p in d['paths'])


class TestTheHorizontalBundle:

    def test_from_the_room_to_its_rack(self, client, office):
        d = client.get(f'/api/v1/dcim/sites/{office["site"]}/circuits').get_json()
        cables = [c for h in d['hnet'] for c in h.pop('cables')]
        assert d['hnet'] == [{'room': office['desk'], 'rack': office['rack'], 'total': 1,
                              'kinds': {'copper': 1}}]
        # And which cable it is, with both ends named: the 3D highlights one cable of a bundle.
        assert [(c['an'], c['ap'], c['bn'], c['bp'], c['label']) for c in cables]             == [('P.01', 'A-R', 'Panel A', '7', 'P01-A')]
        assert d['net'] == []           # the horizontal run is not a rack-to-rack trunk


_PROBE = r"""
__out = {};
_dcpFeat = {items: [
    {uid: 'i1', role: 'pc', label: 'PC-01', state: 'error',
     box: {x: 1000, y: 500, w: 450, d: 200, h: 450, base: 750, rot: 0, mount: 'desk'}},
    {uid: 'i2', role: 'outlet', label: 'P.01',
     box: {x: 0, y: 0, w: 80, d: 50, h: 80, base: 300, rot: 0, mount: 'wall'}}]};
const svg = _dcriSvg();
__out.agarres = (svg.match(/data-dcpi="/g) || []).length;
__out.abreviatura = svg.includes('>PC<');
__out.estado = (svg.match(/<circle/g) || []).length;
const e = _dc3dRoomBoxes({uid: 'r', name: 'Open', width_mm: 6000, depth_mm: 4000}, [], [], {},
                         {items: _dcriItems()});
const pc = e.cajas.find(k => k.lee && k.lee.ritem && k.lee.uid === 'i1');
__out.pcLee = pc ? [pc.lee.name, pc.lee.tipo, pc.lee.state] : null;
__out.punto = e.puntos['item:i1'];
__out.techo = !!e.puntos['room:r'];
__out.ficha = _dcriPanelHtml(_dcpFeat.items[0], '').includes('_dcriTrace(');
__out.salto = _dcriHopHtml({label: 'Panel A', role: 'patch_panel', port: '7', out: '7-R',
                            where: 'IDF-1'}).includes('7 → 7-R');
__out.oculto = _dcriHopHtml({hidden: true}).includes('badge');
"""


class TestTheScreen:

    def test_the_plan_draws_them_and_the_3d_stands_them_up(self, client):
        if shutil.which('node') is None:
            pytest.skip('no node: nothing to run the script with')
        _login(client)
        out = node_run(panel_bundle(client), plan2d_catalog_js(client) + _PROBE)
        assert out['agarres'] == 2 and out['abreviatura'] and out['estado'] == 1
        assert out['pcLee'] == ['PC-01', 'item', 'error']
        x, y, z = out['punto']
        assert abs(x - 1.225) < 1e-6 and abs(z - 0.6) < 1e-6 and abs(y - 1.2) < 1e-6
        assert out['techo'] and out['ficha'] and out['salto'] and out['oculto']
