#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One object of the plan, the same in the room and on the floor (`_planobj.html`).

The two plans drew, showed and handled a rack, a piece or a room item each their own way: the
floor drew them without the access-control dot or an item's state and letters, its inspector
was a name and four buttons, and duplicating put the copy a tile away diagonally with its label
in the room and to the right without it on the floor. Now one drawing (`_dcThingSvg`), one set
of panels that write to whichever plan is open (`_dcObj`), and one turn, duplicate and drop.

Run in node against the panel's own bundle, with the server's plan catalogue loaded.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle, plan2d_catalog_js  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='no node to run the script with')

_PROBE = r"""
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
_dcimData = {orgs: [], sites: []};
renderDcim = () => {};
__out = {};
let llamadas = [];
_dcimSend = (m, u, b) => { llamadas.push([m, u, b]); return Promise.resolve({ok: false, error: 'x'}); };
let pregunta = '';
showConfirmModal = (texto) => { pregunta = texto; };
_dcpQueue = (url, cambios) => { llamadas.push(['QUEUE', url, cambios]); };

const puerta = {uid: 'pu', kind: 'door', label: '', pos_x: 1000, pos_y: 0, width_mm: 1000, depth_mm: 120,
                rotation: 0, lock: 'cylinder', state: 'warning'};
const pc = {uid: 'pc1', role: 'pc', label: 'PC-01', pos_x: 500, pos_y: 500, state: 'error',
            box: {x: 500, y: 500, w: 180, d: 300, rot: 0}};
const rack = {uid: 'k1', name: 'R01', pos_x: 3000, pos_y: 2000, width_mm: 600, depth_mm: 1000,
              rotation: 0, base_mm: 0, asset: 'RACK-0007', u_height: 42, roll: {state: 'ok'}};

// ── En la planta ────────────────────────────────────────────────────────────
_dcimPlan = null;
_dcsPlan = {site: {uid: 's', rooms: [{uid: 'rA', floor_uid: 'p', name: 'Sala A', pos_x: 0, pos_y: 0,
                                      width_mm: 8000, depth_mm: 6000, rotation: 0}]},
            floors: [{uid: 'p', area_uid: ''}], floor: 'p', kinds: P2D_CAT.dcim.kinds,
            content: {rA: {racks: [rack], features: [puerta], items: [pc]}}};
_dcsItem = null; _dcsSel = '';
__out.plantaPuerta = _dcsThing('feature', puerta, 'rA');
__out.plantaPc = _dcsThing('ritem', pc, 'rA');
__out.plantaRack = _dcsThing('rack', rack, 'rA');
__out.busca = [!!_dcObj('rack', 'k1'), !!_dcObj('ritem', 'pc1'), _dcObjRoom('feature', 'pu')];
// La ficha de la planta es la de la sala.
_dcsItem = {kind: 'rack', uid: 'k1', room: 'rA'};
__out.fichaRack = _dcsItemPanel(rack);
_dcsItem = {kind: 'feature', uid: 'pu', room: 'rA'};
__out.fichaPieza = _dcsItemPanel(puerta);
_dcsItem = {kind: 'ritem', uid: 'pc1', room: 'rA'};
__out.fichaEquipo = _dcsItemPanel(pc);
// Escribir un campo desde la planta llega a la fila de la planta.
_dcpRackSet('k1', 'name', 'R01-B');
__out.campoPlanta = [rack.name, llamadas.filter(l => l[0] === 'QUEUE').map(l => l[1])];
// Duplicar, girar y quitar desde la planta.
llamadas = [];
_dcsItem = {kind: 'feature', uid: 'pu', room: 'rA'};
_dcsItemDuplicate();
_dcsItem = {kind: 'rack', uid: 'k1', room: 'rA'};
_dcsItemDuplicate();
_dcsItem = {kind: 'ritem', uid: 'pc1', room: 'rA'};
_dcsItemTurn();
__out.accionesPlanta = llamadas.map(l => [l[0], l[1], l[2]]);
_dcsItem = {kind: 'feature', uid: 'pu', room: 'rA'};
_dcsItemDrop();
__out.preguntaPlanta = pregunta;

// ── En la sala, lo mismo ────────────────────────────────────────────────────
_dcsPlan = null;
_dcimPlan = {room: {uid: 'rA', name: 'Sala A', tile_mm: 600}, racks: [rack]};
_dcpFeat = {kinds: P2D_CAT.dcim.kinds, features: [puerta], items: [pc]};
_dcpSel = null;
__out.salaPuerta = _dcpFeature(puerta);
__out.salaPc = _dcriItemSvg(pc);
llamadas = [];
_dcpDuplicate('pu');
_dcpRackDuplicate('k1');
__out.accionesSala = llamadas.map(l => [l[0], l[1], l[2]]);
pregunta = '';
_dcpDropFeature('pu');
__out.preguntaSala = pregunta;

// ── La barra flotante y la paleta, del motor ────────────────────────────────
const acts = (lista) => lista.map(b => b.act);
__out.barraSala = {rack: acts(_dcpP2d.ad.floatButtons({kind: 'rack'})),
                   pieza: acts(_dcpP2d.ad.floatButtons({kind: 'feature'}))};
_dcpSel = null;
_dcpP2d.ad.floatAct('edit', {kind: 'feature', room: '', uid: 'pu'});
__out.editaEnSala = _dcpSel;
// Todo a la vista (el modo 'all'), para ver cada objeto por su clave.
p2dPaletteMode = 'all';
const paletaSala = _dcpPaletteHtml();
ssCanvasWindow = () => ({x: 1000 * _DCP_SCALE, y: 1000 * _DCP_SCALE, w: 4000 * _DCP_SCALE, h: 2000 * _DCP_SCALE});
llamadas = [];
p2dAdd('room', 'camera');
p2dAdd('room', 'door');
__out.anadeSala = llamadas.map(l => [l[1], l[2]]);
P2DCAL = {kind: 'room'};
__out.paletaCalibrando = _dcpPaletteHtml();
P2DCAL = null;
currentUser = {permissions: ['dcim_view']};
__out.barraMira = {rack: acts(_dcpP2d.ad.floatButtons({kind: 'rack'})),
                   pieza: acts(_dcpP2d.ad.floatButtons({kind: 'feature'}))};
currentUser = {permissions: ['dcim_view', 'dcim_edit']};

_dcimPlan = null;
_dcsPlan = {site: {uid: 's', rooms: [{uid: 'rA', floor_uid: 'p', name: 'Sala A', pos_x: 0, pos_y: 0,
                                      width_mm: 8000, depth_mm: 6000, rotation: 0}]},
            floors: [{uid: 'p', area_uid: ''}], floor: 'p', kinds: P2D_CAT.dcim.kinds,
            content: {rA: {racks: [rack], features: [puerta], items: [pc]}}};
__out.barraPlanta = {rack: acts(_dcsP2d.ad.floatButtons({kind: 'rack', room: 'rA'})),
                     pieza: acts(_dcsP2d.ad.floatButtons({kind: 'feature', room: 'rA'})),
                     sala: acts(_dcsP2d.ad.floatButtons({kind: 'room', room: ''}))};
_dcsP2d.ad.floatAct('back', {kind: 'feature', room: 'rA', uid: 'pu'});
__out.alFondoPlanta = _dcsIsBack('feature', 'rA', 'pu');
p2dBringAll('floor');
const paletaPlanta = _dcsPaletteHtml();
const claves = (html, n) => html.split('p2dPaletteAdd(&quot;' + n + '&quot;,&quot;').slice(1)
    .map(x => x.split('&quot;')[0]);
__out.paletas = {sala: claves(paletaSala, 'room'), planta: claves(paletaPlanta, 'floor'),
                 nucleo: paletaPlanta.includes("_dcsCoreAdd('stairs')") && !paletaSala.includes('_dcsCoreAdd'),
                 rack: paletaSala.includes("p2dPlaceStart('room','rack')") && paletaPlanta.includes("p2dPlaceStart('floor','rack')")};
llamadas = [];
p2dAdd('floor', 'door');
__out.anadePlanta = llamadas.map(l => [l[1], l[2]]);
// La barra de una sala espera si se viene de algo de dentro (la barra de eso aún no se ha ido);
// sin nada que esperar, sale ya. (El arnés no corre temporizadores: se cuenta lo que se pinta.)
let pintadas = 0;
p2dFloatPaint = () => { pintadas++; };
_dcsP2d.floatTimer = 1;
p2dFloatShow(_dcsP2d, {kind: 'room', room: '', uid: 'rA'}, {});
const conBarraDentro = pintadas;
_dcsP2d.floatTimer = null;
p2dFloatShow(_dcsP2d, {kind: 'room', room: '', uid: 'rA'}, {});
p2dFloatShow(_dcsP2d, {kind: 'rack', room: 'rA', uid: 'k1'}, {});
__out.salaEspera = [conBarraDentro, pintadas];

// ── El plano de fondo ───────────────────────────────────────────────────────
__out.herramientas = {conPlano: p2dPlanFileTools('floors', 'p', true), sinPlano: p2dPlanFileTools('rooms', 'rA', false)};
currentUser = {permissions: ['dcim_view']};
__out.herramientasMira = p2dPlanFileTools('floors', 'p', true);
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
const imagen = {data: 'data:image/png;base64,AAAA', ratio: 0.5};
_dcPlanBg = true;
_dcsPlan.image = imagen;
_dcsPlan.floors[0].plan = 'p.png';
_dcsPlan.floors[0].plan_mm = 20000;
__out.imagenPlanta = (_dcsContent().match(/<image [^>]*>/) || [''])[0];
_dcimPlan = {room: {uid: 'zz', plan: 'x.png', plan_mm: 20000}, racks: [], image: imagen};
__out.imagenSala = _dcpPlanImage([]);
// Subir y quitar: a la ruta de cada uno, y lo que tiene después se vuelve a leer.
const pedidos = [];
fetch = (url, o) => { pedidos.push([o.method, url]); return Promise.resolve({ok: false, json: () => Promise.resolve({})}); };
FormData = function () { this.append = () => {}; };
p2dPlanUpload({files: [{}], value: ''}, 'rooms', 'zz');
showConfirmModal = (texto, hacer) => hacer();
p2dPlanDrop('floors', 'p');
__out.pedidos = pedidos;
let leidas = [];
_dcpLoadPlan = (r) => { leidas.push('sala:' + r.uid + ':' + r.plan); return Promise.resolve(); };
_dcsLoadImage = () => { leidas.push('planta'); return Promise.resolve(); };
_dcPlanSet('rooms', 'zz', '');
_dcPlanSet('floors', 'p', 'nuevo.png');
__out.trasCambiar = [leidas[0], _dcimPlan.room.plan, _dcimPlan.image, _dcsPlan.floors[0].plan];

// ── Arrastrar uno solo, por el motor ────────────────────────────────────────
// (El arnés no espera a las promesas: se mira lo que se manda a guardar, no la petición.)
let guardado = null;
p2dSavePositions = (P, members) => { guardado = [P.name, members.map(m => [m.kind, m.uid])]; return Promise.resolve(); };
let punto = {x: 0, y: 0};
ssCanvasPoint = () => punto;
const evg = {currentTarget: {setPointerCapture() {}}, pointerId: 1, altKey: false};
_dcsPlan = null;
const rackSala = {uid: 'k1', name: 'R01', pos_x: 3000, pos_y: 2000, width_mm: 600, depth_mm: 1000, rotation: 0, roll: {}};
_dcimPlan = {room: {uid: 'rA', name: 'Sala A', tile_mm: 600, width_mm: 9000, depth_mm: 6000}, racks: [rackSala]};
_dcpFeat = {kinds: P2D_CAT.dcim.kinds, features: [], items: []};
_dcpView = 'top'; _dcpMagnet = true; _dcpSel = null;
__out.cogeSala = p2dGrab(_dcpP2d, evg, {kind: 'rack', room: '', uid: 'k1'});
punto = {x: 1000 * _DCP_SCALE, y: 0};
p2dMove(_dcpP2d, evg);
__out.movidoSala = [rackSala.pos_x, rackSala.pos_y];
p2dUp(_dcpP2d);
__out.guardaSala = guardado;
// Pulsar un rack sin moverlo: elegido, con su ficha.
guardado = null;
punto = {x: 0, y: 0};
p2dGrab(_dcpP2d, evg, {kind: 'rack', room: '', uid: 'k1'});
p2dUp(_dcpP2d);
__out.pulsaRack = [_dcpSel, guardado];
// Quien solo mira no coge nada.
currentUser = {permissions: ['dcim_view']};
__out.miraNoCoge = p2dGrab(_dcpP2d, evg, {kind: 'rack', room: '', uid: 'k1'});
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
// En la planta: lo de una sala girada recibe el desplazamiento girado, y una sala se mueve sola.
_dcimPlan = null;
const pcPlanta = {uid: 'pc9', role: 'pc', pos_x: 500, pos_y: 500, rotation: 0, box: {x: 500, y: 500, w: 180, d: 300, rot: 0}};
const salaGirada = {uid: 'rG', floor_uid: 'p', name: 'Sala G', pos_x: 20000, pos_y: 20000,
                    width_mm: 4000, depth_mm: 2000, rotation: 90};
_dcsPlan = {site: {uid: 's', rooms: [salaGirada]}, floors: [{uid: 'p', area_uid: ''}], floor: 'p',
            kinds: P2D_CAT.dcim.kinds, content: {rG: {racks: [], features: [], items: [pcPlanta]}}};
punto = {x: 0, y: 0};
p2dGrab(_dcsP2d, evg, {kind: 'ritem', room: 'rG', uid: 'pc9'});
punto = {x: 1000 * _DCP_SCALE, y: 0};
p2dMove(_dcsP2d, evg);
__out.movidoPlanta = [pcPlanta.pos_x, pcPlanta.pos_y];
p2dUp(_dcsP2d);
__out.guardaPlanta = guardado;
punto = {x: 0, y: 0};
p2dGrab(_dcsP2d, evg, {kind: 'room', room: '', uid: 'rG'});
punto = {x: 0, y: 1000 * _DCP_SCALE};
p2dMove(_dcsP2d, evg);
__out.movidaSala = [salaGirada.pos_x, salaGirada.pos_y, pcPlanta.pos_x, pcPlanta.pos_y];
p2dUp(_dcsP2d);
__out.guardaSalaPlanta = guardado;
__out.rutas = [_dcpP2d.ad.url('rack', 'k1'), _dcsP2d.ad.url('ritem', 'pc9'), _dcsP2d.ad.url('room', 'rG')];

// ── La paleta, por grupos o todo a la vista ──
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
P2DCAL = null;
p2dPaletteMode = 'groups';
_dcpP2d.palOpen = null;
const cerrada = p2dPaletteHtml(_dcpP2d);
p2dPaletteOpen('room', 'safety');
const abierta = p2dPaletteHtml(_dcpP2d);
p2dPaletteOpen('room', 'safety');
const otraVez = _dcpP2d.palOpen;
p2dPaletteOpen('room', 'equipment');
p2dPaletteAdd('room', 'camera');
const eligePoner = [_dcpP2d.placing && _dcpP2d.placing.key, _dcpP2d.palOpen];
const conTitulo = (p2dPaletteMode = 'all', p2dPaletteHtml(_dcpP2d));
p2dPaletteMode = 'groups';
// Poner: el clic siguiente en el plano dice dónde; una pieza se puede dibujar con su recuadro.
const puestos = [], addAt0 = _dcpP2d.ad.addAt, redraw0 = _dcpP2d.ad.redraw, punto0 = ssCanvasPoint;
_dcpP2d.ad.addAt = (k, p, tam) => { puestos.push([k, Math.round(p.x), Math.round(p.y), tam]); };
_dcpP2d.ad.redraw = () => {};
let aqui = null;
ssCanvasPoint = () => aqui;
const SP = _DCP_SCALE;
aqui = {x: 1000 * SP, y: 2000 * SP};
p2dPlaceDown(_dcpP2d, {button: 0}); p2dPlaceUp(_dcpP2d);
const trasPoner = _dcpP2d.placing;
p2dPlaceStart('room', 'bench');
aqui = {x: 0, y: 0}; p2dPlaceDown(_dcpP2d, {button: 0});
aqui = {x: 3000 * SP, y: 1000 * SP}; p2dPlaceMove(_dcpP2d, {});
const recuadro = p2dPlaceSvg(_dcpP2d);
p2dPlaceUp(_dcpP2d);
p2dPlaceStart('room', 'pc');
aqui = {x: 500 * SP, y: 500 * SP}; p2dPlaceDown(_dcpP2d, {button: 0});
aqui = {x: 3000 * SP, y: 3000 * SP}; p2dPlaceMove(_dcpP2d, {}); p2dPlaceUp(_dcpP2d);
p2dPlaceStart('room', 'door'); p2dPlaceStart('room', 'door');
const otraVezNada = _dcpP2d.placing;
p2dPlaceStart('room', 'door');
const escape = [p2dKeyDown(_dcpP2d, {key: 'Escape'}), _dcpP2d.placing];
p2dPlaceStart('room', 'door');
const central = p2dPlaceDown(_dcpP2d, {button: 1});
p2dPlaceCancel(_dcpP2d);
_dcpP2d.ad.addAt = addAt0; _dcpP2d.ad.redraw = redraw0; ssCanvasPoint = punto0;
__out.poner = {eligePoner, trasPoner, puestos, recuadro: recuadro.includes('data-p2dplace'),
               otraVezNada, escape, central,
               titulo: conTitulo.includes('ss-pal-sec-fixed') && conTitulo.includes('Racks')};
// Lo dibujado se guarda con su tamaño; un equipo no lo toma.
llamadas = [];
_dcObjAdd('bench', 'rX', {x: 1500, y: 500}, (mm) => mm, {w: 3000, d: 1000});
_dcObjAdd('pc', 'rX', {x: 0, y: 0}, (mm) => mm, {w: 3000, d: 1000});
__out.anadeMedido = llamadas.map(l => l[2]);
// El nombre, a la medida de lo que nombra.
const letra = (svg) => Number((/font-size="([\d.]+)"/.exec(svg) || [])[1]);
__out.letraRack = letra(_dcThingSvg('rack', {uid: 'kf', name: 'R04', width_mm: 600, depth_mm: 1000, pos_x: 0, pos_y: 0}, {}));
__out.letraPasillo = letra(_dcThingSvg('feature', {uid: 'fa', kind: 'aisle', label: 'Pasillo frío', width_mm: 4800,
                                                   depth_mm: 1200, pos_x: 0, pos_y: 0}, {}));
__out.escalaDcp = _DCP_SCALE;
// A rack says its front and its back, as every piece; and the «3D» link.
const rackSvg = _dcThingSvg('rack', {uid: 'kfb', name: 'R01', width_mm: 600, depth_mm: 1000, pos_x: 0, pos_y: 0}, {});
__out.frenteRack = [rackSvg.includes('fill="var(--bs-primary)"'), /stroke-dasharray="3 2"/.test(rackSvg)];
__out.enlace3d = {sala: _dc3dLinkHtml({site: 's1', floor: 'f1', room: 'r1'}),
                  rack: _dc3dLinkHtml({site: 's1', floor: 'f1', rack: 'k1'}, true),
                  sinPlanta: _dc3dLinkHtml({site: 's1', room: 'r1'}), sinSede: _dc3dLinkHtml({floor: 'f1'})};
__out.porGrupos = {
    grupos: (cerrada.match(/data-p2dpalgroup="(\w+)"/g) || []).map(x => x.split('"')[1]),
    sinPanel: !cerrada.includes('ss-pal-fly'),
    rackDelante: cerrada.indexOf("p2dPlaceStart('room','rack')") >= 0
                 && cerrada.indexOf("p2dPlaceStart('room','rack')") < cerrada.indexOf('data-p2dpalgroup'),
    // Desplegar y contraer, con el icono del panel para eso (el del inspector del plano).
    modo: cerrada.includes('data-p2dpalmode="groups"') && cerrada.includes('bi-chevron-double-right')
          && cerrada.indexOf('data-p2dpalmode') < cerrada.indexOf("p2dPlaceStart('room','rack')"),
    // Level with its button: in a hole with it, after it and before the next group's.
    alSuBoton: /<div class="ss-pal-anchor">\s*<button[^>]*data-p2dpalgroup="safety"[\s\S]*?<\/button>\s*<div class="ss-pal-fly"/.test(abierta)
               && abierta.indexOf('data-p2dpalfly') < abierta.indexOf('data-p2dpalgroup="access"'),
    panel: [abierta.includes('data-p2dpalfly="safety"'), (abierta.match(/class="ss-pal-row"/g) || []).length,
            abierta.includes('300 × 300')],
    otraVezCierra: otraVez, puestos, cerradoAlPoner: _dcpP2d.palOpen};
p2dPaletteMode = 'all';
const todos = p2dPaletteHtml(_dcpP2d);
p2dPaletteFold('room', 'safety');
const plegada = p2dPaletteHtml(_dcpP2d);
p2dPaletteFold('room', 'safety');
p2dPaletteModeSet('room', 'groups');
const enTodos = (h, k) => h.includes('p2dPaletteAdd(&quot;room&quot;,&quot;' + k + '&quot;)');
__out.todoALaVista = {titulos: (todos.match(/data-p2dpalsec=/g) || []).length,
                      cada: Object.keys(P2D_CAT.dcim.kinds).every(k => enTodos(todos, k)),
                      plegado: [enTodos(plegada, 'extinguisher'), enTodos(plegada, 'camera')],
                      vuelve: p2dPaletteMode,
                      modo: todos.includes('data-p2dpalmode="all"') && todos.includes('bi-chevron-double-left')
                            && todos.indexOf('data-p2dpalmode') < todos.indexOf('ss-pal-sec')};
"""


@pytest.fixture(scope='module')
def out():
    """One `node` run for the whole module."""
    pytest.importorskip('flask')
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return node_run(panel_bundle(c), plan2d_catalog_js(c) + _PROBE)


class TestTheFloorDrawsLikeTheRoom:

    def test_a_door_with_a_lock_carries_its_access_dot(self, out):
        assert '<circle' in out['plantaPuerta'], 'the floor drew no access-control dot'
        assert '<circle' in out['salaPuerta']

    def test_a_room_item_carries_its_letters_and_its_state(self, out):
        for dibujo in (out['plantaPc'], out['salaPc']):
            assert '>PC</text>' in dibujo and '<circle' in dibujo

    def test_the_same_shape_on_both(self, out):
        """The body is one drawing: the same rectangle, scaled the same, on both plans."""
        forma = 'width="20" height="2.4"'
        assert forma in out['plantaPuerta'] and forma in out['salaPuerta']

    def test_each_keeps_its_own_handles_and_text(self, out):
        assert 'data-dcsi="feature"' in out['plantaPuerta'] and 'data-dcpf="pu"' in out['salaPuerta']
        assert 'paint-order="stroke"' in out['plantaRack'], 'the floor writes its labels upright'


class TestOnePanelForBoth:

    def test_the_floors_inspector_is_the_rooms(self, out):
        # The room's fields: a rack's U and height off the floor, a piece's height.
        assert '_dcpRackSet(' in out['fichaRack'] and 'u_height' in out['fichaRack'] and 'base_mm' in out['fichaRack']
        assert '_dcpSet(' in out['fichaPieza'] and 'height_mm' in out['fichaPieza']
        assert '_dcriTrace(' in out['fichaEquipo'], 'tracing a cable from the floor'
        assert '_dcsItemOpen()' in out['fichaRack'], 'and still a way to open its room or rack'

    def test_the_object_is_found_on_whichever_plan_is_open(self, out):
        assert out['busca'] == [True, True, 'rA']

    def test_a_field_typed_on_the_floor_reaches_the_floors_row(self, out):
        nombre, colas = out['campoPlanta']
        assert nombre == 'R01-B'
        assert colas == ['/api/v1/dcim/racks/k1']


class TestTheFloatingBarAndThePalette:
    """Both plans' floating bar and palette are the 2D plan editor's (`p2dFloatShow`,
    `p2dPaletteHtml`); each screen only says which buttons a thing has and where a new one goes."""

    def test_the_same_buttons_for_a_thing_on_both_plans(self, out):
        assert out['barraSala']['rack'] == ['open', 'edit', 'turn', 'dup', 'back', 'move', 'drop']
        assert out['barraSala']['pieza'] == ['edit', 'turn', 'dup', 'back', 'drop']
        assert out['barraPlanta']['rack'] == out['barraSala']['rack']
        assert out['barraPlanta']['pieza'] == ['open'] + out['barraSala']['pieza'], 'and opening its room'

    def test_a_viewer_can_only_open(self, out):
        assert out['barraMira'] == {'rack': ['open'], 'pieza': []}

    def test_a_room_on_the_floor_has_its_own_buttons(self, out):
        assert out['barraPlanta']['sala'] == ['open', 'turn', 'unplace']

    def test_each_button_does_its_screens_thing(self, out):
        assert out['editaEnSala'] == {'kind': 'feature', 'uid': 'pu'}
        assert out['alFondoPlanta'] is True

    def test_a_rooms_bar_waits_when_coming_from_inside_it(self, out):
        assert out['salaEspera'] == [0, 2], 'the room waited; then it and a rack came at once'

    def test_both_palettes_come_from_the_same_catalogue(self, out):
        p = out['paletas']
        assert p['sala'] and p['sala'] == p['planta'], 'the same objects, the same order'
        assert p['sala'][0] == 'zone' and 'camera' in p['sala'] and 'door' in p['sala']
        assert p['rack'], 'and a rack before them, on both'
        assert p['nucleo'], 'the floor adds its stairs and lift, the room does not'

    def test_the_palette_by_group_opens_one_beside_it(self, out):
        """Asked for: thirty icons in one strip, told apart only by hovering each. One button per
        group (the rack still loose in front, then the mode switch); pressing one opens its objects
        beside it by name (no size: a piece is drawn to its size), pressing it again closes it, and adding one closes it."""
        g = out['porGrupos']
        # The switch to expand and collapse goes first, in both modes.
        assert g['grupos'] == ['structure', 'furniture', 'datacenter', 'safety', 'access', 'sockets',
                               'equipment']
        assert g['sinPanel'] and g['rackDelante'] and g['modo']
        assert g['alSuBoton'], 'reported: the panel opened at the top of the strip, away from its button'
        assert g['panel'] == [True, 7, False], 'its objects by name, without a size: drawing sets it'
        assert g['otraVezCierra'] is None and g['cerradoAlPoner'] is None

    def test_choosing_waits_for_where_to_put_it(self, out):
        """Asked for: choosing something put it in the middle of the view at once. Now it leaves
        the plan waiting: the next click puts it there; a piece can be drawn with its box, which
        sets its size and puts it in the middle of it; a device dragged is still put where it was
        pressed. Choosing it again or Escape lets it go, and the middle button still pans."""
        p = out['poner']
        assert p['eligePoner'] == ['camera', None]
        assert p['trasPoner'] is None
        assert p['puestos'] == [['camera', 1000, 2000, None], ['bench', 1500, 500, {'w': 3000, 'd': 1000}],
                                ['pc', 500, 500, None]]
        assert p['recuadro'] and p['otraVezNada'] is None and p['escape'] == [True, None]
        assert p['central'] is False

    def test_a_drawn_piece_is_saved_with_its_size(self, out):
        bench, pc = out['anadeMedido']
        assert (bench['width_mm'], bench['depth_mm'], bench['pos_x'], bench['pos_y']) == (3000, 1000, 0, 0)
        assert 'width_mm' not in pc

    def test_a_name_fits_what_it_names(self, out):
        """Reported: a rack's name was drawn at a fixed size wider than the rack, and ran into
        the next rack's. It fits the rack's width now; a big piece keeps the usual size."""
        ancho_rack = 600 * out['escalaDcp']
        assert out['letraRack'] * 0.6 * 3 <= ancho_rack * 0.9 + 1e-9
        assert out['letraPasillo'] == 5.6

    def test_a_rack_says_its_front_and_its_back(self, out):
        """Reported: on the map one could not tell a rack's front from its back. As every piece:
        a blue band at the front and a dashed line at the back."""
        assert out['frenteRack'] == [True, True]

    def test_the_3d_link_opens_that_place_in_another_tab(self, out):
        """Asked for: a button on the maps that opens the room, the floor or the rack in 3D in
        another tab. Without a floor only the building, where a room has no place."""
        e = out['enlace3d']
        assert 'href="/3d?site=s1&amp;floor=f1&amp;mode=floor&amp;room=r1"' in e['sala']
        assert 'target="_blank"' in e['sala'] and 'rel="noopener"' in e['sala']
        assert 'rack=k1' in e['rack'] and 'btn-sm' not in e['rack']
        assert 'href="/3d?site=s1"' in e['sinPlanta'] and e['sinSede'] == ''
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        dcim = os.path.join(src, 'lib', 'web_admin', 'templates', 'partials', 'dcim')
        for f in ('_plan.html', '_siteplan.html', '_rack.html'):
            assert '_dc3dLinkHtml(' in io.open(os.path.join(dcim, f), encoding='utf-8').read(), f

    def test_what_is_loose_has_a_title_too(self, out):
        """Reported: with everything in view the rack, alone at the top, had no title."""
        assert out['poner']['titulo']

    def test_both_plans_take_the_click_to_put(self):
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        dcim = os.path.join(src, 'lib', 'web_admin', 'templates', 'partials', 'dcim')
        for f, n in (('_plan.html', '_dcpP2d'), ('_siteplan.html', '_dcsP2d')):
            s = io.open(os.path.join(dcim, f), encoding='utf-8').read()
            for fn in ('p2dPlaceDown(', 'p2dPlaceMove(', 'p2dPlaceUp('):
                assert fn + n in s, (f, fn)

    def test_or_everything_in_view_under_its_title(self, out):
        """The other way to see it: every object, under the title of its group, and a group can
        be folded. The switch goes back and is remembered."""
        a = out['todoALaVista']
        assert a['titulos'] == 7 and a['cada'] and a['modo']
        assert a['plegado'] == [False, True]
        assert a['vuelve'] == 'groups'

    def test_no_palette_while_calibrating(self, out):
        assert out['paletaCalibrando'] == ''

    def test_adding_puts_it_where_one_looks(self, out):
        """In the centre of the view: equipment by its corner, a piece by its centre; on the floor,
        in the room under the centre, in its coordinates."""
        camara, puerta = out['anadeSala']
        assert camara[0] == '/api/v1/dcim/rooms/rA/items' and camara[1]['role'] == 'camera'
        assert (camara[1]['pos_x'], camara[1]['pos_y']) == (3000, 1800)
        assert puerta[0] == '/api/v1/dcim/features' and puerta[1]['kind'] == 'door'
        en_planta = out['anadePlanta'][0]
        assert en_planta[0] == '/api/v1/dcim/features' and en_planta[1]['room_uid'] == 'rA'


class TestTheBackgroundPlan:
    """The background plan's fetching, drawing, upload and removal are one for both plans."""

    def test_the_same_tools_on_both_and_only_for_whoever_edits(self, out):
        h = out['herramientas']
        assert 'p2dPlanUpload(this,' in h['conPlano'] and 'floors' in h['conPlano']
        assert 'p2dPlanDrop(' in h['conPlano'] and 'p2dPlanDrop(' not in h['sinPlano']
        assert out['herramientasMira'] == ''

    def test_the_same_image_on_both(self, out):
        assert out['imagenSala'].startswith('<image ') and out['imagenPlanta'].startswith('<image ')
        quitar_sitio = lambda s: s.split(' x=')[0]           # noqa: E731 — the box differs, the image not
        assert quitar_sitio(out['imagenSala']) == quitar_sitio(out['imagenPlanta'])
        assert 'opacity=".85"' in out['imagenSala'] and 'opacity=".85"' in out['imagenPlanta']

    def test_upload_and_remove_go_to_each_ones_route(self, out):
        assert out['pedidos'] == [['POST', '/api/v1/dcim/rooms/zz/plan'], ['DELETE', '/api/v1/dcim/floors/p/plan']]

    def test_after_a_change_the_plan_is_read_again(self, out):
        """A room whose own plan is removed is read again —a general area falls back to its
        floor's—, and the floor reads its new one."""
        leida, plan_sala, imagen_sala, plan_planta = out['trasCambiar']
        assert leida == 'sala:zz:' and plan_sala == '' and imagen_sala is None
        assert plan_planta == 'nuevo.png'


class TestDraggingOneThing:
    """One thing is dragged by the engine too, as several are: the snap, the steps, what is saved
    on release and how it is undone. Each screen keeps what a click does."""

    def test_a_rack_in_the_room_moves_to_the_tile_and_is_saved_by_its_route(self, out):
        assert out['cogeSala'] is True
        assert out['movidoSala'] == [4200, 1800], '3000 + 1000 mm and 2000, each to its tile of 600'
        assert out['guardaSala'] == ['room', [['rack', 'k1']]]

    def test_a_click_without_moving_selects_the_rack(self, out):
        elegido, guardado = out['pulsaRack']
        assert elegido == {'kind': 'rack', 'uid': 'k1'} and guardado is None

    def test_a_viewer_grabs_nothing(self, out):
        assert out['miraNoCoge'] is False

    def test_on_the_floor_a_thing_in_a_turned_room_moves_turned_back(self, out):
        """A metre right on the floor is, in a room turned a quarter, a metre to its «up»."""
        assert out['movidoPlanta'] == [500, -500]
        assert out['guardaPlanta'] == ['floor', [['ritem', 'pc9']]]

    def test_a_room_moves_and_what_is_inside_goes_with_it(self, out):
        sx, sy, ix, iy = out['movidaSala']
        assert (sx, sy) == (20000, 21000) and (ix, iy) == (500, -500), 'the item kept its place in the room'
        assert out['guardaSalaPlanta'] == ['floor', [['room', 'rG']]]

    def test_each_one_is_written_by_its_route(self, out):
        assert out['rutas'] == ['/api/v1/dcim/racks/k1', '/api/v1/dcim/room-items/pc9',
                                '/api/v1/dcim/rooms/rG']


class TestOneSetOfActions:

    def test_duplicating_sends_the_same_from_both_plans(self, out):
        planta = [a for a in out['accionesPlanta'] if a[0] == 'POST']
        sala = out['accionesSala']
        assert [(a[1], sorted(a[2])) for a in planta] == [(a[1], sorted(a[2])) for a in sala]
        pieza = planta[0][2]
        assert (pieza['pos_x'], pieza['pos_y']) == (1000 + 1000 + 200, 0), 'to its right, 20 cm away'
        assert pieza['kind'] == 'door' and pieza['room_uid'] == 'rA'

    def test_a_copied_rack_does_not_take_its_asset_number(self, out):
        copia = [a[2] for a in out['accionesSala'] if a[1] == '/api/v1/dcim/racks'][0]
        assert 'asset' not in copia and copia['name'] != 'R01' and copia['base_mm'] == 0

    def test_turning_a_room_item_from_the_floor(self, out):
        giro = [a for a in out['accionesPlanta'] if a[0] == 'PUT']
        assert giro == [['PUT', '/api/v1/dcim/room-items/pc1', {'rotation': 90}]]

    def test_removing_asks_the_same_from_both(self, out):
        assert out['preguntaPlanta'] and out['preguntaPlanta'] == out['preguntaSala']
