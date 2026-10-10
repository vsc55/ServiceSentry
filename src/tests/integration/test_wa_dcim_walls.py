#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A floor's walls read from its plan — the detection in `node`, the storage through the API.

Asked for: the background plan should give the walls. The panel proposes them from the plan and
somebody reviews them; saved, the floor and the building in 3D raise them. What these pin:

- a thick dark stroke is a wall, with its thickness; a thin one (a dimension line) is not, nor a
  short one (text), nor a solid blob (a filled column);
- horizontal and vertical walls both, and a wall cut by a gap is joined;
- the review snaps to wall ends and squares a nearly straight one;
- in 3D a wall is a slab from floor to ceiling, a door its lintel, a window sill + glass + lintel;
- the API keeps a floor's walls as a whole, refuses a bad segment by number, and deleting the
  floor takes its walls.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login
from tests.helpers import node_run, panel_bundle

_PROBE = r"""
__out = {};
// A white picture with things drawn on it, in black.
const W = 400, H = 300;
const img = {width: W, height: H, data: new Uint8ClampedArray(W * H * 4).fill(255)};
const rect = (x0, y0, w, h, g) => {
    for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) {
        const p = (y * W + x) * 4; img.data[p] = img.data[p + 1] = img.data[p + 2] = g === undefined ? 0 : g;
    }
};
rect(20, 50, 300, 8);        // a horizontal wall, 8 px thick
rect(20, 120, 300, 1);       // a dimension line, 1 px
rect(200, 60, 8, 200);       // a vertical wall
rect(40, 200, 6, 6);         // a dot of text
rect(300, 200, 60, 60);      // a filled column: too thick to be a wall
rect(20, 270, 100, 8);       // a wall cut by a gap…
rect(126, 270, 100, 8);      // …that goes on after it
const tramos = dcwDetect(img, {thresh: 128, minT: 3, maxT: 20, minLen: 40, gap: 10});
const h = tramos.filter(s => s.y1 === s.y2).sort((a, b) => a.y1 - b.y1);
const v = tramos.filter(s => s.x1 === s.x2);
__out.detect = {
    horizontales: h.map(s => [Math.round(s.y1), s.x1, s.x2, s.t]),
    verticales: v.map(s => [Math.round(s.x1), s.y1, s.y2, s.t]),
};
// Otsu finds a grey between paper and ink by itself.
__out.otsu = _dcwOtsu(new Uint8Array([250, 250, 250, 250, 10, 10, 12]));
// From the calibration: millimetres per pixel → what to look for in pixels.
__out.params = _dcwParams(10, {minCm: 6});

// ── A CAD plan: a wall is two thin parallel lines ───────────────────────────────
const lineas = [
    {x1: 0, y1: 100, x2: 400, y2: 100, t: 1}, {x1: 0, y1: 105, x2: 380, y2: 105, t: 1},   // a wall, 5 px
    {x1: 0, y1: 200, x2: 300, y2: 200, t: 1},                                              // alone: a table edge
    {x1: 0, y1: 300, x2: 300, y2: 300, t: 1}, {x1: 0, y1: 340, x2: 300, y2: 340, t: 1},   // 40 px apart: too wide
    {x1: 50, y1: 0, x2: 50, y2: 90, t: 1}, {x1: 56, y1: 10, x2: 56, y2: 90, t: 1},         // a vertical wall
];
__out.parejas = dcwPairs(lineas, 2, 12).map(w => [w.x1, w.y1, w.x2, w.y2, w.t]);
__out.umbralDevuelto = typeof dcwDetect(img, {thresh: 128, minT: 3, maxT: 20, minLen: 40}).umbral === 'number';
const manual = dcwDetect(img, {thresh: 200, minT: 3, maxT: 20, minLen: 40});
__out.otsuAparte = [manual.umbral, manual.otsu !== 200];

// ── Hatching is not a wall ──────────────────────────────────────────────────────
const rayado = Array.from({length: 8}, (_, i) => ({x1: 100 + i * 10, y1: 0, x2: 100 + i * 10, y2: 200, t: 1}));
const muroSolo = {x1: 0, y1: 0, x2: 0, y2: 200, t: 1};
__out.rayado = dcwDropHatching(rayado.concat([muroSolo, {x1: 6, y1: 0, x2: 6, y2: 200, t: 1}]), 30, 4)
    .map(s => s.x1).sort((p, q) => p - q);
// A façade wall right beside a roof's hatching, longer than its strokes, stays.
// …even with the strokes packed tight against it.
const denso = Array.from({length: 12}, (_, i) => ({x1: 92 + i * 2, y1: 0, x2: 92 + i * 2, y2: 200, t: 1}));
__out.fachada = dcwDropHatching(denso.concat([{x1: 90, y1: 0, x2: 90, y2: 600, t: 1}]), 30, 4).map(s => s.x1);

// ── A mixed plan: double-line walls and single thick partitions ─────────────────
__out.mixto = dcwMixed([
    {x1: 0, y1: 100, x2: 400, y2: 100, t: 1}, {x1: 0, y1: 105, x2: 400, y2: 105, t: 2},   // a double wall
    {x1: 0, y1: 200, x2: 300, y2: 200, t: 3},                                              // a partition
    {x1: 0, y1: 300, x2: 300, y2: 300, t: 1},                                              // a lone thin line
], 2, 12, 2).map(w => [w.y1, w.t]);
// The same wall read twice — as a pair and as a loose thick stroke — comes out once.
__out.dobles = dcwMixed([
    {x1: 0, y1: 100, x2: 400, y2: 100, t: 1}, {x1: 0, y1: 105, x2: 400, y2: 105, t: 1},
    {x1: 0, y1: 103, x2: 390, y2: 103, t: 3},
], 2, 12, 2).length;
__out.cambioModo = String(_dcwMode).includes('_dcwDetect()');

// ── Openings cut their wall ─────────────────────────────────────────────────────
__out.huecos = _dcwCut([
    {kind: 'wall', x1: 0, y1: 0, x2: 10000, y2: 0, thick_mm: 200},
    {kind: 'door', x1: 2000, y1: 50, x2: 3000, y2: 50, thick_mm: 200},
    {kind: 'window', x1: 6000, y1: 0, x2: 8000, y2: 0, thick_mm: 200},
    {kind: 'door', x1: 2000, y1: 5000, x2: 3000, y2: 5000, thick_mm: 200},   // elsewhere: cuts nothing
]).filter(w => w.kind === 'wall').map(w => [Math.round(w.x1), Math.round(w.x2)]);

// ── The review: snapping ────────────────────────────────────────────────────────
_dcw = {segs: [{kind: 'wall', x1: 0, y1: 0, x2: 5000, y2: 0, thick_mm: 150}], tool: 'wall', start: null, sel: -1};
__out.snapExtremo = _dcwSnap({x: 5100 * _DCP_SCALE, y: 120 * _DCP_SCALE}, null);
__out.snapEscuadra = _dcwSnap({x: 3000 * _DCP_SCALE, y: 7000 * _DCP_SCALE}, [3100, 0]);
__out.distancia = Math.round(_dcwDist(_dcw.segs[0], 2500, 300));
_dcw = null;

// ── In 3D ───────────────────────────────────────────────────────────────────────
_dcsPlan = {walls: {f1: [{kind: 'wall', x1: 0, y1: 0, x2: 4000, y2: 0, thick_mm: 200},
                         {kind: 'door', x1: 4000, y1: 0, x2: 5000, y2: 0, thick_mm: 200},
                         {kind: 'window', x1: 5000, y1: 0, x2: 6000, y2: 0, thick_mm: 200}]}};
const cajas = [];
_dcwBoxes({uid: 'f1'}, cajas, 3);
const alto = (k) => Math.round(k.m[5] * 100) / 100, base = (k) => Math.round(k.m[13] * 100) / 100;
__out.tresd = cajas.map(k => [base(k), alto(k), k.color[3] < 1]);
const muro = cajas[0].m;
__out.largo = Math.round(Math.hypot(muro[0], muro[1], muro[2]) * 1000) / 1000;
__out.grueso = Math.round(Math.hypot(muro[8], muro[9], muro[10]) * 1000) / 1000;
"""


@pytest.fixture(scope='module')
def out():
    if shutil.which('node') is None:
        pytest.skip('no node: nothing to run the script with')
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


class TestReadingThePlan:
    def test_a_thick_stroke_is_a_wall_a_thin_or_short_or_solid_one_is_not(self, out):
        hs = out['detect']['horizontales']
        assert [54, 20, 320, 8] in [[round(y), a, b, t] for y, a, b, t in hs], hs
        assert not any(round(y) == 120 for y, *_ in hs), 'a 1 px dimension line'
        assert not any(t > 20 for *_, t in hs), 'a filled column'

    def test_vertical_walls_too(self, out):
        assert [204, 60, 260, 8] in out['detect']['verticales']

    def test_a_wall_cut_by_a_gap_is_joined(self, out):
        assert [274, 20, 226, 8] in out['detect']['horizontales']

    def test_otsu_finds_the_ink(self, out):
        assert 12 <= out['otsu'] < 250

    def test_what_to_look_for_comes_from_the_scale(self, out):
        p = out['params']
        assert p['minT'] == 6 and p['maxT'] == 70 and p['minLen'] == 60


class TestTheReview:
    def test_snaps_to_a_nearby_end_and_squares_a_near_straight_wall(self, out):
        assert out['snapExtremo'] == [5000, 0]
        assert out['snapEscuadra'] == [3100, 7000]
        assert out['distancia'] == 300


class TestIn3D:
    def test_wall_door_lintel_window_sill_glass_lintel(self, out):
        assert out['tresd'] == [[0, 3, False], [2.1, 0.9, False],
                                [0, 0.9, False], [0.9, 1.2, True], [2.1, 0.9, False]]

    def test_as_long_and_thick_as_drawn(self, out):
        assert out['largo'] == 4 and out['grueso'] == 0.2


class TestTheApi:
    def _floor(self, c):
        site = c.post('/api/v1/dcim/sites', json={'name': 'Muros'}).get_json()['uid']
        return site, c.post('/api/v1/dcim/floors', json={'site_uid': site, 'name': 'P0', 'level': 0}).get_json()['uid']

    def test_saved_as_a_whole_and_served_with_the_site(self, admin, client):
        _login(client)
        site, floor = self._floor(client)
        tramos = [{'kind': 'wall', 'x1': 0, 'y1': 0, 'x2': 5000, 'y2': 0, 'thick_mm': 200},
                  {'kind': 'door', 'x1': 5000, 'y1': 0, 'x2': 6000, 'y2': 0}]
        r = client.put(f'/api/v1/dcim/floors/{floor}/walls', json={'walls': tramos})
        assert r.status_code == 200 and r.get_json()['walls'] == 2
        assert len(client.get(f'/api/v1/dcim/floors/{floor}/walls').get_json()['walls']) == 2
        client.put(f'/api/v1/dcim/floors/{floor}/walls', json={'walls': tramos[:1]})
        walls = client.get(f'/api/v1/dcim/sites/{site}/contents').get_json()['walls'][floor]
        assert [w['kind'] for w in walls] == ['wall'], 'the second save replaces the first'

    def test_a_bad_segment_is_refused_by_number(self, admin, client):
        _login(client)
        _site, floor = self._floor(client)
        for malo in ({'kind': 'tobogan', 'x1': 0, 'y1': 0, 'x2': 1000, 'y2': 0},
                     {'kind': 'wall', 'x1': 0, 'y1': 0, 'x2': 0, 'y2': 0},
                     {'kind': 'wall', 'x1': 'a', 'y1': 0, 'x2': 1000, 'y2': 0},
                     {'kind': 'wall', 'x1': 0, 'y1': 0, 'x2': 1000, 'y2': 0, 'thick_mm': 99999}):
            r = client.put(f'/api/v1/dcim/floors/{floor}/walls',
                           json={'walls': [{'kind': 'wall', 'x1': 0, 'y1': 0, 'x2': 1000, 'y2': 0}, malo]})
            assert r.status_code == 400 and '2' in r.get_json()['error'], malo

    def test_deleting_the_floor_takes_its_walls(self, admin, client):
        _login(client)
        _site, floor = self._floor(client)
        client.put(f'/api/v1/dcim/floors/{floor}/walls',
                   json={'walls': [{'kind': 'wall', 'x1': 0, 'y1': 0, 'x2': 1000, 'y2': 0}]})
        assert client.delete(f'/api/v1/dcim/floors/{floor}').status_code == 200
        assert admin._dcim_store.walls_of(floor) == []
        assert client.get(f'/api/v1/dcim/floors/{floor}/walls').status_code == 404

    def test_editing_needs_permission(self, admin):
        anon = admin.app.test_client()
        assert anon.put('/api/v1/dcim/floors/x/walls', json={'walls': []}).status_code in (302, 401, 403)


class TestADoubleLinePlan:
    """Seen with a real CAD plan: walls are two thin parallel lines, and reading strokes took
    every straight line — hatching, furniture, text — for a wall, and each wall twice."""

    def test_two_close_parallel_lines_are_one_wall_with_its_real_thickness(self, out):
        assert [0, 102.5, 400, 102.5, 6] in out['parejas']
        assert [53, 0, 53, 90, 7] in out['parejas']

    def test_a_line_alone_or_a_pair_too_far_apart_is_not_a_wall(self, out):
        assert len(out['parejas']) == 2

    def test_the_threshold_used_comes_back(self, out):
        assert out['umbralDevuelto']


class TestOpeningsCutTheirWall:
    def test_a_door_or_window_on_a_wall_opens_it_and_one_elsewhere_does_not(self, out):
        assert out['huecos'] == [[0, 2000], [3000, 6000], [8000, 10000]]


class TestARealPlanSecondPass:
    """Seen with a real plan a second time: half of what CAD mode proposed was hatching and
    stairs, the interior partitions (one thick stroke) were all missed, and «auto» showed the
    last manual value."""

    def test_hatching_and_stairs_are_dropped(self, out):
        assert out['rayado'] == [0, 6], 'eight evenly spaced parallels go; a wall and its face stay'

    def test_but_a_longer_wall_beside_the_hatching_stays(self, out):
        assert out['fachada'] == [90]

    def test_mixed_takes_double_walls_and_thick_partitions_not_thin_lines(self, out):
        assert out['mixto'] == [[102.5, 6.5], [200, 3]]

    def test_a_wall_read_twice_comes_out_once(self, out):
        assert out['dobles'] == 1

    def test_changing_mode_reads_the_plan_again(self, out):
        assert out['cambioModo']

    def test_the_automatic_threshold_is_reported_apart_from_the_one_used(self, out):
        assert out['otsuAparte'] == [200, True]
