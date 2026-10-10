#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A power source IS a piece of the plan: `dc_source.feature_uid`.

Reported from the screen: in the 3D, the mains, the panels and the UPSs stood in a column
OUTSIDE the building, beside the very same things drawn inside it as room pieces. A source had
no place — only a rack item when it was a UPS in a cabinet — so the power layer put the rest in
a row at the edge. Now a source says which piece of the plan it is (a panel, a room UPS, the
generator's zone), and the 3D draws it there, its cables reaching it.
"""

from __future__ import annotations

import io
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


@pytest.fixture()
def wa():
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    w = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    w._csrf_enabled = False
    w.app.config['TESTING'] = True
    return w


def _setup(c, nombre='S'):
    site = c.post('/api/v1/dcim/sites', json={'name': nombre}).get_json()['uid']
    room = c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Energía'}).get_json()['uid']
    pieza = lambda kind, label: c.post('/api/v1/dcim/features', json={   # noqa: E731
        'room_uid': room, 'kind': kind, 'label': label}).get_json()['uid']
    return site, room, pieza


class TestTheRoutes:

    def test_a_source_is_a_panel_of_its_site(self, wa):
        c = wa.app.test_client()
        _login(c)
        site, _room, pieza = _setup(c)
        cuadro = pieza('panel', 'Cuadro CPD')
        src = c.post('/api/v1/dcim/sources', json={'site_uid': site, 'name': 'Cuadro CPD',
                                                   'kind': 'panel', 'feature_uid': cuadro})
        assert src.status_code == 200
        uid = src.get_json()['uid']
        d = c.get('/api/v1/dcim/sources').get_json()
        assert next(s for s in d['sources'] if s['uid'] == uid)['feature_uid'] == cuadro
        assert [(p['uid'], p['source'], p['room_name']) for p in d['plan_pieces']] \
            == [(cuadro, uid, 'Energía')]
        circ = c.get(f'/api/v1/dcim/sites/{site}/circuits').get_json()
        assert circ['sources'][0]['feature'] == cuadro

    def test_not_a_door_not_another_sites_and_not_twice(self, wa):
        c = wa.app.test_client()
        _login(c)
        site, _room, pieza = _setup(c)
        otra, _r2, pieza2 = _setup(c, 'Otra')
        puerta, cuadro, ajeno = pieza('door', 'Puerta'), pieza('panel', 'C1'), pieza2('ups', 'SAI')
        nueva = lambda **k: c.post('/api/v1/dcim/sources', json=dict(  # noqa: E731
            {'site_uid': site, 'name': 'X', 'kind': 'panel'}, **k))
        assert nueva(feature_uid=puerta).status_code == 400
        assert nueva(feature_uid=ajeno).status_code == 400
        assert nueva(feature_uid='no-such').status_code == 400
        primera = nueva(feature_uid=cuadro).get_json()['uid']
        assert nueva(feature_uid=cuadro).status_code == 400          # already another source
        segunda = nueva().get_json()['uid']
        assert c.put(f'/api/v1/dcim/sources/{segunda}',
                     json={'feature_uid': cuadro}).status_code == 400
        assert c.put(f'/api/v1/dcim/sources/{primera}',
                     json={'feature_uid': cuadro}).status_code == 200   # itself, again: fine
        assert c.put(f'/api/v1/dcim/sources/{primera}', json={'feature_uid': ''}).status_code == 200
        _ = otra


_PROBE = r"""
__out = {};
// A room with a panel piece; the circuits say a source IS that piece, another is nowhere.
const sala = {uid: 'r', name: 'Energía', width_mm: 8000, depth_mm: 6000};
const piezas = [{uid: 'p1', kind: 'panel', label: 'Cuadro CPD', pos_x: 1000, pos_y: 300,
                 width_mm: 900, depth_mm: 400, rotation: 0}];
const e = _dc3dRoomBoxes(sala, [], piezas, {panel: {h: 2000, layer: 'room'}}, {});
__out.punto = e.puntos['feature:p1'];
_dcsPlan = {site: {uid: 's'}};
_dc3dLook = Object.assign({}, _dc3dLook, {power: true, net: false});
_dc3dCirc = {site: 's', loading: '', data: {net: [], power: [], sources: [
    {uid: 'a', name: 'Cuadro CPD', kind: 'panel', feature: 'p1', rack: '', upstream: 'b'},
    {uid: 'b', name: 'Acometida', kind: 'mains', feature: '', rack: '', upstream: ''},
    // A panel and a UPS of another floor: their piece and their rack are not in this scene.
    {uid: 'c', name: 'Cuadro planta 3', kind: 'panel', feature: 'p-otra', rack: '', upstream: 'b'},
    {uid: 'd', name: 'SAI P3', kind: 'ups', feature: '', rack: 'k-otro', upstream: 'c'}]}};
const antes = e.cajas.length;
_dc3dAddCircuits(e);
const nuevas = e.cajas.slice(antes);
__out.cajasFuente = nuevas.filter(k => k.lee && k.lee.tipo === 'source').map(k => k.lee.name);
// The upstream line from the panel starts at the piece, not at the edge.
const linea = nuevas.filter(k => k.lee && k.lee.tipo === 'power');
__out.lineaDesdePieza = linea.length > 0;
"""


class TestThe3D:

    def test_a_source_is_drawn_at_its_piece_and_only_the_unplaced_one_outside(self, wa):
        if shutil.which('node') is None:
            pytest.skip('no node: nothing to run the script with')
        c = wa.app.test_client()
        _login(c)
        out = node_run(panel_bundle(c), _PROBE)
        x, y, z = out['punto']
        assert abs(x - 1.45) < 1e-6 and abs(z - 0.5) < 1e-6 and y > 2.0   # over the panel
        # The panel's source draws no box of its own: the piece is it. Only the mains, which
        # is nowhere on the plan, stays in the row beside the building. Reported from the screen
        # again: in one floor's 3D, the panel and the UPS of ANOTHER floor stood in that row too —
        # they have a place, just not on this floor, so here they are not drawn.
        assert out['cajasFuente'] == ['Acometida']
        assert out['lineaDesdePieza'] is True
