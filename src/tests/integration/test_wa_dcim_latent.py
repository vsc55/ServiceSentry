#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Latent bugs found by a review of this build's DCIM and plan editor work — each pinned so it
does not come back.

Server: the generic item routes wrote a wall item's jacks and source unchecked; a role change
left the old role's jacks and source; a room moved to another site kept its sockets' sources;
`"disconnect": "false"` deleted cables; a strip carried to another site kept its source; emptying
a rack left another rack's strip pointing at a deleted item; and a real site named «Demo» was
taken for the demo. Panel (in `node`): leaving a floor kept the walls review —its keys, its undo
lock, and its walls saved onto the next floor—, a half-done calibration and the place mode; arrow
moves on two selections lost the first; a small box over a long wall missed it; the north tail
was never marked; a change inside an undo batch merged with one outside it; and the room item
card showed the old mount after saving it.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


@pytest.fixture()
def casa(client):
    _login(client)
    c = client
    s1 = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Sede'}))
    s2 = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Otra'}))
    room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s1, 'name': 'Oficina'}))
    room2 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s2, 'name': 'DR'}))
    src1 = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': s1, 'name': 'SAI-1', 'kind': 'ups'}))
    src2 = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': s2, 'name': 'SAI-2', 'kind': 'ups'}))
    toma = _uid(c.post(f'/api/v1/dcim/rooms/{room}/items', json={
        'role': 'power_outlet', 'source_uid': src1, 'jacks': [{'connector': 'cee-7-3', 'n': 2}]}))
    ra = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'RA', 'u_height': 42}))
    rx = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room2, 'name': 'RX', 'u_height': 42}))
    return dict(s1=s1, s2=s2, room=room, room2=room2, src1=src1, src2=src2, toma=toma, ra=ra, rx=rx)


class TestTheServer:

    def test_the_generic_item_route_does_not_write_jacks_or_source(self, client, admin, casa):
        r = client.put(f'/api/v1/dcim/items/{casa["toma"]}', json={'source_uid': casa['src2'], 'jacks': 'roto{'})
        assert r.status_code == 200
        it = admin._dcim_store.items.get(casa['toma'])
        assert it['source_uid'] == casa['src1'] and json.loads(it['jacks'])[0]['connector'] == 'cee-7-3'
        nuevo = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': casa['ra'], 'u_start': 1, 'u_height': 1,
                                                             'source_uid': casa['src1'], 'jacks': '[]x'}))
        assert admin._dcim_store.items.get(nuevo)['source_uid'] == ''

    def test_a_role_change_takes_the_old_roles_jacks_and_source(self, client, admin, casa):
        assert client.put(f'/api/v1/dcim/room-items/{casa["toma"]}', json={'role': 'pc'}).status_code == 200
        it = admin._dcim_store.items.get(casa['toma'])
        assert (it['jacks'], it['source_uid']) == ('', '')

    def test_a_room_moved_to_another_site_releases_its_sockets_source(self, client, admin, casa):
        assert client.put(f'/api/v1/dcim/rooms/{casa["room"]}', json={'site_uid': casa['s2']}).status_code == 200
        assert admin._dcim_store.items.get(casa['toma'])['source_uid'] == ''

    def test_disconnect_false_as_text_keeps_the_cables(self, client, admin, casa):
        c = client
        a = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': casa['ra'], 'u_start': 5, 'u_height': 1, 'label': 'A'}))
        b = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': casa['ra'], 'u_start': 6, 'u_height': 1, 'label': 'B'}))
        assert c.post('/api/v1/dcim/cables', json={'a_item': a, 'a_port': 'e0', 'b_item': b, 'b_port': 'e0'}).status_code == 200
        rb = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': casa['room'], 'name': 'RB', 'u_height': 42}))
        r = c.put(f'/api/v1/dcim/items/{a}', json={'rack_uid': rb, 'u_start': 5, 'disconnect': 'false'})
        assert r.status_code == 200 and r.get_json()['moved']['disconnected'] == 0
        assert admin._dcim_store.cables_of([a])

    def test_a_strip_carried_to_another_site_leaves_its_source(self, client, admin, casa):
        st = admin._dcim_store
        regleta = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': casa['ra'], 'label': 'PDU',
                                                               'role': 'pdu', 'placement': 'side'}))
        pdu = _uid(client.post('/api/v1/dcim/pdus', json={'rack_uid': casa['ra'], 'name': 'PDU-A', 'feed': 'a',
                                                          'outlets': 8, 'source_uid': casa['src1']}))
        st.pdus.update(pdu, {'item_uid': regleta}, actor='t')
        assert client.put(f'/api/v1/dcim/items/{regleta}', json={'rack_uid': casa['rx']}).status_code == 200
        assert st.pdus.get(pdu)['source_uid'] == '' and st.pdus.get(pdu)['rack_uid'] == casa['rx']

    def test_emptying_a_rack_releases_another_racks_strip(self, client, admin, casa):
        st = admin._dcim_store
        caja = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': casa['ra'], 'u_start': 3, 'u_height': 1}))
        rb = _uid(client.post('/api/v1/dcim/racks', json={'room_uid': casa['room'], 'name': 'RB', 'u_height': 42}))
        pdu = _uid(client.post('/api/v1/dcim/pdus', json={'rack_uid': rb, 'name': 'PDU-B', 'feed': 'a', 'outlets': 8}))
        st.pdus.update(pdu, {'item_uid': caja}, actor='t')
        assert client.delete(f'/api/v1/dcim/racks/{casa["ra"]}?contents=delete').status_code == 200
        assert st.pdus.get(pdu)['item_uid'] == ''

    def test_a_real_site_called_demo_is_not_the_demo(self, client, admin):
        _login(client)
        from lib.core.dcim import demo                                 # noqa: PLC0415
        mia = _uid(client.post('/api/v1/dcim/sites', json={'name': demo.SITE}))
        assert demo.find(admin._dcim_store) == []
        assert client.delete('/api/v1/dcim/demo').get_json()['removed'] == 0
        assert admin._dcim_store.sites.get(mia)


_PROBE = r"""
__out = {};
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
// Leaving the floor ends the walls review: no key listener, no undo lock, no walls saved elsewhere.
_dcw = {floor: 'fA', segs: [{kind: 'wall', x1: 0, y1: 0, x2: 1, y2: 0, thick_mm: 100}], sel: -1};
p2duLocalOpen();
_dcsP2d.placing = {key: 'pc'};
_dcPlanLeave();
__out.alDejar = [_dcw === null, P2DU.localOnly, _dcsP2d.placing === null];
// A review whose floor is not the open one saves nothing.
const envios = [];
_dcimSend = (m, u, b) => { envios.push(u); return Promise.resolve({ok: true}); };
_dcsFloor = () => ({uid: 'fB'});
_dcw = {floor: 'fA', segs: [], sel: -1};
_dcwSave();
__out.otraPlanta = [envios.length, _dcw === null];
// Arrow moves on two selections are both saved.
const guardados = [];
p2dSavePositions = (P, ms) => guardados.push(ms.map(m => m.uid));
const P = p2dMake('t', {may: () => true, step: () => 100, shift: () => {}, at: () => ({x: 0, y: 0}),
                        row: () => ({}), redraw: () => {}, inspector: () => {}, primary: () => null,
                        groupable: () => false});
P.picked = new Set(['rack||a']);
p2dArrow(P, {key: 'ArrowRight'});
P.picked = new Set(['rack||b']);
p2dArrow(P, {key: 'ArrowRight'});
__out.flechas = (P.arrowMoved || []).map(m => m.uid).sort();
// A small box in the middle of a long wall takes it.
__out.muroLargo = p2dSegInBox({x1: 0, y1: 0, x2: 20000, y2: 0}, 10100, -50, 10900, 50);
__out.muroFuera = p2dSegInBox({x1: 0, y1: 0, x2: 20000, y2: 0}, 10100, 100, 10900, 200);
// Inside a batch, a change does not merge with one from before it.
P2DU.stack = []; P2DU.redo = []; P2DU.localOnly = false; P2DU.markAt = null;
P2DU.shadow.set('/x/a', {pos_x: 0});
p2duRecord('/x/a', {pos_x: 0}, {pos_x: 5});
const marca = p2duMark();
P2DU.shadow.get('/x/a').pos_x = 5;
p2duRecord('/x/a', {pos_x: 5}, {pos_x: 9});
p2duBatch(marca);
__out.tanda = P2DU.stack.length;
"""


@pytest.fixture(scope='module')
def out():
    if shutil.which('node') is None:
        pytest.skip('no node: nothing to run the script with')
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return node_run(panel_bundle(c), _PROBE)


class TestThePanel:

    def test_leaving_a_floor_ends_the_review_the_undo_lock_and_placing(self, out):
        assert out['alDejar'] == [True, False, True]

    def test_a_review_of_another_floor_saves_nothing(self, out):
        assert out['otraPlanta'] == [0, True]

    def test_arrow_moves_on_two_selections_are_both_saved(self, out):
        assert out['flechas'] == ['a', 'b']

    def test_a_small_box_over_a_long_wall_takes_it(self, out):
        assert out['muroLargo'] is True and out['muroFuera'] is False

    def test_a_batch_does_not_merge_with_what_came_before_it(self, out):
        assert out['tanda'] == 2
