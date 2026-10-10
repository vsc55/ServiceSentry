#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The rack in 3D, the circuits, and the tools over the inventory's 3D — in `node`.

Asked for: phase 2 (one rack in 3D), phase 3 (power and network as layers) and nine more
things: search, colour by, only problems, live state, the camera in the address, a picture,
measuring, walking, and the floors' stairs and lifts. What these pin is the arithmetic and the
scene each one builds; the browser drew them in the verification pass.
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
_dc3dLook = {power: false, net: false, by: 'state', byRack: 'state', bad: false};

// ── The rack in 3D ──────────────────────────────────────────────────────────────
const datos = {rack: {uid: 'k', name: 'R01', u_height: 10, width_mm: 600, depth_mm: 1000, desc_units: 0},
               items: [
    {uid: 'a', label: 'srv1', role: 'server', u_start: 1, u_height: 2, face: 'front', placement: 'u', state: 'error'},
    {uid: 'b', label: 'sw1', role: 'switch', u_start: 10, u_height: 1, face: 'rear', placement: 'u', state: 'ok'},
    {uid: 'c', label: 'pdu1', role: 'pdu', placement: 'side'},
    {uid: 'd', label: 'ups1', role: 'ups', placement: 'near', u_height: 0},
    {uid: 'e', u_start: 5, u_height: 1, face: 'front', placement: 'u', foreign: true},
    {uid: 'f', label: 'hijo', role: 'other', parent_uid: 'g', u_start: 4, u_height: 1},
    {uid: 'g', label: 'bandeja', role: 'shelf', u_start: 4, u_height: 1, face: 'full', placement: 'u'}]};
const r3 = _dcr3dScene(datos);
// The boxes that say a state: no name of their own, the state's colour.
const _marcas = (sc) => sc.cajas.filter(k => !k.lee && [0, 1, 2].every(i => k.color[i] === _DC3_STATE.error[i]));
// Every design of the state, on the same server. None hides the photo: no opaque mark is
// wider than 7 mm or taller than 4 mm across the face, and the tint lets it through.
__out.disenos = {};
for (const e of _DCR3_MARKS) {
    const ks = _marcas(_dcr3dScene(datos, {por: 'state', estado: e}));
    __out.disenos[e] = {n: ks.length,
        tapa: ks.some(k => k.color[3] >= 1 && Math.abs(k.m[0]) > 0.0071 && Math.abs(k.m[5]) > 0.0041),
        tinte: ks.some(k => k.color[3] < 0.5 && Math.abs(k.m[0]) > 0.4)};
}
const caja = (uid) => r3.cajas.find(k => k.lee && k.lee.uid === uid);
const y0 = (k) => k.m[13], alto = (k) => k.m[5], z0 = (k) => k.m[14], hondo = (k) => k.m[10];
__out.rack = {
    srvAbajo: Math.abs(y0(caja('a')) - 0.08) < 1e-6,
    srvAlto: Math.abs(alto(caja('a')) - (2 * 0.04445 - 0.002)) < 1e-6,
    swArriba: Math.abs(y0(caja('b')) - (0.08 + 9 * 0.04445)) < 1e-6,
    swDetras: z0(caja('b')) + hondo(caja('b')) <= 1.0 && z0(caja('b')) > 0.3,
    srvDelante: z0(caja('a')) < 0.1,
    regletaDe0U: Math.abs(alto(caja('c')) - 10 * 0.04445) < 1e-6,
    junto: caja('d').m[12] > 0.6,
    ajeno: r3.cajas.some(k => k.borde && !k.lee),
    // Mounted on a tray: drawn on it, and the tray becomes the plate under it.
    hijoEncima: !!caja('f') && y0(caja('f')) > y0(caja('g')) && alto(caja('g')) < 0.01,
    franja: _marcas(r3).length,
    camara: [r3.theta < 0, r3.phi > 1],
};
// Numbered from the top: U1 is the highest row.
const arriba = _dcr3dScene({rack: Object.assign({}, datos.rack, {desc_units: 1}), items: [datos.items[0]]});
__out.rackDesc = y0(arriba.cajas.find(k => k.lee && k.lee.uid === 'a')) > 0.08 + 7 * 0.04445;
// Colour by warranty, and only problems.
const garantia = _dcr3dScene({rack: datos.rack, items: [Object.assign({}, datos.items[0], {warranty_until: '2000-01-01'})]},
                             {por: 'warranty'});
__out.garantia = garantia.cajas.find(k => k.lee).color === _DC3_STATE.error;
const mal = _dcr3dScene(datos, {mal: true});
__out.soloMal = [mal.cajas.find(k => k.lee && k.lee.uid === 'b').color[3], mal.cajas.find(k => k.lee && k.lee.uid === 'a').color[3]];
// The card of an item.
const ficha = _dc3dCardHtml(caja('a').lee);
__out.ficha = [ficha.includes('srv1'), ficha.includes('U1–U2'), ficha.includes("_dcimOpen('edit','item'")];
// The model's photos, on the faces that are seen.
const conFotos = _dcr3dScene({rack: datos.rack, items: [
    Object.assign({}, datos.items[0], {face: 'full', images: {front: 'f.png', rear: 'r.png'}}),
    Object.assign({}, datos.items[1], {images: {front: 'sw.png', rear: 'swr.png'}}),
    Object.assign({}, datos.items[4], {images: {front: 'x.png'}})]});
const esq = (m, u, v) => [m[0] * u + m[8] * v + m[12], m[1] * u + m[9] * v + m[13], m[2] * u + m[10] * v + m[14]];
const foto = (n) => conFotos.planos.find(p => p.data.endsWith(n));
const cajaF = conFotos.cajas.find(k => k.lee && k.lee.uid === 'a');
const fr = foto('f.png'), re = foto('r.png'), sw = foto('sw.png');
// Shared U and trays: the slots as the elevation numbers them, from 1, slot 1 on the viewer's
// left from the front (the larger x).
const reparto = _dcr3dScene({rack: datos.rack, items: [
    {uid: 'h1', label: 'Nodo 1', role: 'server', u_start: 3, u_height: 1, face: 'full', placement: 'u', u_slots: 2, u_slot: 1, images: {front: 'n.png'}},
    {uid: 'h2', label: 'Nodo 2', role: 'server', u_start: 3, u_height: 1, face: 'full', placement: 'u', u_slots: 2, u_slot: 2, images: {front: 'n.png'}},
    {uid: 't', label: 'Bandeja', role: 'shelf', u_start: 6, u_height: 1, face: 'full', placement: 'u'},
    {uid: 'm1', label: 'Mini 1', role: 'server', parent_uid: 't', u_start: 6, u_height: 1, images: {front: 'm.png', rear: 'mr.png'}},
    {uid: 'm2', label: 'Mini 2', role: 'server', parent_uid: 't', u_start: 6, u_height: 1, images: {front: 'm.png'}}]});
const cajaR = (uid) => reparto.cajas.find(k => k.lee && k.lee.uid === uid);
const xs = (k) => [k.m[12], k.m[12] + k.m[0]];
const rail0 = Math.min(...reparto.cajas.filter(k => k.lee && !k.lee.uid.startsWith('m') && k.lee.uid !== 't').map(k => k.m[12]));
const h1 = xs(cajaR('h1')), h2 = xs(cajaR('h2')), m1 = xs(cajaR('m1')), m2 = xs(cajaR('m2')), tr = xs(cajaR('t'));
__out.reparto = {
    dentro: h2[0] >= rail0 - 1e-6 && h1[1] <= rail0 + 0.4826 + 1e-6,
    noSePisan: h2[1] <= h1[0] + 1e-6,
    primeroALaIzquierda: h1[0] > h2[0],
    minisEnLaBandeja: m1[0] >= tr[0] - 1e-6 && m2[1] <= tr[1] + 1e-6 && m1[0] > m2[0],
    fotos: reparto.planos.length,
};
// The cables in the rack: network between two items and out through the roof, power from an
// item to its outlet on a side strip.
const cableado = {rack: datos.rack, items: [
    {uid: 'sv', label: 'srv', role: 'server', u_start: 2, u_height: 1, face: 'full', placement: 'u'},
    {uid: 'tor', label: 'sw', role: 'switch', u_start: 9, u_height: 1, face: 'full', placement: 'u'},
    {uid: 'pa', label: 'PDU-A', role: 'pdu', placement: 'side'}]};
const conCables = (redes, energia) => _dcr3dScene(cableado, {redes, energia,
    cables: {cables: [{a_item: 'sv', b_item: 'tor', kind: 'copper', color: 'red'},
                      {a_item: 'tor', b_item: 'lejos', kind: 'fiber', color: ''}],
             colors: [['red', '#dc2626']]},
    power: {pdus: [{uid: 'p1', item_uid: 'pa', feed: 'a', outlets: 10, color: '#2f6fed'}],
            items: [{uid: 'sv', feeds: [{pdu_uid: 'p1', outlet: 10}]}]}});
const tubos = (sc) => sc.cajas.filter(k => k.cable);
const extremo = (m) => [m[12] + m[0], m[13] + m[1], m[14] + m[2]];
const todo = conCables(true, true), sinNada = conCables(false, false);
const rojos = tubos(todo).filter(k => Math.abs(k.color[0] - 0xdc / 255) < 1e-3 && k.color[1] < 0.2);
const azules = tubos(todo).filter(k => Math.abs(k.color[2] - 0xed / 255) < 1e-3);
const techo = todo.H;
const regleta = todo.cajas.find(k => k.lee && k.lee.uid === 'pa');
const finToma = azules.length ? extremo(azules[azules.length - 1].m) : [0, 0, 0];
__out.cables = {
    apagados: tubos(sinNada).length,
    red: rojos.length > 0,
    porElTecho: tubos(todo).some(k => Math.max(k.m[13], extremo(k.m)[1]) > techo),
    corriente: azules.length > 0,
    // Outlet 10 of 10 is at the top of the strip.
    tomaArriba: finToma[1] > regleta.m[13] + regleta.m[5] * 0.85,
    enLaRegleta: Math.abs(finToma[0] - (regleta.m[12] + regleta.m[0] / 2)) < 0.01,
};
// Seen in the browser: names on the face, not on the lid; an unwatched item's LED grey; power
// cords dark with the branch on the plug; a tray's mini PC as deep as a mini PC.
const sinVigilar = _dcr3dScene(cableado, {por: 'state'});
__out.legible = {
    rotuloEnLaCara: caja('a').lee.at[2] < z0(caja('a')),
    pilotoGris: sinVigilar.cajas.filter(k => !k.lee && !k.cable && k.color[0] === _DCR3_OFF[0]).length,
    cordonOscuro: tubos(todo).filter(k => k.color[0] < 0.45 && k.color[2] < 0.45).length > 0,
    miniCorto: Math.abs(cajaR("m1").m[10]) <= 0.3 + 1e-6,
};
__out.fotos = {
    cuantas: conFotos.planos.length,
    delanteDeLaCaja: esq(fr.m, 0, 0)[2] < cajaF.m[14] && esq(re.m, 0, 0)[2] > cajaF.m[14] + cajaF.m[10],
    arribaEsArriba: esq(fr.m, 0, 0)[1] > esq(fr.m, 0, 1)[1],
    // From the front one looks towards +z, so the picture's left is the larger x.
    izquierdaDelante: esq(fr.m, 0, 0)[0] > esq(fr.m, 1, 0)[0],
    izquierdaDetras: esq(re.m, 0, 0)[0] < esq(re.m, 1, 0)[0],
    traseraSinSuDetras: !foto('swr.png') && esq(sw.m, 0, 0)[2] > 0.5,
    ajenoSin: !foto('x.png'),
};

// ── Colour by, in the room ──────────────────────────────────────────────────────
_dc3dLook.by = 'occupancy';
__out.ocupacion = [_dc3dRackColor({u_height: 42, used_u: 40}) === _DC3_STATE.error,
                   _dc3dRackColor({u_height: 42, used_u: 25}) === _DC3_STATE.warning,
                   _dc3dRackColor({u_height: 42, used_u: 2}) === _DC3_STATE.ok];
_dc3dLook.by = 'org';
__out.empresa = [JSON.stringify(_dc3dRackColor({org_uid: 'x'})) === JSON.stringify(_dc3dOrgColor('x')),
                 JSON.stringify(_dc3dOrgColor('x')) !== JSON.stringify(_dc3dOrgColor('y'))];
_dc3dLook.by = 'state';

// ── The circuits ────────────────────────────────────────────────────────────────
const sala = _dc3dRoomBoxes({uid: 's', width_mm: 8000, depth_mm: 6000}, [
    {uid: 'r1', name: 'R1', pos_x: 0, pos_y: 0, u_height: 42, roll: {}},
    {uid: 'r2', name: 'R2', pos_x: 3000, pos_y: 0, u_height: 42, roll: {}}], [], {}, {});
__out.puntos = Object.keys(sala.puntos).sort();
_dcsPlan = null;
_dcimPlan = {room: {uid: 's', site_uid: 'sede'}};
_dc3dCirc = {site: 'sede', loading: '', data: {
    net: [{a: 'r1', b: 'r2', total: 5, kinds: {fiber: 3, copper: 2}}],
    power: [{rack: 'r1', pdu: 'p', name: 'PDU-A', feed: 'a', source: 'ups'},
            {rack: 'r2', pdu: 'q', name: 'PDU-B', feed: 'b', source: 'red'}],
    sources: [{uid: 'ups', name: 'SAI', kind: 'ups', upstream: 'red', rack: 'r2'},
              {uid: 'red', name: 'Acometida', kind: 'mains', upstream: '', rack: ''}]}};
const antes = sala.cajas.length;
_dc3dLook.net = true; _dc3dLook.power = true;
_dc3dAddCircuits(sala);
const nuevas = sala.cajas.slice(antes);
__out.circuitos = {
    red: nuevas.filter(k => k.lee && k.lee.tipo === 'run').length,
    redColor: nuevas.find(k => k.lee && k.lee.tipo === 'run').color === _DC3_RUN_COLOR.fiber,
    energia: nuevas.filter(k => k.lee && k.lee.tipo === 'power').length > 0,
    ramaA: nuevas.some(k => k.lee && k.lee.tipo === 'power' && k.color === _DC3_FEED_COLOR.a),
    fuenteSuelta: nuevas.filter(k => k.lee && k.lee.tipo === 'source').map(k => k.lee.name),
    sinRotulo: nuevas.filter(k => k.lee && ['run', 'power'].includes(k.lee.tipo)).every(k => k.lee.sinRotulo),
};
_dc3dLook.net = false; _dc3dLook.power = false;

// ── Segments, halos, anchors that move ──────────────────────────────────────────
const tubo = ss3dTube([0, 0, 0], [3, 0, 4], 0.1);
__out.tubo = Math.round(Math.hypot(tubo[0], tubo[1], tubo[2]) * 1000) / 1000;
const halo = ss3dGrow(ss3dModel(0, 0, 0, 2, 2, 2, 0), 1.5);
__out.halo = [halo[0], halo[12]];
const puesta = ss3dPlace({cajas: [], W: 2, D: 2, puntos: {p: [1, 0, 1]}}, 10, 0, 5, 0, 1);
__out.puntoMovido = puesta.puntos.p;

// ── Search, locally ─────────────────────────────────────────────────────────────
_SS3D.set(_DC3D_BOX, {gl: null, escena: {cajas: [
    {color: [1, 1, 1, 1], m: ss3dModel(0, 0, 0, 1, 1, 1, 0), lee: {uid: 'x1', name: 'Rack-Norte'}},
    {color: [1, 1, 1, 1], m: ss3dModel(3, 0, 0, 1, 1, 1, 0), lee: {uid: 'x2', name: 'Rack-Sur'}}]}, opts: {}});
const dichos = [];
ss3dSay = (id, txt) => dichos.push(txt);
_dc3dSearch('rack', 'room');
const primero = _dc3dFoco;
_dc3dSearch('rack', 'room');
__out.buscar = [primero, _dc3dFoco, dichos[0]];
_SS3D.delete(_DC3D_BOX);
_dc3dFoco = '';

// ── The camera in the address ───────────────────────────────────────────────────
_dc3dUrlTake(new URLSearchParams('v3d=rack&cam=1.5,2,3,10,0.7,1.1,o'));
__out.urlCam = _dc3dCamTake();
__out.urlCamOnce = _dc3dCamTake();
__out.urlVista = _dcRackView;
const url = new URL('http://x/admin/dcim');
_dcimRack = null; _dc3d = {on: true}; _dcimPlan = {room: {uid: 's'}};
_SS3D.set(_DC3D_BOX, {cam: {mira: [1, 2, 3], radio: 9, theta: 0.5, phi: 1, orto: false}});
_dc3dUrlWrite(url);
__out.urlEscrita = [url.searchParams.get('v3d'), url.searchParams.get('cam')];
_SS3D.delete(_DC3D_BOX);
_dc3d = null;

// ── Measuring ───────────────────────────────────────────────────────────────────
const MV = {id: 'm', gl: null, cv: {}, escena: {cajas: []}, medir: {pts: []}, opts: {}};
_ss3dMeasureClick(MV, {o: [0, 10, 0], d: [0, -1, 0]});
const dist = _ss3dMeasureClick(MV, {o: [3, 10, 4], d: [0, -1, 0]});
__out.medir = [Math.round(dist * 100) / 100, MV.extras.length];

// ── A floor's core ──────────────────────────────────────────────────────────────
const cajasN = [], rotN = [];
_ds3Core({core_kind: 'lift', core_x: 5000, core_y: 2000}, cajasN, rotN);
__out.nucleo = [cajasN.length, cajasN[0].color[3] < 1, rotN[0].name === t('dcim_core_lift'),
                Math.round(cajasN[0].m[12] * 10) / 10];
const vacio = [];
_ds3Core({core_kind: ''}, vacio, []);
__out.sinNucleo = vacio.length;

// ── Fixes seen in the browser ───────────────────────────────────────────────────
__out.rackCamara = String(_dcr3dMount).includes('_dc3dCamTake()');
const sala2 = _dc3dRoomBoxes({uid: 's'}, [{uid: 'zz', name: 'R2', pos_x: 0, pos_y: 0, u_height: 42, roll: {}},
                                          {uid: 'aa', name: 'R1', pos_x: 2000, pos_y: 0, u_height: 42, roll: {}}], [], {}, {});
_dcsPlan = null;
_dcimPlan = {room: {uid: 's', site_uid: 'sede'}};
_dc3dCirc = {site: 'sede', loading: '', data: {net: [{a: 'aa', b: 'zz', total: 1, kinds: {copper: 1}}], power: [], sources: []}};
_dc3dLook.net = true;
_dc3dAddCircuits(sala2);
_dc3dLook.net = false;
const tirada = sala2.cajas.find(k => k.lee && k.lee.tipo === 'run').lee;
__out.tirada = [tirada.name, tirada.kind.startsWith('1 cable:')];
const PV = {id: 'p', escena: {cajas: [{color: [0.5, 0.8, 0.6, 0.28], m: ss3dModel(-1, 0, -1, 2, 3, 2, 0),
                                       lee: {name: 'Escalera', tipo: 'core'}}]}};
ss3dCard = () => {};
ss3dFlyToBox = () => {};
__out.nucleoPulsable = _dc3dPickThing({o: [0, 10, 0], d: [0, -1, 0]}, PV);
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


class TestTheRackIn3D:
    def test_each_item_in_its_u_at_its_height(self, out):
        r = out['rack']
        assert r['srvAbajo'] and r['srvAlto'] and r['swArriba']

    def test_front_and_rear_mounted_from_their_rails(self, out):
        assert out['rack']['srvDelante'] and out['rack']['swDetras']

    def test_side_strips_beside_items_and_foreign_ones(self, out):
        r = out['rack']
        assert r['regletaDe0U'] and r['junto'] and r['ajeno'] and r['hijoEncima']

    def test_state_on_the_front_and_a_camera_from_the_front(self, out):
        assert out['rack']['franja'] == 2              # the LED and its halo, by default and out['rack']['franjaFina']
        assert out['rack']['camara'] == [True, True]

    def test_every_state_design_leaves_the_photo_visible(self, out):
        """Reported from the screen: the state was a 6 cm block over the model's photo. Five
        designs to choose from in the toolbar, none of them covering it."""
        d = out['disenos']
        assert {k: v['n'] for k, v in d.items()} == {'led': 2, 'edge': 1, 'top': 1, 'frame': 4,
                                                     'tint': 1, 'none': 0}
        assert not any(v['tapa'] for v in d.values())
        assert d['tint']['tinte']

    def test_numbered_from_the_top_u1_is_the_highest(self, out):
        assert out['rackDesc']

    def test_colour_by_warranty_and_only_problems(self, out):
        assert out['garantia']
        assert out['soloMal'][0] < 0.5 and out['soloMal'][1] == 1

    def test_the_item_card(self, out):
        assert out['ficha'] == [True, True, True]

    def test_a_shared_u_and_a_tray_as_the_elevation_draws_them(self, out):
        """Reported from the screen: in a U shared by several items no photo showed. Slots
        were counted from 0, so the second half of a U fell outside the rack, and what was
        mounted on a tray was not drawn at all."""
        r = out['reparto']
        assert r['dentro'] and r['noSePisan'] and r['primeroALaIzquierda']
        assert r['minisEnLaBandeja']
        assert r['fotos'] == 5          # two nodes, two minis' fronts and one mini's rear

    def test_the_cables_in_the_rack(self, out):
        """Asked for from the screen: the rack in 3D drew no cables. Network cables go from
        port to port through the side channel, and out through the roof when the other end is in
        another rack; power cords end on their outlet, at its height on the strip, in the
        branch's colour. Both can be switched off."""
        c = out['cables']
        assert c['apagados'] == 0
        assert c['red'] and c['porElTecho']
        assert c['corriente'] and c['tomaArriba'] and c['enLaRegleta']

    def test_it_reads_as_seen_in_the_browser(self, out):
        """Checked in the browser: names fell on the item above; nothing showed a LED in a
        demo nobody watches; branch A's blue was the copper's blue; a mini PC on a tray was
        64 cm deep."""
        lg = out['legible']
        assert lg['rotuloEnLaCara'] and lg['cordonOscuro'] and lg['miniCorto']
        assert lg['pilotoGris'] == 4            # two unwatched items, a LED and its glow each

    def test_a_models_photos_on_the_faces_that_are_seen(self, out):
        """Reported from the screen: the rack in 3D drew plain boxes, though the rack already
        brought each model's photos. Front on the front, rear on the back, right way up and not
        mirrored from either side; a rear-only item shows its front to the rear door, and a
        foreign one shows none."""
        f = out['fotos']
        assert f['cuantas'] == 3
        assert f['delanteDeLaCaja'] and f['arribaEsArriba']
        assert f['izquierdaDelante'] and f['izquierdaDetras']
        assert f['traseraSinSuDetras'] and f['ajenoSin']


class TestColourBy:
    def test_occupancy(self, out):
        assert out['ocupacion'] == [True, True, True]

    def test_company_one_colour_each(self, out):
        assert out['empresa'] == [True, True]


class TestTheCircuits:
    def test_each_rack_leaves_an_anchor_on_its_top(self, out):
        assert out['puntos'] == ['rack:r1', 'rack:r2']

    def test_network_runs_in_the_colour_of_what_they_carry(self, out):
        c = out['circuitos']
        assert c['red'] >= 1 and c['redColor']

    def test_power_by_branch_and_a_loose_source_beside(self, out):
        c = out['circuitos']
        assert c['energia'] and c['ramaA']
        assert c['fuenteSuelta'] == ['Acometida'], 'the UPS is in R2; the mains has no place'

    def test_runs_carry_no_name_tag(self, out):
        assert out['circuitos']['sinRotulo']


class TestTheEngineTools:
    def test_a_tube_from_one_point_to_another(self, out):
        assert out['tubo'] == 5

    def test_a_halo_grown_about_its_centre(self, out):
        assert out['halo'] == pytest.approx([3, -0.5])

    def test_anchors_move_with_their_scene(self, out):
        assert out['puntoMovido'] == [11, 0, 6]

    def test_measuring_two_points(self, out):
        assert out['medir'] == [5, 3]


class TestSearchAndTheAddress:
    def test_search_finds_and_enter_goes_to_the_next(self, out):
        primero, segundo, dicho = out['buscar']
        assert primero == 'x1' and segundo == 'x2' and '1' in dicho and '2' in dicho

    def test_the_address_brings_the_camera_once(self, out):
        assert out['urlCam'] == {'mira': [1.5, 2, 3], 'radio': 10, 'theta': 0.7, 'phi': 1.1, 'orto': True}
        assert out['urlCamOnce'] is None
        assert out['urlVista'] == '3d'

    def test_and_the_viewer_writes_it(self, out):
        assert out['urlEscrita'] == ['room', '1.00,2.00,3.00,9.00,0.50,1.00']


class TestAFloorsCore:
    def test_a_glass_column_with_its_name(self, out):
        assert out['nucleo'] == [1, True, True, 4.0]

    def test_nothing_when_unmarked(self, out):
        assert out['sinNucleo'] == 0


class TestFixesSeenInTheBrowser:
    def test_the_rack_viewer_takes_the_camera_from_the_address(self, out):
        assert out['rackCamara']

    def test_a_run_is_named_by_rack_name_and_says_one_cable(self, out):
        assert out['tirada'] == ['R1 ↔ R2', True]

    def test_a_floors_core_can_be_clicked(self, out):
        assert out['nucleoPulsable'] is True
