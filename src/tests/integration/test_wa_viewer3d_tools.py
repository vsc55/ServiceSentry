#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 3D viewer's improvements, in `node` on the panel's real script.

Asked for: a better floor and building viewer. What these pin, engine first and then the
inventory on top of it:

- the loop draws only when the picture changed, and stops when nothing does;
- the solid boxes are baked into buffers with their corners in place, and the named ones get
  edges;
- the camera flies, the short way round, and the quick views land where they say;
- a ray finds the nearest named box, also a turned one;
- name tags that would overlap, or are far beyond what is looked at, are left out;
- two fingers pinch to zoom;
- rooms are tinted by their worst state, walls can be low, the floors above can be hidden,
  a cabinet's boards answer as the cabinet without repeating its name, and the card says what
  a rack is and opens it.
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

// ── The loop sleeps ─────────────────────────────────────────────────────────────
const marcos = [];
requestAnimationFrame = (f) => { marcos.push(f); return marcos.length; };
let dibujados = 0;
const drawOrig = ss3dDraw;
ss3dDraw = () => { dibujados++; };
const V = {gl: {}, cv: {clientWidth: 800, clientHeight: 400},
           cam: {mira: [0, 0, 0], radio: 10, theta: 1, phi: 1}, escena: {}};
_ss3dWake(V);
let vueltas = 0;
while (marcos.length && vueltas < 200) { const f = marcos.shift(); f(); vueltas++; }
__out.dormido = {dibujados, vueltas, raf: V.raf};
V.cam.theta = 2;
_ss3dWake(V);
while (marcos.length && vueltas < 400) { const f = marcos.shift(); f(); vueltas++; }
__out.despierto = dibujados;
ss3dDraw = drawOrig;

// ── Baked boxes ─────────────────────────────────────────────────────────────────
const caja = (x, nombre) => ({color: [0.5, 0.25, 0.1, 1], m: ss3dModel(x, 0, 0, 2, 1, 1, 0),
                              lee: nombre ? {name: nombre} : null});
const lote = ss3dBatchArrays([caja(0, 'R1'), caja(5, '')]);
__out.lote = {tris: lote.tris.length, cuenta: lote.tris[0].count, lineas: lote.lines[0].count,
              maxX: Math.max(...Array.from(lote.tris[0].pos).filter((_, i) => i % 3 === 0)),
              color: Array.from(lote.tris[0].col.slice(0, 3)).map(v => Math.round(v * 100) / 100),
              borde: Array.from(lote.lines[0].col.slice(0, 3)).map(v => Math.round(v * 1000) / 1000)};
__out.muchos = ss3dBatchArrays(Array.from({length: 3000}, (_, i) => caja(i, ''))).tris.length;

// ── Flying ──────────────────────────────────────────────────────────────────────
const W = {gl: {}, cv: {}, cam: {mira: [0, 0, 0], radio: 10, theta: 6.1, phi: 1}, escena: {W: 10, D: 10}};
ss3dFlyTo(W, {mira: [4, 1, 2], radio: 5, theta: 0.2}, 0);
_ss3dAnimate(W);
__out.vuelo = {mira: W.cam.mira, radio: W.cam.radio, theta: Math.round(W.cam.theta * 1000) / 1000,
               fin: W.anim === null};

// ── A true isometric ────────────────────────────────────────────────────────────
_SS3D.set('isoBox', {gl: {}, cv: {}, cam: {mira: [0, 0, 0], radio: 10, theta: 1, phi: 1},
                     escena: {W: 10, D: 10}});
const ISO = _SS3D.get('isoBox');
ss3dPreset('isoBox', 'iso');
ISO.anim.ms = 0;
_ss3dAnimate(ISO);
__out.iso = {orto: ISO.cam.orto, phi: Math.round(ISO.cam.phi * 10000) / 10000,
             theta: Math.round(ISO.cam.theta * 10000) / 10000};
ISO.ojo = [10, 10, 10];
ISO.cv = {getBoundingClientRect: () => ({left: 0, top: 0, width: 200, height: 100})};
const r1 = ss3dRay(ISO, 20, 20), r2 = ss3dRay(ISO, 180, 80);
__out.isoRayos = {mismaDir: r1.d.every((v, i) => Math.abs(v - r2.d[i]) < 1e-9),
                  otroOrigen: Math.hypot(r1.o[0] - r2.o[0], r1.o[1] - r2.o[1], r1.o[2] - r2.o[2]) > 1};
ss3dPreset('isoBox', 'fit');
__out.isoFuera = ISO.cam.orto;
const om = ss3dOrtho(-2, 2, -1, 1, -10, 10);
__out.orto = [om[0], om[5], om[10], om[15]];
_SS3D.delete('isoBox');

// ── Pointing at a box ───────────────────────────────────────────────────────────
const escena = {cajas: [
    {color: [1, 1, 1, 1], m: ss3dModel(0, 0, 0, 1, 2, 1, 0), lee: {name: 'lejos'}},
    {color: [1, 1, 1, 1], m: ss3dModel(0, 0, 3, 1, 2, 1, 45), lee: {name: 'cerca'}},
    {color: [1, 1, 1, 1], m: ss3dModel(0, 0, 6, 1, 2, 1, 0), lee: null},
]};
const P = {escena};
const rayo = {o: [0.5, 1, 20], d: [0, 0, -1]};
__out.pick = (ss3dPickBox(P, rayo) || {caja: {lee: {}}}).caja.lee.name;
__out.pickNada = ss3dPickBox(P, {o: [50, 1, 20], d: [0, 0, -1]});

// ── Names that do not pile up ───────────────────────────────────────────────────
const elegidos = ss3dLabelsChoose([
    {i: 0, x: 100, y: 100, dist: 5, area: 0},
    {i: 1, x: 110, y: 100, dist: 3, area: 0},     // overlaps 0, nearer: it wins
    {i: 2, x: 400, y: 100, dist: 4, area: 0},
    {i: 3, x: 105, y: 100, dist: 9, area: 1},     // an area name, first of all
    {i: 4, x: 700, y: 300, dist: 500, area: 0},   // far beyond what is looked at
], 10, () => [60, 18]);
__out.rotulos = Array.from(elegidos).sort();

// ── Two fingers ─────────────────────────────────────────────────────────────────
const T = {gl: {}, cam: {mira: [5, 1, 5], radio: 10, theta: 1, phi: 1}, escena: {W: 20, D: 20, H: 3}};
_ss3dTouchDown(T, {pointerId: 1, clientX: 100, clientY: 100});
_ss3dTouchDown(T, {pointerId: 2, clientX: 200, clientY: 100});
_ss3dTouchMove(T, {pointerId: 2, clientX: 300, clientY: 100});
__out.pellizco = Math.round(T.cam.radio * 100) / 100;

// ── The inventory on top ────────────────────────────────────────────────────────
const sala = (o) => _dc3dRoomBoxes({uid: 's1', width_mm: 6000, depth_mm: 5000},
    [{uid: 'k1', name: 'R01', pos_x: 0, pos_y: 0, u_height: 42, used_u: 10, roll: {state: 'ok'}}],
    [{uid: 'a1', kind: 'cabinet', label: 'Armario', pos_x: 3000, pos_y: 3000, width_mm: 1000,
      depth_mm: 500, shelves: 2}],
    {cabinet: {h: 2000, layer: 'room'}}, o);
const normal = sala({}), roja = sala({estado: 'error'}), baja = sala({wallH: 1});
const suelo = (e) => e.cajas[0].color;
__out.tinte = [suelo(normal)[0] < suelo(roja)[0], suelo(normal)[0] === _DC3_COLOR.floor[0]];
const alto = (e) => e.cajas.find(k => k.muro).m[5];
__out.muros = [Math.round(alto(normal) * 10) / 10, alto(baja)];
const rack = normal.cajas.find(k => k.lee && k.lee.tipo === 'rack');
__out.rackLee = [rack.lee.uid, rack.lee.room, rack.lee.u, rack.lee.used];
const tablas = normal.cajas.filter(k => k.lee && k.lee.tipo === 'feature');
__out.armario = [tablas.length > 1, tablas.every(k => k.lee.uid === 'a1'),
                 ss3dLabelsOf(normal).filter(e => e.name === 'Armario').length];
const ficha = _dc3dCardHtml(rack.lee);
__out.ficha = [ficha.includes('R01'), ficha.includes('10 / 42'), ficha.includes("_dcimLoadRack(")];
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


class TestTheLoopSleeps:
    def test_one_drawing_then_it_stops(self, out):
        d = out['dormido']
        assert d['dibujados'] == 1, 'the same picture is drawn once, not sixty times a second'
        assert d['raf'] == 0 and d['vueltas'] < 40

    def test_a_change_wakes_it_and_draws_once_more(self, out):
        assert out['despierto'] == 2


class TestTheBakedBoxes:
    def test_corners_in_place_and_colour_on_every_corner(self, out):
        l = out['lote']
        assert l['tris'] == 1 and l['cuenta'] == 72
        assert abs(l['maxX'] - 7) < 1e-6, 'the second box ends at x = 5 + 2'
        assert l['color'] == [0.5, 0.25, 0.1]

    def test_edges_only_for_the_named_box_and_darker(self, out):
        assert out['lote']['lineas'] == 24
        assert out['lote']['borde'] == pytest.approx([0.225, 0.1125, 0.045], abs=1e-3)

    def test_split_under_the_16_bit_index_limit(self, out):
        assert out['muchos'] == 2


class TestTheCamera:
    def test_it_flies_the_short_way_round(self, out):
        v = out['vuelo']
        assert v['mira'] == [4, 1, 2] and v['radio'] == 5 and v['fin']
        assert abs(v['theta'] - (0.2 + 6.283)) < 0.01, 'from 6.1 to 0.2 is forward a little'

    def test_two_fingers_apart_zoom_in(self, out):
        assert out['pellizco'] == 5


class TestPointingAndNames:
    def test_the_nearest_named_box_also_turned(self, out):
        assert out['pick'] == 'cerca'
        assert out['pickNada'] is None

    def test_names_that_would_overlap_or_are_far_are_left_out(self, out):
        assert out['rotulos'] == [2, 3], 'the area name first; 0 and 1 sit under it; 4 is far'


class TestTheInventoryOnTop:
    def test_a_room_floor_tinted_by_its_worst_state(self, out):
        assert out['tinte'] == [True, True]

    def test_low_walls(self, out):
        assert out['muros'] == [3.0, 1]

    def test_a_rack_says_what_the_card_needs(self, out):
        assert out['rackLee'] == ['k1', 's1', 42, 10]

    def test_a_cabinet_answers_with_every_board_and_names_itself_once(self, out):
        assert out['armario'] == [True, True, 1]

    def test_the_card_names_counts_and_opens(self, out):
        assert out['ficha'] == [True, True, True]


class TestATrueIsometric:
    """Asked from the screen: «Isométrica» and «Encuadrar todo» were 15° apart and looked the
    same; it is now the real one — no perspective, at the isometric angle."""

    def test_no_perspective_at_the_isometric_angle(self, out):
        assert out['iso'] == {'orto': True, 'phi': 0.9553, 'theta': 0.7854}

    def test_every_ray_goes_the_same_way_from_a_different_point(self, out):
        assert out['isoRayos'] == {'mismaDir': True, 'otroOrigen': True}

    def test_the_other_views_go_back_to_perspective(self, out):
        assert out['isoFuera'] is False

    def test_the_projection_matrix(self, out):
        assert out['orto'] == pytest.approx([0.5, 1, -0.1, 1])
