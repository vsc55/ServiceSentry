#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 3D viewer's realistic mode and walking it like a game — a prototype on /3d.

Asked for: «a realistic 3D mode, like in games», with walking in first person and doors that
open. A prototype first, with the viewer's own engine and on /3d only: a second painter for the
same scene (`_viewer3d_real.html`) that the engine hands the frame to when the viewer asks, and
a walk with collisions. What these pin is the arithmetic —materials, doors, what stops a
walker— and that the panel neither loads it nor changes; the picture was looked at in a browser.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run                                  # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


@pytest.fixture(scope='module')
def client():
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    w = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    w._csrf_enabled = False
    w.app.config['TESTING'] = True
    c = w.app.test_client()
    _login(c)
    return c


def _script(html):
    return max(re.findall(r'<script[^>]*>(.*?)</script>', html, re.S), key=len)


class TestWhereItLives:

    def test_only_the_3d_page_loads_it(self, client):
        assert 'function ss3dRealDraw' in client.get('/3d').get_data(as_text=True)
        assert 'function ss3dRealDraw' not in client.get('/admin').get_data(as_text=True)

    def test_the_engine_hands_the_frame_over_only_when_asked(self, client):
        panel = client.get('/admin').get_data(as_text=True)
        assert ("if (V.opts.realista && typeof ss3dRealDraw === 'function' && ss3dRealDraw(V, vp, ojo)) "
                "return;") in panel


_PROBE = r"""
__out = {};
const caja = (x, y, z, w, h, d, extra) => Object.assign({color: [0.5, 0.5, 0.5, 1],
                                                       m: ss3dModel(x, y, z, w, h, d, 0)}, extra || {});
// What each thing is made of.
__out.mat = {
    suelo: ss3dRealMat(caja(0, -0.03, 0, 10, 0.03, 8)),
    muro: ss3dRealMat(caja(0, 0, 0, 10, 3, 0.06, {muro: 'z0'})),
    rack: ss3dRealMat(caja(1, 0, 1, 0.6, 2, 1, {lee: {tipo: 'rack'}})),
    equipo: ss3dRealMat(caja(1, 0, 1, 0.5, 0.1, 0.8, {lee: {tipo: 'item'}})),
    mesa: ss3dRealMat(caja(1, 0, 1, 1.6, 0.75, 0.8, {lee: {tipo: 'feature', fk: 'bench'}})),
    cuadro: ss3dRealMat(caja(1, 0, 1, 0.9, 2, 0.4, {lee: {tipo: 'feature', fk: 'panel'}})),
    cable: ss3dRealMat(caja(1, 1, 1, 0.1, 0.1, 3, {cable: true})),
};
__out.SS3D_MAT = SS3D_MAT;
__out.baldosa = [ss3dRealSkip(caja(0.6, 0, 0, 0.008, 0.001, 8)), ss3dRealSkip(caja(0, -0.03, 0, 10, 0.03, 8))];
// An open rack's glass box is not drawn; a closed one is.
__out.cristal = [ss3dRealHidden(caja(1, 0, 1, 0.6, 2, 1, {lee: {tipo: 'rack', open: true}})),
                 ss3dRealHidden(caja(1, 0, 1, 0.6, 2, 1, {lee: {tipo: 'rack'}}))];
// The sun: the whole 30 x 20 m floor from the orbit; walking, 9 m round the walker, on a 2 m grid.
const planta = {X0: 0, Z0: 0, Y0: 0, W: 30, D: 20, H: 3};
__out.sol = [ss3dRealSunBox(planta, [12.7, 1.6, 5.2], false),
             ss3dRealSunBox(planta, [12.7, 1.6, 5.2], true),
             ss3dRealSunBox({W: 6, D: 4, H: 3}, [1, 1.6, 1], true)];

// A door: on its hinge, a quarter turn, the hinge where it was; and away from who comes.
const puerta = caja(2, 0, 3, 1, 2.1, 0.12, {lee: {tipo: 'feature', fk: 'door', uid: 'p'}});
const bisagra = (m) => [m[12] + m[8] * 0.5, m[14] + m[10] * 0.5];
const abierta = ss3dDoorMatrix(puerta.m, 1, 1);
__out.puerta = {
    esPuerta: ss3dRealIsDoor(puerta),
    bisagraQuieta: bisagra(abierta).map(v => Math.round(v * 1000) / 1000),
    antes: bisagra(puerta.m).map(v => Math.round(v * 1000) / 1000),
    hojaGira: Math.round(Math.hypot(abierta[0], abierta[2]) * 1000) / 1000,
    hojaAhora: [Math.round(abierta[0] * 1000) / 1000, Math.round(abierta[2] * 1000) / 1000],
    cerrada: ss3dDoorMatrix(puerta.m, 0, 1) === puerta.m,
    // Coming from +z, it swings to -z; from -z, to +z.
    lados: [ss3dDoorSide(puerta.m, [2.5, 1.6, 6]), ss3dDoorSide(puerta.m, [2.5, 1.6, 0])],
};

// What stops a walker: a rack yes, a wall yes but not at its door, a zone and the stairs no.
const muro = caja(0, 0, 3, 6, 3, 0.12, {muro: 'z1'});
const solidos = ss3dRealSolids([
    muro, puerta,
    caja(4, 0, 0.5, 0.6, 2, 1, {lee: {tipo: 'rack'}}),
    caja(0, 0.01, 0, 3, 0.02, 2, {lee: {tipo: 'feature', fk: 'zone'}}),
    caja(5, 0, 5, 2, 3, 2, {lee: {tipo: 'core'}}),
    caja(0, 2.7, 0, 6, 0.14, 0.3, {lee: {tipo: 'feature', fk: 'tray'}}),
    caja(0, -0.03, 0, 10, 0.03, 8),
], 0);
const puertas = [{a: [2, 0, 3], b: [3, 2.1, 3.12]}];
// Leaving the walk (Esc): the camera gets a radius back —the walker's 2 cm could not be zoomed
// out of— and walking again carries on where one left off.
globalThis.requestAnimationFrame = () => 1;
globalThis.cancelAnimationFrame = () => {};
let vuelo = null;
ss3dFlyTo = (_V, dest) => { vuelo = dest; };
const VV = {id: 'v', key: 'planta:1', box: null, opts: {}, gl: null,
            cam: {mira: [4, 1.65, 5], radio: 0.02, theta: 1, phi: 1.5}, escena: {cajas: [], W: 10, D: 8}};
_SS3D.set('v', VV);
Object.assign(_SS3D_FPS, {id: 'v', on: true, pos: [4, 1.65, 5], yaw: 0.3, pitch: 0, lock: null, labels: null});
ss3dFpsStop();
__out.salir = {radio: vuelo && vuelo.radio, mira: vuelo && vuelo.mira, on: ss3dFpsOn()};
VV.cam = {mira: [9, 1, 9], radio: 8, theta: 2, phi: 0.95};
ss3dFpsStart('v');
__out.volver = ss3dFpsWhere();
ss3dFpsStop();

// Zoom while walking: the field of view goes to the camera, and the ray that points uses it —
// zoomed, a click must land where the crosshair is, not where it would be unzoomed.
_SS3D_FPS.fov = 0.24;
Object.assign(_SS3D_FPS, {pos: [1, 1.65, 1], yaw: 0, pitch: 0});
const VZ = {id: 'z', cam: {}, gl: null, escena: {cajas: []}, opts: {}, ojo: [1, 1.65, 1],
            cv: {getBoundingClientRect: () => ({left: 0, top: 0, width: 200, height: 100})}};
_ss3dFpsCamera(VZ, false);
const esquina = (fov) => { VZ.cam.fov = fov; return ss3dRay(VZ, 200, 50).d; };
const ancho = esquina(0.96), cerrado = esquina(0.24);
__out.zoom = {fov: _SS3D_FPS.fov, enCamara: 0.24,
              rayoMasCerrado: Math.abs(cerrado[2]) < Math.abs(ancho[2])};
_SS3D_FPS.fov = _SS3D_FOV;

// Without a viewer the walk stops: its frame loop re-armed itself for ever (audit 2026-10-12).
Object.assign(_SS3D_FPS, {id: 'nadie', on: true});
_ss3dFpsStep(0);
__out.sinVisor = ss3dFpsOn();

__out.choques = {
    cuantos: solidos.length,
    rack: ss3dRealBlocked(solidos, puertas, 4.3, 1.0),
    muro: ss3dRealBlocked(solidos, puertas, 0.8, 3.05),
    porLaPuerta: ss3dRealBlocked(solidos, puertas, 2.5, 3.05),
    zona: ss3dRealBlocked(solidos, puertas, 1, 1),
    escalera: ss3dRealBlocked(solidos, puertas, 6, 6),
};
"""


class TestTheArithmetic:

    @pytest.fixture(scope='class')
    def out(self, client):
        if shutil.which('node') is None:
            pytest.skip('no node: nothing to run the script with')
        return node_run(_script(client.get('/3d').get_data(as_text=True)), _PROBE)

    def test_each_thing_has_its_material(self, out):
        M = out['SS3D_MAT']
        assert out['mat'] == {'suelo': M['floor'], 'muro': M['wall'], 'rack': M['rack'],
                              'equipo': M['device'], 'mesa': M['wood'], 'cuadro': M['metal'],
                              'cable': M['gloss']}

    def test_the_tile_lines_give_way_to_the_floors_own(self, out):
        assert out['baldosa'] == [True, False]

    def test_an_open_racks_glass_is_not_a_layer_over_what_it_shows(self, out):
        """Reported from the walk: an open rack looked as if a dotted sheet lay over it — its
        glass box, drawn with the perforated door's material."""
        assert out['cristal'] == [True, False]

    def test_walking_the_sun_looks_at_what_is_round_the_walker(self, out):
        """Reported from the walk: the shadows' edges in steps. A floor's whole 38 m in the map
        from the orbit; walking, 18 m centred on the walker, snapped to 2 m; a small room keeps
        its whole box."""
        todo, andando, sala = out['sol']
        assert todo['r'] > 18 and todo['c'][0] == 15 and todo['c'][2] == 10
        assert andando['r'] == 9 and andando['c'][0] == 12 and andando['c'][2] == 6
        assert sala['r'] < 9 and sala['c'][0] == 3

    def test_a_door_turns_on_its_hinge_and_away_from_who_comes(self, out):
        p = out['puerta']
        assert p['esPuerta'] and p['cerrada']
        assert p['bisagraQuieta'] == p['antes']             # the hinge does not move
        assert p['hojaGira'] == 1.0                         # the leaf, still a metre wide…
        assert p['hojaAhora'][0] == 0.0                     # …now across, not along
        assert p['lados'] == [1, -1]

    def test_leaving_the_walk_gives_the_camera_a_radius_and_walking_again_resumes(self, out):
        """Reported from the screen: after Esc the view could not be zoomed out — the camera kept
        the walker's 2 cm radius, which the wheel multiplies."""
        assert out['salir'] == {'radio': 8, 'mira': [4, 1, 5], 'on': False}
        v = out['volver']
        assert round(v['x'], 3) == 4 and round(v['z'], 3) == 5 and round(v['yaw'], 3) == 0.3

    def test_zoom_narrows_the_view_and_the_pointing(self, out):
        """Asked for: zoom while walking, to see the ports at the back of a server."""
        assert out['zoom'] == {'fov': 0.24, 'enCamara': 0.24, 'rayoMasCerrado': True}

    def test_what_stops_a_walker(self, out):
        c = out['choques']
        assert c['cuantos'] == 2                            # the wall and the rack
        assert c['rack'] and c['muro']
        assert not c['porLaPuerta'] and not c['zona'] and not c['escalera']

    def test_the_walk_stops_without_a_viewer(self, out):
        """Found by the 2026-10-12 audit: with no viewer mounted, the walk's step asked for the
        next frame for ever."""
        assert out['sinVisor'] is False
