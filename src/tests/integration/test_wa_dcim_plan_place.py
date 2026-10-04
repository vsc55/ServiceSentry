"""Dragging a piece on the room plan brings what you SEE to the wall, whatever its turn.

`pos_x`/`pos_y` are the corner of the unturned box, and the turn is about its centre. The drag
clamped that corner at zero, so a door turned a quarter — 1000 × 120, drawn 440 mm to the right
of its corner — stopped 44 cm short of the wall, with the magnet on or off. A door is the piece
that goes ON the wall. Reported from the screen.

Run in `node` against the bundle the panel actually serves, because the fault was arithmetic:
reading the source says a clamp is there, and only the numbers say where it stops.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='sin node: no hay con qué ejecutar el guion')

# A 6 × 5 m room with 600 mm tiles. Each case drags from well inside the room to far past the
# top-left corner, and reports where the VISIBLE box ends up — which is what the person placing
# the piece is looking at.
_PRUEBA = r"""
__out = {};
_dcimPlan = {room: {tile_mm: 600, width_mm: 6000, depth_mm: 5000}};
const casos = {};
function visible(at, w, d, rot) {
    const o = _dcpEdgeOffset(w, d, rot);
    return {x: at.x + o.x, y: at.y + o.y};
}
for (const iman of [true, false]) {
    _dcpMagnet = iman;
    for (const rot of [0, 90, 180, 270, 45]) {
        const p = _dcpPlace({x: 2150, y: 2800}, -9000, -9000, 1000, 120, rot);
        casos[(iman ? 'iman' : 'libre') + rot] = {esquina: p, visto: visible(p, 1000, 120, rot)};
    }
}
// Unturned, the arithmetic must be the one it always was: nothing moves for anyone who never
// turned a piece.
_dcpMagnet = true;
casos.recto = _dcpPlace({x: 1200, y: 600}, 610, 590, 600, 1000, 0);
// And a turned piece dragged a little, with the magnet, lines its VISIBLE edge up with a tile.
casos.baldosa = visible(_dcpPlace({x: 2150, y: 2800}, 100, 0, 1000, 120, 90), 1000, 120, 90);
// Resizing: the side or corner OPPOSITE the handle stays where it is seen, whatever the turn.
function punto(x, y, w, d, rot, sx, sy) {
    const r = rot * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
    const lx = sx * w / 2, ly = sy * d / 2;
    return [Math.round(x + w / 2 + lx * c - ly * s), Math.round(y + d / 2 + lx * s + ly * c)];
}
_dcpMagnet = false;
casos.estirar = {};
for (const rot of [0, 90, 180, 270, 30]) {
    for (const asa of ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']) {
        const gx = asa.includes('e') ? 1 : (asa.includes('w') ? -1 : 0);
        const gy = asa.includes('s') ? 1 : (asa.includes('n') ? -1 : 0);
        const n = _dcpResize({handle: asa, w0: 1000, d0: 600, rot, at: {x: 2000, y: 2000}},
                             200, 150);
        casos.estirar[asa + rot] = {
            w: n.width_mm, d: n.depth_mm,
            antes: punto(2000, 2000, 1000, 600, rot, -gx, -gy),
            despues: punto(n.pos_x, n.pos_y, n.width_mm, n.depth_mm, rot, -gx, -gy)};
    }
}
casos.minimo = _dcpResize({handle: 'se', w0: 600, d0: 600, rot: 0, at: {x: 0, y: 0}},
                          -5000, -5000);
// The 3D view: the box a piece occupies in 3D is the one it occupies on the plan, turned the same
// way. `m` is column-major; a unit-cube corner (u, t) lands at x = m0 u + m8 t + m12, z = m2 u +
// m10 t + m14 (metres).
function esquina3d(m, u, t) {
    return [Math.round((m[0] * u + m[8] * t + m[12]) * 1000),
            Math.round((m[2] * u + m[10] * t + m[14]) * 1000)];
}
function esquinaPlano(x, y, w, d, rot, u, t) {
    const r = rot * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
    const lx = u * w - w / 2, ly = t * d - d / 2;
    return [Math.round(x + w / 2 + lx * c - ly * s), Math.round(y + d / 2 + lx * s + ly * c)];
}
casos.tresd = {};
for (const rot of [0, 30, 90, 180, 270]) {
    const m = _dc3model(-0.44, 0, 2.0, 1.0, 2.1, 0.12, rot);
    casos.tresd[rot] = [[1, 0], [0, 1], [1, 1]].map(([u, t]) => ({
        tres: esquina3d(m, u, t), plano: esquinaPlano(-440, 2000, 1000, 120, rot, u, t)}));
}
// And a rack's front strip is on the side the plan paints its front: the `pos_y` side, turned
// with the rack about the RACK's centre.
_dcimPlan = {room: {width_mm: 6000, depth_mm: 5000, tile_mm: 600},
             racks: [{uid: 'r0', pos_x: 1000, pos_y: 1000, width_mm: 600, depth_mm: 1000,
                      u_height: 42, rotation: 0, roll: {}},
                     {uid: 'r9', pos_x: 3000, pos_y: 1000, width_mm: 600, depth_mm: 1000,
                      u_height: 42, rotation: 90, roll: {}}]};
_dcpFeat = {features: [], kinds: {}, layers: ['floor', 'room', 'air']};
const escena = _dc3dScene();
function caja3d(m) {
    const xs = [], zs = [];
    for (const u of [0, 1]) for (const t of [0, 1]) {
        const p = esquina3d(m, u, t); xs.push(p[0]); zs.push(p[1]);
    }
    return {x0: Math.min(...xs), x1: Math.max(...xs), z0: Math.min(...zs), z1: Math.max(...zs)};
}
const conNombre = escena.cajas.filter(k => k.lee);
const franjas = escena.cajas.filter(k => !k.lee && k.color !== _DC3_COLOR.floor
                                        && k.color !== _DC3_COLOR.wallroom
                                        && k.color !== _DC3_COLOR.tile);
casos.franja = {rack0: caja3d(conNombre[0].m), franja0: caja3d(franjas[0].m),
                rack90: caja3d(conNombre[1].m), franja90: caja3d(franjas[1].m)};
// Moving about the room in 3D: the camera lives in `_dc3d.cam`, and the handlers only need an
// event with the fields they read.
const escena3 = {W: 6, D: 5, H: 3};
_dc3d = {cam: _dc3dCamHome(escena3), escena: escena3};
const ev = (extra) => Object.assign({preventDefault() {}, shiftKey: false}, extra);
const mira0 = _dc3d.cam.mira.slice();
for (let i = 0; i < 60; i++) _dc3dWheel(ev({deltaY: -1}));
casos.rueda = {radio: _dc3d.cam.radio, antes: mira0, despues: _dc3d.cam.mira.slice()};
for (let i = 0; i < 400; i++) _dc3dWheel(ev({deltaY: -1, shiftKey: true}));
casos.ruedaSinFin = _dc3d.cam.mira.slice();
_dc3d.cam = _dc3dCamHome(escena3);
const w0 = _dc3d.cam.mira.slice(), e = _dc3dAxes(_dc3d.cam);
_dc3dKey(ev({key: 'w'}));
const w1 = _dc3d.cam.mira.slice();
_dc3dKey(ev({key: 'e'}));
const e1 = _dc3d.cam.mira.slice();
for (let i = 0; i < 100; i++) _dc3dKey(ev({key: 'q'}));
const suelo = _dc3d.cam.mira[1];
_dc3dKey(ev({key: 'Home'}));
casos.teclas = {avance: [w1[0] - w0[0], w1[2] - w0[2]], fwd: [e.fwd[0], e.fwd[2]],
                sube: e1[1] - w1[1], suelo, casa: _dc3d.cam.mira};
// Looking from below: dragging down far enough takes the camera past the horizontal.
_dc3d.cam = _dc3dCamHome(escena3);
_dc3d.arrastre = {x: 0, y: 0, pan: false};
_dc3dMove({clientX: 0, clientY: -2000});
casos.desdeAbajo = _dc3d.cam.phi;
// The walls: all four, and the one between the camera and the room turns to glass.
const sala = {W: 6, D: 5, H: 3};
casos.muros = {
    lados: _dc3dScene().cajas.filter(k => k.muro).map(k => k.muro).sort(),
    dentro: ['z0', 'x0', 'z1', 'x1'].map(l => _dc3dWallAlpha(l, [3, 1.5, 2.5], sala)),
    detrasDelFondo: _dc3dWallAlpha('z0', [3, 1.5, -1], sala),
    delanteDerecha: ['z0', 'x0', 'z1', 'x1'].map(l => _dc3dWallAlpha(l, [9, 4, 8], sala)),
};
// Typing several fields in a row saves ALL of them: the second must not cancel the first.
const enviados = [];
_dcimSend = async (metodo, url, cuerpo) => { enviados.push({url, cuerpo}); return {ok: true}; };
_dcpQueue('/api/v1/dcim/racks/r1', {base_mm: 1500});
_dcpQueue('/api/v1/dcim/racks/r1', {name: 'Pared'});
_dcpFlush();
_dcpQueue('/api/v1/dcim/racks/r1', {u_height: 12});
_dcpQueue('/api/v1/dcim/features/f1', {pos_x: 600});
_dcpFlush();
casos.cola = enviados;
// The front view: a wall rack hung at 1.6 m against the north wall, and a door on the west
// wall, turned 270° with its stored corner at -440 mm.
_dcimPlan = {room: {width_mm: 6000, depth_mm: 5000, tile_mm: 600},
             racks: [{uid: 'rp', name: 'Pared', pos_x: 600, pos_y: 0, width_mm: 600,
                      depth_mm: 1000, rotation: 0, u_height: 42, base_mm: 1600, roll: {}}]};
_dcpFeat = {features: [{uid: 'pu', kind: 'door', pos_x: -440, pos_y: 4040, width_mm: 1000,
                        depth_mm: 120, rotation: 270}],
            kinds: {door: {w: 1000, d: 120, h: 2100, layer: 'room'}},
            layers: ['floor', 'room', 'air']};
const redondo = (it) => ({uid: it.uid, u0: Math.round(it.u0), u1: Math.round(it.u1),
                          y0: Math.round(it.y0), y1: Math.round(it.y1), dist: Math.round(it.dist)});
casos.alzado = {};
for (const lado of ['N', 'E', 'S', 'W']) casos.alzado[lado] = _dcpElevationItems(lado).map(redondo);
casos.alturaSala = Math.round(_dcpElevationH());
// Dragging in the front view: along the wall, with the viewer's sign, and a rack up and down.
_dcpMagnet = false;
const arr = (side) => ({side, w: 600, d: 1000, rot: 0, base: 1600, at: {x: 1200, y: 1000}});
casos.frente = {
    N: _dcpElevApply(arr('N'), 300, 0), S: _dcpElevApply(arr('S'), 300, 0),
    E: _dcpElevApply(arr('E'), 300, 0), W: _dcpElevApply(arr('W'), 300, 0),
    sube: _dcpElevApply(arr('N'), 0, 520), suelo: _dcpElevApply(arr('N'), 0, -9000),
    pieza: _dcpElevApply({side: 'N', w: 1000, d: 120, rot: 0, base: 0, at: {x: 1200, y: 0}}, 0, 900),
    piezaAlta: _dcpElevResize({side: 'N', handle: 'et', kind: 'feature', h0: 750, rot: 0,
                               w0: 1600, d0: 800, at: {x: 0, y: 0}}, 0, 480),
    piezaMin: _dcpElevResize({side: 'N', handle: 'et', kind: 'feature', h0: 750, rot: 0,
                              w0: 1600, d0: 800, at: {x: 0, y: 0}}, 0, -9000),
};
// A piece's own height and base, or its kind's when it has none.
_dcpFeat = {features: [], kinds: {bench: {h: 750}, tray: {h: 140, base: 2720}},
            layers: ['floor', 'room', 'air']};
casos.pieceZ = {
    tipo: _dcpPieceZ({kind: 'tray', height_mm: null, base_mm: null}),
    propia: _dcpPieceZ({kind: 'bench', height_mm: 1100, base_mm: 200}),
    enElSuelo: _dcpPieceZ({kind: 'tray', height_mm: null, base_mm: 0}),
};
// Resizing from the front: the side facing the viewer's right or left, and a rack's U.
const est = (side, handle, rot) => ({side, handle, rot, kind: 'rack', w0: 1000, d0: 600, u0: 42,
                                     at: {x: 2000, y: 2000}});
casos.estFrente = {
    N_er: _dcpElevResize(est('N', 'er', 0), 300, 0),
    N_el: _dcpElevResize(est('N', 'el', 0), -300, 0),
    E_er: _dcpElevResize(est('E', 'er', 0), 300, 0),
    E_er90: _dcpElevResize(est('E', 'er', 90), 300, 0),
    diagonal: _dcpElevResize(est('N', 'er', 45), 300, 0),
    u: _dcpElevResize(est('N', 'et', 0), 0, 44.45 * 6),
    uMin: _dcpElevResize(est('N', 'et', 0), 0, -9000),
};
// A room stretched on a building's plan snaps to 10 cm, not to a room's 600 mm tile.
_dcpMagnet = true;
casos.salaEstirada = _dcpResize({handle: 'se', w0: 4000, d0: 3000, rot: 0, at: {x: 1000, y: 1000}},
                                1234, 567, _dcsSnap);
casos.planoSinAncho = [_dcsPlanBox().w];
// A point on the floor, in the coordinates of a room turned a quarter: what places a rack INSIDE
// a turned room where it was dropped.
const girada = {pos_x: 10000, pos_y: 5000, width_mm: 6000, depth_mm: 4000, rotation: 90};
casos.local = {
    centro: _dcsToLocal(girada, 13000, 7000),
    esquina: _dcsToLocal(girada, 15000, 4000),
    zona: _dcsToLocal({pos_x: 0, pos_y: 0, width_mm: 0, depth_mm: 0, rotation: 0}, 9000, 4000),
};
__out.casos = JSON.stringify(casos);
"""


@pytest.fixture(scope='module')
def casos():
    import json                                                      # noqa: PLC0415
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
    return json.loads(node_run(panel_bundle(c), _PRUEBA)['casos'])


class TestUnaPiezaGiradaLlegaALaPared:

    @pytest.mark.parametrize('iman', ['iman', 'libre'])
    @pytest.mark.parametrize('giro', [0, 90, 180, 270, 45])
    def test_lo_que_se_ve_toca_la_pared(self, casos, iman, giro):
        """Con el imán y sin él, y con cualquier giro: el borde que se VE queda en cero."""
        visto = casos['%s%d' % (iman, giro)]['visto']
        assert visto == {'x': 0, 'y': 0}, (
            'girada %d°, la pieza se queda a %s mm de la pared' % (giro, visto))

    def test_girada_un_cuarto_la_esquina_guardada_es_negativa(self, casos):
        """Es lo que la deja en la pared: la esquina sin girar queda fuera de la sala, y el
        dibujo, que gira sobre el centro, cae justo dentro. Un tope en `pos_x ≥ 0` lo impedía."""
        assert casos['iman90']['esquina'] == {'x': -440, 'y': 440}

    def test_sin_girar_se_mueve_como_siempre(self, casos):
        """Quien nunca giró una pieza no nota nada: la cuenta es la de antes."""
        assert casos['recto'] == {'x': 1800, 'y': 1200}

    def test_el_iman_alinea_lo_que_se_ve(self, casos):
        """Alinear la esquina invisible dejaba el borde visible 440 mm fuera de la baldosa."""
        assert casos['baldosa']['x'] % 600 == 0, casos['baldosa']


class TestUnaPiezaSeEstiraDesdeSusAsas:

    @pytest.mark.parametrize('giro', [0, 90, 180, 270, 30])
    @pytest.mark.parametrize('asa', ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'])
    def test_lo_opuesto_al_asa_no_se_mueve(self, casos, asa, giro):
        """El giro va sobre el centro y el centro se mueve al cambiar el tamaño: sin corregir la
        esquina guardada, una pieza girada resbalaría de lado mientras se estira. Con un grado
        de margen: a 30° la posición se guarda redondeada al milímetro."""
        c = casos['estirar']['%s%d' % (asa, giro)]
        assert all(abs(x - y) <= 1 for x, y in zip(c['antes'], c['despues'])), c

    def test_sin_girar_cada_asa_estira_lo_suyo(self, casos):
        """Arrastrando 200 a la derecha y 150 hacia abajo: lo que tira hacia fuera crece, lo que
        tira hacia dentro encoge, y lo que no toca un eje no lo cambia. A pasos de 50 mm."""
        e = casos['estirar']
        esperado = {'n': (1000, 450), 's': (1000, 750), 'e': (1200, 600), 'w': (800, 600),
                    'ne': (1200, 450), 'nw': (800, 450), 'se': (1200, 750), 'sw': (800, 750)}
        for asa, medida in esperado.items():
            assert (e[asa + '0']['w'], e[asa + '0']['d']) == medida, asa

    def test_girada_un_cuarto_estira_lo_que_esta_bajo_la_mano(self, casos):
        """Girada 90°, el ancho de la pieza apunta hacia abajo en la pantalla: tirar del asa
        del ancho hacia abajo lo alarga, en vez de cambiar el fondo."""
        assert casos['estirar']['e90']['w'] == 1150

    def test_nunca_por_debajo_de_cinco_centimetros(self, casos):
        """Una pieza de tamaño cero no hay quien la vuelva a coger."""
        assert (casos['minimo']['width_mm'], casos['minimo']['depth_mm']) == (50, 50)


class TestEl3dEsElMismoPlano:
    """La vista 3D giraba cada caja sobre su esquina y en sentido contrario al plano, que gira
    sobre el centro. Con una puerta pegada a la pared —esquina guardada en -440 mm— eso la
    despegaba 44 cm de la pared en 3D. Reportado desde la pantalla, con captura."""

    @pytest.mark.parametrize('giro', [0, 30, 90, 180, 270])
    def test_cada_esquina_cae_donde_en_planta(self, casos, giro):
        """Esquina por esquina y no solo la huella: una caja girada al revés ocupa la misma
        huella a 90° y a 180°, y solo las esquinas dicen hacia dónde mira."""
        for p in casos['tresd'][str(giro)]:
            assert all(abs(a - b) <= 1 for a, b in zip(p['tres'], p['plano'])), p

    def test_la_franja_del_frente_esta_donde_la_pinta_el_plano(self, casos):
        """El plano pinta el frente en el lado de `pos_y`; el 3D lo ponía en el de atrás, y los
        dos decían cosas contrarias sobre hacia dónde sopla el rack."""
        f = casos['franja']
        assert f['franja0']['z1'] <= f['rack0']['z0'] + 1, f
        assert f['rack0']['x0'] <= f['franja0']['x0'] and f['franja0']['x1'] <= f['rack0']['x1']

    def test_y_gira_con_el_rack(self, casos):
        """Girado un cuarto en planta (en el sentido de las agujas del reloj), el frente queda a
        la derecha: la franja pegada al lado derecho del rack, no flotando donde estaría si
        girase sobre su propio centro."""
        f = casos['franja']
        assert f['franja90']['x0'] >= f['rack90']['x1'] - 1, f
        assert f['rack90']['z0'] <= f['franja90']['z0'] and f['franja90']['z1'] <= f['rack90']['z1']


class TestPorLaSalaSePuedeAndar:
    """La cámara solo orbitaba alrededor de un punto fijo a un metro del suelo: la rueda se paraba
    a 1,2 m y la vista no bajaba de la horizontal. No se llegaba a la pared del fondo ni había
    forma de ponerse bajo un rack de pared. Reportado desde la pantalla, con captura."""

    def test_la_rueda_llega_al_minimo_y_sigue_hacia_dentro(self, casos):
        r = casos['rueda']
        assert r['radio'] == 0.5, 'la rueda sigue parándose antes de llegar'
        movido = sum(abs(a - b) for a, b in zip(r['antes'], r['despues']))
        assert movido > 1.0, 'al llegar al mínimo la rueda no avanza: no se atraviesa la sala'

    def test_y_ni_se_hunde_ni_se_sale_de_la_sala(self, casos):
        """Siguiendo la mirada, que casi siempre va hacia abajo, la rueda hundía la cámara en el
        suelo; y sin tope atravesaba la sala y seguía hacia el vacío de detrás del muro. Anda en
        horizontal, y hasta los muros de la sala (6 × 5 m), con 30 cm de holgura."""
        x, y, z = casos['ruedaSinFin']
        assert abs(y - casos['rueda']['antes'][1]) < 1e-9, 'la rueda cambia la altura'
        assert -0.3 <= x <= 6.3 and -0.3 <= z <= 5.3, casos['ruedaSinFin']

    def test_w_anda_hacia_donde_se_mira(self, casos):
        t = casos['teclas']
        assert t['avance'][0] * t['fwd'][0] + t['avance'][1] * t['fwd'][1] > 0, t

    def test_e_sube_y_q_no_atraviesa_el_suelo(self, casos):
        t = casos['teclas']
        assert t['sube'] > 0, 'E no sube'
        assert t['suelo'] >= 0.05, 'bajando se atraviesa el suelo'

    def test_inicio_vuelve_a_la_vista_de_partida(self, casos):
        assert casos['teclas']['casa'] == [3, 1, 2.5]

    def test_se_puede_mirar_desde_abajo(self, casos):
        """Por encima de la horizontal (π/2) es mirar desde abajo: como se ve un rack colgado."""
        assert 1.5708 < casos['desdeAbajo'] < 3.1416, casos['desdeAbajo']


class TestUnMuroNoTapaLaSala:
    """Solo se dibujaban los dos muros del fondo, y cruzar uno dejaba la pantalla en gris: se
    miraba la sala a través de su muro, por detrás. Reportado desde la pantalla."""

    def test_estan_los_cuatro(self, casos):
        assert casos['muros']['lados'] == ['x0', 'x1', 'z0', 'z1']

    def test_desde_dentro_son_macizos(self, casos):
        assert casos['muros']['dentro'] == [1, 1, 1, 1]

    def test_el_que_se_interpone_es_de_cristal(self, casos):
        """Cruzado el muro del fondo, ese muro deja ver la sala."""
        assert casos['muros']['detrasDelFondo'] < 0.5

    def test_y_desde_la_vista_de_partida_solo_los_de_delante(self, casos):
        """La cámara empieza delante a la derecha: esos dos, de cristal; el fondo, macizo, que
        es contra lo que se lee la sala."""
        z0, x0, z1, x1 = casos['muros']['delanteDerecha']
        assert (z0, x0) == (1, 1) and z1 < 0.5 and x1 < 0.5


class TestLoTecleadoSeGuardaEntero:
    """Con un temporizador por petición, escribir la altura de un rack y enseguida su nombre
    guardaba el nombre y nada más: el segundo campo cancelaba el primero, sin aviso. Encontrado al
    probar el inspector del rack; las piezas tenían el mismo fallo con X e Y."""

    def test_dos_campos_seguidos_salen_juntos(self, casos):
        assert casos['cola'][0] == {'url': '/api/v1/dcim/racks/r1',
                                    'cuerpo': {'base_mm': 1500, 'name': 'Pared'}}

    def test_cambiar_de_cosa_manda_antes_lo_de_la_anterior(self, casos):
        """Esperar a que se pare de teclear en la segunda para guardar la primera es perderla si
        se cierra la pantalla antes."""
        assert [c['url'] for c in casos['cola'][1:]] == ['/api/v1/dcim/racks/r1',
                                                         '/api/v1/dcim/features/f1']
        assert casos['cola'][1]['cuerpo'] == {'u_height': 12}


class TestLaSalaDeFrente:
    """En planta no se ve la altura de nada, y un rack colgado tapa lo que haya debajo. Se pidió
    poder mirar cada pared de frente y girar de una a otra. Una sala de 6 × 5 m con un rack
    colgado a 1,6 m en la pared norte y una puerta en la oeste."""

    def _uno(self, casos, lado, uid):
        return [i for i in casos['alzado'][lado] if i['uid'] == uid][0]

    def test_el_rack_de_pared_sale_a_su_altura(self, casos):
        r = self._uno(casos, 'N', 'rp')
        assert (r['u0'], r['u1'], r['dist']) == (600, 1200, 0)
        assert (r['y0'], r['y1']) == (1600, 3467), '42U desde 1,6 m'

    @pytest.mark.parametrize('lado,esperado', [('S', (4800, 5400, 4000)),
                                               ('E', (0, 1000, 4800)),
                                               ('W', (4000, 5000, 600))])
    def test_y_desde_cada_pared_cae_donde_debe(self, casos, lado, esperado):
        """Medido desde el rincón de la izquierda de quien mira hacia esa pared desde dentro:
        mirando al sur, la izquierda es el este, y el rack sale a la derecha."""
        r = self._uno(casos, lado, 'rp')
        assert (r['u0'], r['u1'], r['dist']) == esperado, r

    def test_la_puerta_girada_esta_en_su_pared(self, casos):
        """Girada 270° con la esquina guardada en -440 mm: pegada a la pared oeste, y de frente
        mide lo que mide una puerta."""
        p = self._uno(casos, 'W', 'pu')
        assert p['dist'] == 0 and (p['u1'] - p['u0']) == 1000 and (p['y0'], p['y1']) == (0, 2100)

    def test_lo_pegado_a_la_pared_va_primero(self, casos):
        """Lo que se pinta después queda encima: lo de en medio de la sala, más tenue, encima de
        lo que cuelga del muro, y no al revés."""
        dists = [i['dist'] for i in casos['alzado']['N']]
        assert dists == sorted(dists)

    def test_la_sala_crece_si_algo_pasa_del_techo(self, casos):
        """Un rack colgado que llega a 3,47 m no se dibuja cortado a 3 m."""
        assert casos['alturaSala'] == 3467


class TestDeFrenteSeMueve:
    """Se pidió poder mover las cosas en la vista de frente. A lo largo de la pared y, un rack,
    también arriba y abajo; la distancia a la pared, que desde aquí no se ve, no se toca."""

    @pytest.mark.parametrize('lado,esperado', [('N', (1500, 1000)), ('S', (900, 1000)),
                                               ('E', (1200, 1300)), ('W', (1200, 700))])
    def test_a_la_derecha_de_quien_mira(self, casos, lado, esperado):
        """De frente al norte la derecha es el este (+x); al sur, el oeste (-x); al este, el sur
        (+y); al oeste, el norte (-y). Y el otro eje, quieto."""
        f = casos['frente'][lado]
        assert (f['pos_x'], f['pos_y']) == esperado, f

    def test_un_rack_sube_a_pasos_de_cinco_centimetros(self, casos):
        assert casos['frente']['sube']['base_mm'] == 2100     # 1600 + 520 → 2100

    def test_y_no_baja_del_suelo(self, casos):
        assert casos['frente']['suelo']['base_mm'] == 0

    def test_una_pieza_tambien_sube(self, casos):
        """Desde que cada pieza guarda su propia altura desde el suelo (`base_mm`)."""
        assert casos['frente']['pieza']['base_mm'] == 900

    def test_y_se_hace_mas_alta_a_pasos_de_cinco_centimetros(self, casos):
        """Una mesa de 750 estirada 480 hacia arriba: 1230, que se guarda como 1250."""
        assert casos['frente']['piezaAlta'] == {'height_mm': 1250}
        assert casos['frente']['piezaMin'] == {'height_mm': 50}


class TestCadaPiezaSuAltura:
    """Estirar una mesa hacia arriba no tenía dónde guardarse: toda pieza medía lo que su tipo.
    Vacío es «lo de su tipo», y cero es cero."""

    def test_sin_decir_nada_la_de_su_tipo(self, casos):
        assert casos['pieceZ']['tipo'] == {'h': 140, 'base': 2720}

    def test_la_suya_si_la_tiene(self, casos):
        assert casos['pieceZ']['propia'] == {'h': 1100, 'base': 200}

    def test_y_cero_es_el_suelo_no_la_de_su_tipo(self, casos):
        """Una bandeja puesta en el suelo está a cero; si cero fuera «sin decir», volvería a
        colgar a 2,72 m."""
        assert casos['pieceZ']['enElSuelo']['base'] == 0


class TestDeFrenteSeEstira:
    """Se pidió poder redimensionar también de frente. Una pieza de 1000 × 600 en (2000, 2000)."""

    def test_el_asa_derecha_estira_hacia_la_derecha_y_la_izquierda_queda(self, casos):
        e = casos['estFrente']['N_er']
        assert (e['width_mm'], e['pos_x']) == (1300, 2000), e

    def test_el_asa_izquierda_estira_hacia_la_izquierda_y_la_derecha_queda(self, casos):
        e = casos['estFrente']['N_el']
        assert e['width_mm'] == 1300 and e['pos_x'] + e['width_mm'] == 3000, e

    def test_de_frente_al_este_lo_que_corre_por_la_pared_es_el_fondo(self, casos):
        """Sin girar, a lo largo de la pared este corre el fondo de la pieza, no su ancho."""
        e = casos['estFrente']['E_er']
        assert (e['width_mm'], e['depth_mm']) == (1000, 900), e

    def test_y_girada_un_cuarto_vuelve_a_ser_el_ancho(self, casos):
        e = casos['estFrente']['E_er90']
        assert (e['width_mm'], e['depth_mm']) == (1300, 600), e

    def test_girada_en_diagonal_no_estira_nada(self, casos):
        """Ningún lado da de frente a la pared: estirar dos medidas a la vez sería otra cosa que
        lo que se ve."""
        assert casos['estFrente']['diagonal'] == {}

    def test_un_rack_crece_de_u_en_u_y_nunca_baja_de_una(self, casos):
        assert casos['estFrente']['u'] == {'u_height': 48}
        assert casos['estFrente']['uMin'] == {'u_height': 1}


class TestUnaSalaSeAjustaAlPlanoDeSuPlanta:
    """Se pidió poder estirar una sala sobre el plano de su planta hasta que ocupe su zona, y
    que el zoom no rompa la proporción entre el plano y las salas."""

    def test_se_estira_a_pasos_de_diez_centimetros(self, casos):
        """No a la baldosa de 600 de una sala: en el plano de un edificio no hay baldosa."""
        e = casos['salaEstirada']
        assert (e['width_mm'], e['depth_mm']) == (5200, 3600), e
        assert (e['pos_x'], e['pos_y']) == (1000, 1000), 'la esquina opuesta se ha movido'

    def test_un_plano_sin_ancho_tiene_un_tamano_fijo(self, casos):
        """Sacarlo de las salas estiraba el plano cada vez que se movía una sala hacia fuera,
        y lo ya colocado dejaba de cuadrar con el dibujo."""
        assert casos['planoSinAncho'] == [50000]


class TestLoQueSeSueltaCaeEnSuSala:
    """El plano de la sede pone racks y piezas en la sala que haya debajo, en las coordenadas de
    esa sala aunque esté girada; y fuera de toda sala, en la zona general de la planta, que está
    en (0, 0) sin girar."""

    def _r(self, p):
        return [round(p['x']), round(p['y'])]

    def test_el_centro_de_una_sala_girada_es_su_centro(self, casos):
        assert self._r(casos['local']['centro']) == [3000, 2000]

    def test_y_su_esquina_de_origen_es_su_origen(self, casos):
        """Girada un cuarto (en el sentido de las agujas), la esquina de origen de la sala queda
        arriba a la DERECHA en la planta."""
        assert self._r(casos['local']['esquina']) == [0, 0]

    def test_en_la_zona_general_la_planta_y_la_sala_coinciden(self, casos):
        assert self._r(casos['local']['zona']) == [9000, 4000]
