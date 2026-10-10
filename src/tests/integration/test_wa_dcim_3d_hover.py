#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What is under the pointer in the inventory's 3D, and a rack opened where it stands — in `node`.

Asked for: passing the mouse over something in the 3D says what it is (a door by its name, a
cabinet, a rack…), and a rack reached while walking the 3D can be opened to see what it holds.
What these pin is the label each thing gives, that the engine asks for it only while no button
is pressed, and that an open rack is its own 3D scene put in its place, turned as it is.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='no node: nothing to run the script with')

_PROBE = r"""
__out = {};
_dc3dLook = {power: false, net: false, by: 'state', byRack: 'state', bad: false, stateRack: 'led'};

// ── The engine: a label beside the pointer, only while nothing is dragged ─────────
__out.motor = {
    hueco: ss3dHtml('v').includes('data-ss3d-tip'),
    pregunta: /if \(!V\.arrastre\) \{ _ss3dHover\(V, ev\); return; \}/.test(String(ss3dMove)),
    calla: String(ss3dMove).includes("ss3dTip(V, '')"),
    tactil: String(_ss3dHover).includes("ev.pointerType === 'touch'"),
    unaVezPorFotograma: String(_ss3dHover).includes('requestAnimationFrame'),
};

// ── The label of each thing ─────────────────────────────────────────────────────
const puerta = _dc3dTipHtml({name: 'Puerta CPD', kind: 'Lector', tipo: 'feature', model: 'Salto XS4 One',
                             lock: 'escutcheon', roomName: 'CPD', state: 'warning'});
__out.puerta = [puerta.includes('Puerta CPD'), puerta.includes('Salto XS4 One'),
                puerta.includes(t('dcim_lock_escutcheon')), puerta.includes('CPD'),
                puerta.includes('Lector')];
const rack = _dc3dTipHtml({name: 'R01', kind: 'Rack', tipo: 'rack', u: 42, used: 10, roomName: 'Sala A'});
__out.rack = [rack.includes('R01'), rack.includes('10/42 U'), rack.includes('Sala A')];
const equipo = _dc3dTipHtml({name: 'srv1', kind: 'Servidor', tipo: 'item', u: 2, u0: 5});
__out.equipo = equipo.includes('U5–U6');
// Without a name, what it is: an unnamed emergency light still says it is one.
const sinNombre = _dc3dTipHtml({name: '', kind: 'Luz de emergencia', tipo: 'feature'});
__out.sinNombre = [sinNombre.includes('Luz de emergencia'), (sinNombre.match(/Luz de emergencia/g) || []).length];

// ── Under the pointer: the same boxes a click picks ──────────────────────────────
const V = {id: 'p', escena: {cajas: [
    {color: [0.5, 0.5, 0.5, 1], m: ss3dModel(-1, 0, -1, 2, 2, 2, 0),
     lee: {name: 'Armario A', kind: 'Armario', tipo: 'feature'}},
    {color: [0.5, 0.5, 0.5, 0.1], m: ss3dModel(4, 0, 4, 2, 2, 2, 0),
     lee: {name: 'Cristal', kind: 'Rack', tipo: 'rack'}}]}};
__out.encima = _dc3dHoverThing({o: [0, 10, 0], d: [0, -1, 0]}, V).includes('Armario A');
__out.nada = _dc3dHoverThing({o: [20, 10, 20], d: [0, -1, 0]}, V);
// An open rack is glass: the pointer goes through it to what it holds.
__out.cristal = _dc3dHoverThing({o: [5, 10, 5], d: [0, -1, 0]}, V);

// ── In a floor or the building, the room whose floor it passes over ───────────────
const P = {id: 'p', escena: {cajas: [], salas: [{uid: 's', name: 'Sala de reuniones', y: 0,
                                                 frame: {x: 0, z: 0, W: 4, D: 3, rot: 0}}]}};
__out.sala = _ds3Hover({o: [2, 10, 1], d: [0, -1, 0]}, P).includes('Sala de reuniones');
__out.fuera = _ds3Hover({o: [9, 10, 9], d: [0, -1, 0]}, P);

// ── A rack opened where it stands ───────────────────────────────────────────────
const dentro = {rack: {uid: 'k', name: 'R01', u_height: 10, width_mm: 600, depth_mm: 1000},
                items: [{uid: 'a', label: 'srv1', role: 'server', u_start: 1, u_height: 2,
                         face: 'front', placement: 'u', state: 'error'}]};
const sala = {uid: 'r', name: 'CPD', width_mm: 8000, depth_mm: 6000};
const racks = (rot) => [{uid: 'k', name: 'R01', u_height: 10, width_mm: 600, depth_mm: 1000,
                         pos_x: 2000, pos_y: 3000, rotation: rot}];
const centro = (k) => [0, 1, 2].map(i => k.m[i] * 0.5 + k.m[4 + i] * 0.5 + k.m[8 + i] * 0.5 + k.m[12 + i]);
const delRack = (sc) => sc.cajas.filter(k => k.lee && k.lee.tipo === 'item');
_dc3dOpenRacks.clear();
__out.cerrado = delRack(_dc3dRoomBoxes(sala, racks(0), [], {}, {})).length;
_dc3dOpenRacks.set('k', {data: dentro, cables: {}, power: {}});
const abierto = _dc3dRoomBoxes(sala, racks(0), [], {}, {});
const caja = abierto.cajas.find(k => k.lee && k.lee.tipo === 'rack');
const srv = delRack(abierto)[0];
const c0 = srv ? centro(srv) : [0, 0, 0];
__out.abierto = {n: delRack(abierto).length, cristal: caja.color[3] < 0.5, open: caja.lee.open,
                 dentro: c0[0] > 2 && c0[0] < 2.6 && c0[2] > 3 && c0[2] < 4};
// Seen in the browser: its items' labels stayed at the room's corner, the front stripe hid
// what was opened, and an item's label did not say its room.
const rotulos = abierto.cajas.filter(k => k.lee && k.lee.tipo === 'item' && k.lee.at).map(k => k.lee.at);
__out.rotulos = rotulos.length > 0 && rotulos.every(a => a[0] > 1.9 && a[0] < 2.7 && a[2] > 2.9 && a[2] < 4.1);
const franja = (sc) => sc.cajas.filter(k => !k.lee && Math.abs(k.m[10] - 0.012) < 1e-6).length;
_dc3dOpenRacks.clear();
const _cerrado = _dc3dRoomBoxes(sala, racks(0), [], {}, {});
_dc3dOpenRacks.set('k', {data: dentro, cables: {}, power: {}});
__out.franja = [franja(_cerrado), franja(abierto)];
__out.salaEquipo = srv ? srv.lee.roomName : '';
// Turned a quarter: what it holds turns with it, about the rack's centre.
const girado = delRack(_dc3dRoomBoxes(sala, racks(90), [], {}, {}))[0];
const c1 = girado ? centro(girado) : [0, 0, 0];
__out.girado = c1[0] > 1.8 && c1[0] < 2.8 && c1[2] > 3.2 && c1[2] < 3.8;
// Opening it flies to its FRONT: the camera's angle is the side its stripe is on.
const _V = {id: 'p', cam: {mira: [0, 0, 0], radio: 5, theta: 0, phi: 1}, escena: {cajas: []}};
const giro = (rot) => {
    _dc3dOpenRacks.clear();
    _V.escena = _dc3dRoomBoxes(sala, racks(rot), [], {}, {});
    _V.anim = null;
    ss3dGet = () => _V; ss3dRebuild = () => {}; ss3dCard = () => {};
    _dc3dOpenRacks.set('k', {data: dentro, cables: {}, power: {}});
    const k = _V.escena.cajas.find(c => c.lee && c.lee.tipo === 'rack');
    const m = k.m;
    ss3dFlyToBox(_V, k);
    const fx = -m[8], fz = -m[10];
    _V.anim.hasta.theta = _V.anim.desde.theta + ((((Math.atan2(fz, fx) - _V.anim.desde.theta)
                                                % (2 * Math.PI)) + 3 * Math.PI) % (2 * Math.PI) - Math.PI);
    return [Math.round(Math.cos(_V.anim.hasta.theta)), Math.round(Math.sin(_V.anim.hasta.theta))];
};
// Rack at rot 0: its front stripe is on the -z side, so the eye goes to -z.
__out.deFrente = giro(0);
__out.vueloEnElCodigo = String(_dc3dOpenRack).includes('Math.atan2(fz, fx)');
_dc3dOpenRacks.clear();
_dc3dOpenRacks.set('k', {data: dentro, cables: {}, power: {}});
// The rack's card opens it here; an item's card in an open rack closes it.
__out.fichaRack = _dc3dCardHtml({name: 'R01', kind: 'Rack', tipo: 'rack', uid: 'k'}).includes('_dc3dOpenRack(' + jsStr('k') + ')');
__out.fichaEquipo = _dc3dCardHtml({name: 'srv1', kind: 'S', tipo: 'item', uid: 'a', rack: 'k'}).includes('_dc3dOpenRack(' + jsStr('k') + ')');
// Opening it again closes it, before anything is asked of the server.
ss3dRebuild = () => {};
ss3dCard = () => {};
_dc3dOpenRack('k');
__out.cierra = _dc3dOpenRacks.has('k');
__out.fichaCerrado = _dc3dCardHtml({name: 'srv1', kind: 'S', tipo: 'item', uid: 'a', rack: 'k'}).includes('_dc3dOpenRack');
"""


@pytest.fixture(scope='module')
def out():
    """One `node` run for the whole module: starting it costs more than looking."""
    pytest.importorskip('flask')
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var,
                  pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return node_run(panel_bundle(c), _PROBE)


class TestTheEngineAsksWhatIsUnderThePointer:
    def test_the_viewer_has_a_place_for_the_label(self, out):
        assert out['motor']['hueco']

    def test_only_while_nothing_is_dragged(self, out):
        assert out['motor']['pregunta'] and out['motor']['calla']

    def test_not_on_touch_and_once_per_frame(self, out):
        assert out['motor']['tactil'] and out['motor']['unaVezPorFotograma']


class TestTheLabelOfEachThing:
    def test_a_door_says_its_name_model_lock_and_room(self, out):
        assert out['puerta'] == [True, True, True, True, True]

    def test_a_rack_says_its_room_and_how_full(self, out):
        assert out['rack'] == [True, True, True]

    def test_an_item_says_its_us(self, out):
        assert out['equipo'] is True

    def test_an_unnamed_piece_says_what_it_is_once(self, out):
        assert out['sinNombre'] == [True, 1]


class TestWhatIsUnderThePointer:
    def test_the_box_under_it(self, out):
        assert out['encima'] is True

    def test_nothing_says_nothing(self, out):
        assert out['nada'] == ''

    def test_an_open_rack_is_glass(self, out):
        assert out['cristal'] == ''

    def test_in_a_floor_the_room_under_it(self, out):
        assert out['sala'] is True and out['fuera'] == ''


class TestARackOpenedWhereItStands:
    def test_closed_it_is_a_box(self, out):
        assert out['cerrado'] == 0

    def test_open_it_holds_its_items_in_its_place(self, out):
        assert out['abierto'] == {'n': 1, 'cristal': True, 'open': True, 'dentro': True}

    def test_its_labels_go_with_it_and_no_stripe_hides_it(self, out):
        assert out['rotulos'] is True
        assert out['franja'][0] >= 1 and out['franja'][1] == 0
        assert out['salaEquipo'] == 'CPD'

    def test_opening_it_flies_to_its_front(self, out):
        assert out['deFrente'] == [0, -1] and out['vueloEnElCodigo'] is True

    def test_turned_its_items_turn_with_it(self, out):
        assert out['girado'] is True

    def test_the_cards_open_and_close_it(self, out):
        assert out['fichaRack'] and out['fichaEquipo']

    def test_opening_it_again_closes_it(self, out):
        assert out['cierra'] is False and out['fichaCerrado'] is False
