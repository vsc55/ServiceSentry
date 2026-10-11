#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 2D plan editor (`plan2d`), on the room's plan and the floor's.

Asked for: a rack left a gap to the cold aisle it stands against, and the next rack to the one
beside it, because the tile magnet does not know where the aisle starts. Edges now snap to
what is next to them when they come close, and several things —chosen with Shift/Ctrl + click
or a Shift box, or kept together as a group (`group_uid`)— are dragged as one.

Both screens run on one engine (`_plan2d.html`), each with its adapter (`_plan2d_room.html`,
`_plan2d_floor.html`): what the engine does is tested through it, and what is each screen's —the
tile and the wall in a room, rooms that turn and contain things on a floor— through its adapter.
The arithmetic runs in node against the panel's own bundle; the group id is stored on the
server, which refuses anything that is not one.
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


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


class TestTheGroupIsStored:
    """`group_uid` on a rack, a piece and a room item: written, read back, and refused when it
    is not an id."""

    @pytest.fixture()
    def room(self, client):
        _login(client)
        c = client
        site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD'}))
        rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R01'}))
        aisle = _uid(c.post('/api/v1/dcim/features', json={'room_uid': room, 'kind': 'aisle'}))
        item = _uid(c.post(f'/api/v1/dcim/rooms/{room}/items', json={'role': 'pc'}))
        return dict(room=room, rack=rack, aisle=aisle, item=item)

    def test_each_kind_keeps_its_group(self, client, room):
        c = client
        assert c.put(f'/api/v1/dcim/racks/{room["rack"]}', json={'group_uid': 'g-abc'}).status_code == 200
        assert c.put(f'/api/v1/dcim/features/{room["aisle"]}', json={'group_uid': 'g-abc'}).status_code == 200
        assert c.put(f'/api/v1/dcim/room-items/{room["item"]}', json={'group_uid': 'g-abc'}).status_code == 200
        racks = c.get(f'/api/v1/dcim/racks?room={room["room"]}').get_json()['racks']
        feats = c.get(f'/api/v1/dcim/rooms/{room["room"]}/features').get_json()
        assert [r['group_uid'] for r in racks] == ['g-abc']
        assert [f['group_uid'] for f in feats['features']] == ['g-abc']
        assert [i['group_uid'] for i in feats['items']] == ['g-abc']

    def test_leaving_a_group_is_writing_it_empty(self, client, room):
        c = client
        c.put(f'/api/v1/dcim/racks/{room["rack"]}', json={'group_uid': 'g-abc'})
        assert c.put(f'/api/v1/dcim/racks/{room["rack"]}', json={'group_uid': ''}).status_code == 200
        racks = c.get(f'/api/v1/dcim/racks?room={room["room"]}').get_json()['racks']
        assert racks[0]['group_uid'] == ''

    @pytest.mark.parametrize('bad', [['g-1'], {'a': 1}, 'g 1', '<b>', 'x' * 65, 7])
    def test_what_is_not_an_id_is_refused(self, client, room, bad):
        c = client
        for url in (f'/api/v1/dcim/racks/{room["rack"]}', f'/api/v1/dcim/features/{room["aisle"]}',
                    f'/api/v1/dcim/room-items/{room["item"]}'):
            r = c.put(url, json={'group_uid': bad})
            assert r.status_code == 400, (url, bad, r.get_json())

    def test_a_floors_contents_bring_each_rooms_rows(self, client):
        """The floor plan lists rows and warns like the room plan: its contents carry them."""
        _login(client)
        c = client
        site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        floor = _uid(c.post('/api/v1/dcim/floors', json={'site_uid': site, 'name': 'P1'}))
        room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD', 'floor_uid': floor}))
        row = _uid(c.post('/api/v1/dcim/rows', json={'room_uid': room, 'name': 'A'}))
        _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R01', 'row_uid': row}))
        d = c.get(f'/api/v1/dcim/sites/{site}/contents').get_json()['rooms'][room]
        assert [(r['name'], r['racks']) for r in d['rows']] == [('A', 1)]
        assert d['loose'] == [] and d['warnings'] == []

    def test_nor_on_creation(self, client, room):
        c = client
        r = c.post('/api/v1/dcim/racks', json={'room_uid': room['room'], 'name': 'R02', 'group_uid': ['x']})
        assert r.status_code == 400
        r = c.post('/api/v1/dcim/features', json={'room_uid': room['room'], 'kind': 'aisle',
                                                   'group_uid': {'x': 1}})
        assert r.status_code == 400
        r = c.post(f'/api/v1/dcim/rooms/{room["room"]}/items', json={'role': 'pc', 'group_uid': ['x']})
        assert r.status_code == 400


_PROBE = r"""
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
_dcimData = {orgs: [], sites: []};
__out = {};
renderDcim = () => {};
_dcpView = 'top';
_dcpMagnet = true;
// Un rack arriba, un pasillo frío que no empieza en baldosa, y otro rack al lado.
_dcimPlan = {room: {uid: 'r1', tile_mm: 600, width_mm: 8000, depth_mm: 6000},
             racks: [{uid: 'k1', name: 'R01', pos_x: 0, pos_y: 0, width_mm: 600, depth_mm: 1000, rotation: 0},
                     {uid: 'k2', name: 'R02', pos_x: 3000, pos_y: 0, width_mm: 600, depth_mm: 1000, rotation: 0}]};
_dcpFeat = {kinds: {}, features: [{uid: 'f1', kind: 'aisle', pos_x: 0, pos_y: 1130, width_mm: 3000,
                                   depth_mm: 1200, rotation: 0}],
            items: [{uid: 'i1', role: 'pc', pos_x: 6000, pos_y: 5000, box: {x: 6000, y: 5000, w: 400, d: 400, rot: 0}}]};

// ── El imán entre cosas ──
const aisle = {x: 0, y: 1130, w: 3000, h: 1200};
// Un rack que baja hacia el pasillo, con 80 mm de hueco: su fondo se pega a la cara del pasillo,
// y su izquierda, a 60 mm de la del pasillo, se alinea con ella.
__out.pegado = p2dNearSnap({x: 60, y: 50, w: 600, h: 1000}, [aisle], 150);
// Un rack al lado de otro, a 40 mm: se juntan.
__out.lado = p2dNearSnap({x: 640, y: 0, w: 600, h: 1000}, [{x: 0, y: 0, w: 600, h: 1000}], 150);
// Lo que está lejos en el otro eje no es vecino: no se alinea con la otra punta de la sala.
__out.lejos = p2dNearSnap({x: 640, y: 4000, w: 600, h: 1000}, [{x: 0, y: 0, w: 600, h: 1000}], 150);
// Más allá del margen, nada.
__out.fuera = p2dNearSnap({x: 900, y: 0, w: 600, h: 1000}, [{x: 0, y: 0, w: 600, h: 1000}], 150);

// Arrastrando el rack k1 50 mm hacia abajo: la baldosa lo dejaría en 0 (con 130 mm de hueco al
// pasillo); llega a 80 mm del pasillo, y se pega a él.
__out.conImanCosas = _dcpPlaceNear({x: 0, y: 0}, 0, 50, 600, 1000, 0, new Set([p2dKey('rack', '', 'k1')]), false);
__out.guias = _dcpP2d.guides.slice();
__out.conAlt = _dcpPlaceNear({x: 0, y: 0}, 0, 50, 600, 1000, 0, new Set([p2dKey('rack', '', 'k1')]), true);
// Girado un cuarto, lo que se pega es la caja que se ve (1000 × 600), no la esquina guardada.
__out.girado = _dcpPlaceNear({x: 200, y: 300}, 0, 0, 600, 1000, 90, new Set([p2dKey('rack', '', 'k1')]), false);
// Al soltar, las guías se van.
p2dGuidesClear(_dcpP2d);
__out.guiasSinMano = p2dGuidesSvg(_dcpP2d, {});

// ── El recuadro se ve también la primera vez, con nada elegido ──
_dcpSel = null; _dcpP2d.picked.clear();
_dcpP2d.drag = {what: 'pickbox', from: {x: 0, y: 0}, to: {x: 10, y: 10}, moved: true};
__out.primerRecuadro = p2dPickedSvg(_dcpP2d, true).includes('data-p2dbox');
_dcpP2d.drag = null;

// ── Varios a la vez ──
const hit = (kind, uid) => ({kind, room: '', uid, cycle: null});
const ev = (o) => Object.assign({shiftKey: false, ctrlKey: false, metaKey: false, altKey: false,
                                 currentTarget: {setPointerCapture() {}}, pointerId: 1}, o || {});
_dcpSel = {kind: 'rack', uid: 'k1'};
__out.mayus = p2dManyDown(_dcpP2d, ev({shiftKey: true}), hit('rack', 'k2'));
__out.elegidos = p2dPickedList(_dcpP2d).map(m => m.kind + ':' + m.uid).sort();
__out.panel = p2dManyPanelHtml(_dcpP2d);
// Otra vez Mayús + clic sobre el mismo: sale.
p2dManyDown(_dcpP2d, ev({ctrlKey: true}), hit('rack', 'k2'));
__out.quitado = p2dPickedList(_dcpP2d).map(m => m.kind + ':' + m.uid);
// Un clic sin más sobre algo suelto: no es de aquí, y deja solo eso.
_dcpP2d.picked.add(p2dKey('feature', '', 'f1'));
__out.clicSuelto = p2dManyDown(_dcpP2d, ev(), hit('rack', 'k2'));
__out.trasClicSuelto = _dcpP2d.picked.size;

// El recuadro: lo que toca, en unidades del dibujo.
__out.recuadro = p2dInBox(_dcpP2d, {x: -1, y: -1}, {x: 600 * _DCP_SCALE + 1, y: 2400 * _DCP_SCALE})
    .map(m => m.kind + ':' + m.uid).sort();

// ── Un grupo se coge entero y se mueve junto ──
p2dPickClear(_dcpP2d);
_dcimPlan.racks[0].group_uid = 'g-x';
_dcpFeat.features[0].group_uid = 'g-x';
__out.grupo = p2dGroupOf(_dcpP2d, {kind: 'rack', room: '', uid: 'k1'}).map(m => m.kind + ':' + m.uid).sort();
let punto = {x: 0, y: 0};
ssCanvasPoint = () => punto;
_dcpSel = null;
__out.cogeGrupo = p2dManyDown(_dcpP2d, ev(), hit('feature', 'f1'));
__out.arrastre = _dcpP2d.drag && [_dcpP2d.drag.what, _dcpP2d.drag.members.length];
// 2 m a la derecha y 3 m abajo, lejos de todo: el cogido va a la baldosa, y el otro le sigue
// con el mismo desplazamiento.
punto = {x: 2000 * _DCP_SCALE, y: 3000 * _DCP_SCALE};
p2dMove(_dcpP2d, ev());
__out.movidos = [_dcimPlan.racks[0].pos_x, _dcimPlan.racks[0].pos_y,
                 _dcpFeat.features[0].pos_x, _dcpFeat.features[0].pos_y];
_dcpP2d.drag = null;

// ── Deshacer de una vez ──
_dcUndoPrime();
const U = (tipo, uid) => `/api/v1/dcim/${tipo}/${uid}`;
const k1 = _dcimPlan.racks[0], f1 = _dcpFeat.features[0];
P2DU.stack.push({url: 'otra', before: {}, after: {}, at: 0});
const desde = P2DU.stack.length;
k1.pos_x = 2600;
p2duRecord(U('racks', 'k1'), p2duBefore(U('racks', 'k1'), {pos_x: 2600}), {pos_x: 2600});
f1.pos_x = 2600;
p2duRecord(U('features', 'f1'), p2duBefore(U('features', 'f1'), {pos_x: 2600}), {pos_x: 2600});
p2duBatch(desde);
__out.lote = [P2DU.stack.length, (P2DU.stack[1].batch || []).length];
__out.loteTitulo = p2duButtonsInner().includes(tf('plan2d_n_things', 2));
const e = P2DU.stack.pop();
p2duDone(e, e.before, P2DU.redo);
__out.loteDeshecho = [k1.pos_x, f1.pos_x];
const r = P2DU.redo.pop();
p2duDone(r, r.after, P2DU.stack);
__out.loteRehecho = [k1.pos_x, f1.pos_x];
// Una sola escritura no es un lote.
const solo = P2DU.stack.length;
k1.pos_x = 3000;
p2duRecord(U('racks', 'k1'), p2duBefore(U('racks', 'k1'), {pos_x: 3000}), {pos_x: 3000});
p2duBatch(solo);
__out.unoNoLote = !P2DU.stack[P2DU.stack.length - 1].batch;
// Un equipo de sala también se deshace, y se dibuja de su caja.
__out.equipoEnDeshacer = P2DU.shadow.has(U('room-items', 'i1'));
const i1 = _dcpFeat.items[0];
p2duSync({url: U('room-items', 'i1')}, {pos_x: 100, pos_y: 200});
__out.cajaEquipo = [i1.box.x, i1.box.y];

__out.idGrupo = /^[A-Za-z0-9_-]{1,64}$/.test(p2dNewGroupId());

// ── Las teclas de la sala, por el motor ──
// Una puerta girada un cuarto, a 40 mm de la pared: la flecha la lleva a la pared que se ve.
_dcpFeat.features.push({uid: 'puerta', kind: 'door', pos_x: -400, pos_y: 2000, width_mm: 1000,
                        depth_mm: 120, rotation: 90});
_dcpSel = {kind: 'feature', uid: 'puerta'}; _dcpP2d.picked.clear();
const evk = (o) => Object.assign({key: '', shiftKey: false, ctrlKey: false, metaKey: false, altKey: false}, o);
__out.flechaEsDeAqui = p2dKeyDown(_dcpP2d, evk({key: 'ArrowLeft'}));
clearTimeout(_dcpP2d.arrowTimer);
__out.flechaPared = _dcpFeat.features.find(f => f.uid === 'puerta').pos_x;
let girado = '', quitado = '';
_dcpTurn = (uid) => { girado = uid; };
_dcObjDrop = (kind, uid) => { quitado = uid; };
_dcpSel = {kind: 'rack', uid: 'k2'};
p2dKeyDown(_dcpP2d, evk({key: 'r'}));
_dcpSel = {kind: 'item', uid: 'i1'};
p2dKeyDown(_dcpP2d, evk({key: 'Delete'}));
__out.teclasSala = [girado, quitado];
_dcpSel = {kind: 'rack', uid: 'k2'};
__out.escape = [p2dKeyDown(_dcpP2d, evk({key: 'Escape'})), _dcpSel];

// ── El modo del puntero ──
p2dPointerMode = 'select';
__out.modoElegir = [p2dBoxWanted({button: 0}), p2dBoxWanted({button: 1})];
__out.cursorElegir = [p2dPointerClass(true), p2dPointerClass(false)];
p2dPointerMode = 'pan';
__out.modoMover = [p2dBoxWanted({button: 0}), p2dBoxWanted({button: 0, shiftKey: true})];
__out.cursorMover = p2dPointerClass(true);
__out.botones = p2dPointerButtons();

// ── La planta: una sala girada un cuarto y la zona general ──
_dcimPlan = null;
_dcsPlan = {site: {uid: 's1', rooms: [
                {uid: 'a1', floor_uid: 'p1', name: 'Zona'},
                {uid: 'r1', floor_uid: 'p1', name: 'Sala A', pos_x: 1000, pos_y: 1000,
                 width_mm: 4000, depth_mm: 2000, rotation: 90}]},
            floors: [{uid: 'p1', area_uid: 'a1'}], floor: 'p1', kinds: {},
            content: {a1: {racks: [], features: [], items: [{uid: 'i9', role: 'printer', label: 'Imp-1',
                                                              pos_x: 100, pos_y: 100,
                                                              box: {x: 100, y: 100, w: 400, d: 400}}]},
                      r1: {racks: [{uid: 'k9', name: 'R09', pos_x: 0, pos_y: 0, width_mm: 600,
                                    depth_mm: 1000, rotation: 0}], features: [], items: []}}};
_dcsItem = null; _dcsSel = '';
const kRow = _dcsPlan.content.r1.racks[0];
__out.esquinas = _dcsCornersOf('rack', 'r1', kRow).map(q => [Math.round(q.x), Math.round(q.y)]);
const S2 = _DCP_SCALE, mm = (x, y) => ({x: x * S2, y: y * S2});
__out.recuadroRack = p2dInBox(_dcsP2d, mm(2900, -100), mm(4100, 700)).map(m => m.kind + '|' + m.uid).sort();
__out.recuadroTodo = p2dInBox(_dcsP2d, mm(-100, -100), mm(5000, 5000)).map(m => m.kind + '|' + m.uid).sort();
// 1 m a la derecha en la planta es, en una sala girada un cuarto, 1 m hacia su «arriba».
_dcsManyShift([{kind: 'rack', room: 'r1', uid: 'k9', at: {x: 0, y: 0}}], 1000, 0);
__out.giradoDeVuelta = [kRow.pos_x, kRow.pos_y];
// Con su sala moviéndose también, el rack se queda: ya va con ella.
_dcsManyShift([{kind: 'room', room: '', uid: 'r1', at: {x: 1000, y: 1000}},
               {kind: 'rack', room: 'r1', uid: 'k9', at: {x: 0, y: -1000}}], 500, 0);
__out.conSuSala = [_dcsRooms()[1].pos_x, kRow.pos_x, kRow.pos_y];
// Elegir dos y ver su contorno; un equipo y un rack de salas distintas se agrupan.
p2dPick('floor', 'rack', 'r1', 'k9');
p2dPick('floor', 'ritem', 'a1', 'i9', {shiftKey: true});
__out.plantaElegidos = p2dPickedList(_dcsP2d).map(m => m.kind + '|' + m.uid).sort();
__out.plantaContornos = (p2dPickedSvg(_dcsP2d).match(/data-p2dpick/g) || []).length;
__out.plantaPanel = p2dManyPanelHtml(_dcsP2d).includes('p2dGroup(');
__out.lista = _dcsElementsHtml();
__out.panelPlanta = _dcsFloorPanel();
// Todo lo del plano: una sala vacía (que la cabecera elige), el núcleo y los muros.
_dcsPlan.site.rooms.push({uid: 'rv', floor_uid: 'p1', name: 'Vacia', pos_x: 6000, pos_y: 0, width_mm: 2000,
                          depth_mm: 2000, rotation: 0});
Object.assign(_dcsPlan.floors[0], {core_kind: 'stairs', core_x: 3000, core_y: 3000});
_dcsPlan.walls = {p1: [{kind: 'wall', x1: 0, y1: 0, x2: 5000, y2: 0, thick_mm: 150},
                       {kind: 'door', x1: 1000, y1: 0, x2: 2000, y2: 0, thick_mm: 150}]};
const listaToda = _dcsElementsHtml();
__out.listaToda = {vacia: listaToda.includes('Vacia') && listaToda.includes("_dcsPick(&quot;rv&quot;)"),
                   salaElige: listaToda.includes("_dcsPick(&quot;r1&quot;)"),
                   zonaNoSeElige: !listaToda.includes("_dcsPick(&quot;a1&quot;)"),
                   nucleo: listaToda.includes('data-dcselem="core"'),
                   muros: /data-dcselem="walls"[\s\S]*?>2</.test(listaToda) && listaToda.includes('_dcwStart()')};
_dcsPlan.site.rooms.pop();
delete _dcsPlan.walls;
Object.assign(_dcsPlan.floors[0], {core_kind: '', core_x: 0, core_y: 0});
_dcsPick('');
__out.trasSoltar = p2dPickedList(_dcsP2d).length;

// ── La planta, como el editor de una sala ──
_dcsPlan = {site: {uid: 's2', rooms: [
                {uid: 'a2', floor_uid: 'p2', name: 'Zona'},
                {uid: 'rA', floor_uid: 'p2', name: 'Sala A', pos_x: 0, pos_y: 0, width_mm: 4000, depth_mm: 3000, rotation: 0},
                {uid: 'rB', floor_uid: 'p2', name: 'Sala B', pos_x: 4100, pos_y: 0, width_mm: 3000, depth_mm: 3000, rotation: 0}]},
            floors: [{uid: 'p2', area_uid: 'a2', name: 'P2', level: 2}], floor: 'p2', kinds: {},
            content: {a2: {racks: [], features: [], items: []},
                      rA: {racks: [{uid: 'kA', name: 'RA1', pos_x: 100, pos_y: 100, width_mm: 600, depth_mm: 1000, rotation: 0},
                                   {uid: 'kB', name: 'RA2', pos_x: 750, pos_y: 100, width_mm: 600, depth_mm: 1000, rotation: 0}],
                           features: [], items: [],
                           rows: [{uid: 'w1', name: 'A', racks: 2}], loose: [],
                           warnings: [{label: 'A', aisle: 'caliente', other: 'B'}]},
                      rB: {racks: [], features: [], items: []}}};
_dcsItem = null; _dcsSel = ''; _dcsP2d.picked.clear();
const rB = _dcsRooms()[2];
// Una sala que se acerca a otra se pega a ella; con Alt, solo a los pasos.
__out.salaPegada = _dcsNearDelta([{kind: 'room', room: '', uid: 'rB'}], _dcsAabb('room', '', rB), -50, 0, false);
__out.salaGuias = _dcsP2d.guides.slice();
__out.salaAlt = _dcsNearDelta([{kind: 'room', room: '', uid: 'rB'}], _dcsAabb('room', '', rB), -50, 0, true);
// Un rack junto a otro de su sala.
const kB = _dcsPlan.content.rA.racks[1];
__out.rackPegado = _dcsNearDelta([{kind: 'rack', room: 'rA', uid: 'kB'}], _dcsAabb('rack', 'rA', kB), -100, 0, false);

// Pulsar otra vez lo elegido pasa a lo de debajo.
_dcsMakePrimary({kind: 'rack', room: 'rA', uid: 'kA'});
__out.ciclo = _dcsCycle({moved: false, cycle: {again: true, key: _dcsKey('rack', 'rA', 'kA'),
                                                  pila: [{kind: 'rack', room: 'rA', uid: 'kA'},
                                                         {kind: 'room', room: '', uid: 'rA'}]}});
__out.trasCiclo = [_dcsSel, _dcsItem];
__out.cicloPrimeraVez = _dcsCycle({moved: false, cycle: {again: false, key: 'x', pila: [{}, {}]}});

// Al fondo: tenue y fuera del puntero, con su chip para traerlo.
p2dSendBack('floor', 'rack', 'rA', 'kA');
__out.alFondo = [_dcsIsBack('rack', 'rA', 'kA'), _dcsInside(_dcsRooms()[1]).includes('ss-dcp-back'),
                 p2dBackChip(_dcsP2d).includes('p2dBringAll(')];
p2dBringAll('floor');
__out.traidas = _dcsP2d.back.size;

// El teclado: las flechas mueven lo elegido; Supr sobre una sala pregunta antes de sacarla.
_dcsMakePrimary({kind: 'rack', room: 'rA', uid: 'kA'});
const kA = _dcsPlan.content.rA.racks[0];
const ev2 = (o) => Object.assign({key: '', shiftKey: false, ctrlKey: false, metaKey: false, altKey: false}, o);
__out.flecha = p2dKeyDown(_dcsP2d, ev2({key: 'ArrowRight'}));
__out.flechaMayus = p2dKeyDown(_dcsP2d, ev2({key: 'ArrowDown', shiftKey: true}));
clearTimeout(_dcsP2d.arrowTimer);
__out.trasFlechas = [kA.pos_x, kA.pos_y];
let pregunta = '';
showConfirmModal = (texto) => { pregunta = texto; };
_dcsMakePrimary({kind: 'room', room: '', uid: 'rB'});
__out.suprSala = p2dKeyDown(_dcsP2d, ev2({key: 'Delete'}));
__out.pregunta = pregunta;

// Las filas de cada sala, con sus avisos.
_dcsMakePrimary(null);
__out.filas = _dcsRowsHtml();
__out.panelFilas = _dcsFloorPanel().includes('data-dcsrows');

// El fichero de la planta.
const fichero = _dcsExportJson();
__out.exportado = [fichero.kind, fichero.rooms.length, fichero.rooms.filter(r => r.area).length,
                   (fichero.rooms.find(r => r.name === 'Sala A') || {racks: []}).racks.map(k => k.name)];
__out.esPlanta = [_dcsIsFloorFile(fichero), _dcsIsFloorFile({racks: []}),
                  _dcsIsFloorFile({kind: 'floor', rooms: ['x']})];

// ── El encuadre al abrir: lo que hay, no el origen ──
// Un plano calibrado a 35 m del origen, sin nada más en la planta.
_dcsPlan = {site: {uid: 's3', rooms: []}, floors: [{uid: 'p3', plan_mm: 175000, plan_x: -46, plan_y: 35573}],
            floor: 'p3', kinds: {}, content: {}, walls: {},
            image: {data: 'data:image/png;base64,AAAA', ratio: 0.6}};
const S3 = _DCP_SCALE, ePlanta = _dcsExtent();
__out.encuadrePlanta = [Math.round(ePlanta.y / S3), Math.round((ePlanta.y + ePlanta.height) / S3),
                        Math.round(ePlanta.height / S3)];
// La zona general abierta como sala: sin medidas, con el plano de la planta lejos del origen.
_dcimPlan = {room: {uid: 'zg', name: 'Zona'}, racks: [],
             planFloor: {plan_mm: 175000, plan_x: -46, plan_y: 35573},
             image: {data: 'data:image/png;base64,AAAA', ratio: 0.6}};
_dcpFeat = {kinds: {}, features: [], items: []};
const plano = _dcpPlanBox();
const eZona = _dcpExtent([]);
__out.encuadreZona = [eZona.y / S3 <= plano.y && eZona.y / S3 > plano.y - 1000,
                      (eZona.y + eZona.height) / S3 >= plano.y + plano.h];
// Una sala con medidas sigue encuadrándose desde su esquina.
_dcimPlan = {room: {uid: 'sm', width_mm: 6000, depth_mm: 4000}, racks: []};
const eSala = _dcpExtent([]);
__out.encuadreSala = [eSala.x <= 0, eSala.y <= 0,
                      eSala.x + eSala.width >= 6000 * S3, eSala.y + eSala.height >= 4000 * S3];

// ── El historial no es del inventario: cualquier fuente sirve ──
const enviados2 = [];
const filaX = {uid: 'x', pos_x: 1};
const fuente = {items: () => [['/otra/x', filaX]],
                send: (m, u, b) => { enviados2.push([m, u, b]); return Promise.resolve({ok: true}); },
                rerender: () => {}, may: () => true, keysActive: () => false};
p2duPrime('otra-pantalla', fuente);
filaX.pos_x = 5;
p2duRecord('/otra/x', p2duBefore('/otra/x', {pos_x: 5}), {pos_x: 5});
__out.ajenaApunta = [P2DU.stack.length, P2DU.stack[0] && P2DU.stack[0].before];
p2du('undo');
__out.ajenaDeshace = enviados2;
__out.ajenaBotones = p2duButtons().includes('p2dUndoBtns');

// ── El plano de fondo tampoco es del inventario: otra pantalla lo calibra con sus rutas ──
const guardados = [], empezados = [];
const recX = {uid: 'pX', plan_mm: 0, plan_x: 0, plan_y: 0};
const imgX = {data: 'data:image/png;base64,AAAA', ratio: 0.5};
const fondo = {scale: 0.5, may: () => true, mediaUrl: n => '/otra/media/' + n,
               planUrl: (s, u) => `/otra/${s}/${u}/plano`, planSet: () => Promise.resolve(),
               target: k => k === 'pl' ? {rec: recX, box: p2dPlanBox(recX, imgX, 8000), img: imgX,
                                          svg: 'otraSvg', url: '/otra/planos/pX', redraw: () => {}} : null,
               anchors: () => [{x: 0, y: 0}],
               start: k => empezados.push(k),
               save: (u, b) => { guardados.push([u, b]); return Promise.resolve({ok: true}); },
               rerender: () => {}};
p2dBgUse(fondo);
p2dCalStart('pl');
Object.assign(P2DCAL, {a: {u: 0, v: 0}, b: {u: 0.5, v: 0}, dist: '10', step: 'dist'});
p2dCalApply();
p2dCalSave(true);
__out.fondoAjeno = [empezados, guardados];
const herramientas = p2dPlanFileTools('cosas', 'u1', true);
__out.fondoRutas = [herramientas.includes('p2dPlanFile-cosas'), herramientas.includes('dcim')];
__out.fondoEscala = p2dPlanImageSvg({x: 10, y: 0, w: 100, h: 50, scaled: true}, imgX).includes('x="5"');
fondo.may = () => false;
__out.fondoSinPermiso = p2dPlanFileTools('cosas', 'u1', true);
p2dBgUse(_dcPlanSrc);

// ── Exportar e importar, un grupo; guardar como, un botón con sus formatos ──
const conJson = {input: 'fx', exportFn: 'exp()', importFn: 'imp(this)', exportTt: 'E', importTt: 'I'};
__out.jsonEdita = p2dJsonTools(Object.assign({canImport: true}, conJson));
__out.jsonMira = p2dJsonTools(Object.assign({canImport: false}, conJson));
__out.guardarComo = ssCanvasTools('lienzoX', 'plano');

// ── Un rack soltado en otra sala de la planta: vuelve, se pregunta, y si se confirma cambia ──
_dcimPlan = null;
_dcsPlan = {site: {uid: 's3', rooms: [
                {uid: 'z3', floor_uid: 'p3', name: 'Zona'},
                {uid: 'q1', floor_uid: 'p3', name: 'Sala 1', pos_x: 0, pos_y: 0, width_mm: 4000, depth_mm: 3000, rotation: 0},
                {uid: 'q2', floor_uid: 'p3', name: 'Sala 2', pos_x: 5000, pos_y: 0, width_mm: 4000, depth_mm: 3000, rotation: 0}]},
            floors: [{uid: 'p3', area_uid: 'z3'}], floor: 'p3', kinds: {},
            content: {q1: {racks: [{uid: 'kq', name: 'R07', pos_x: 1000, pos_y: 1000, width_mm: 600,
                                    depth_mm: 1000, rotation: 0}], features: [], items: []},
                      q2: {racks: [], features: [], items: []}, z3: {racks: [], features: [], items: []}}};
const rq = _dcsPlan.content.q1.racks[0];
const preguntas3 = [], envios3 = [];
showConfirmModal = (texto, si) => { preguntas3.push(texto); return si(); };
_dcimSend = (m, u, b) => { envios3.push([m, u, b]); return Promise.resolve({ok: true}); };
_dcsReload = () => {}; _dcsRedraw = () => {};
const mq = {kind: 'rack', room: 'q1', uid: 'kq', at: {x: 1000, y: 1000}};
rq.pos_x = 6000;                      // its centre, 6300 mm of the floor, in Sala 2
const tomada = _dcsRackDropped({members: [mq]});
__out.otraSala = {tomada, vuelve: [rq.pos_x, rq.pos_y], pregunta: preguntas3.length, envio: envios3[0]};
rq.pos_x = 2000;                      // still in Sala 1
__out.mismaSala = _dcsRackDropped({members: [mq]});
__out.variosNo = _dcsRackDropped({members: [mq, {kind: 'rack', room: 'q1', uid: 'otro', at: {x: 0, y: 0}}]});
"""


@pytest.fixture(scope='module')
def out():
    """One `node` run for the whole module: starting it costs more than looking."""
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


@pytest.mark.skipif(shutil.which('node') is None, reason='no node to run the script with')
class TestInTheBrowser:

    def test_an_edge_snaps_to_the_face_it_comes_close_to(self, out):
        assert out['pegado']['y'] == 130, 'its bottom on the aisle\'s top: 1130 - 1000'
        assert out['pegado']['x'] == 0, 'and its left lined up with the aisle\'s'

    def test_a_rack_joins_the_one_beside_it(self, out):
        assert out['lado']['x'] == 600

    def test_what_is_far_in_the_other_axis_is_not_a_neighbour(self, out):
        assert out['lejos']['x'] is None

    def test_beyond_the_margin_nothing_snaps(self, out):
        assert out['fuera']['x'] is None and out['fuera']['y'] is None

    def test_dragging_snaps_to_the_neighbour_before_the_tile(self, out):
        assert out['conImanCosas'] == {'x': 0, 'y': 130}
        assert {'y': 1130} in out['guias']

    def test_alt_leaves_only_the_tile(self, out):
        assert out['conAlt'] == {'x': 0, 'y': 0}

    def test_a_turned_thing_snaps_by_the_box_that_is_seen(self, out):
        # 600 × 1000 turned a quarter is 1000 × 600 on screen: 200 mm of offset each way. Its
        # seen bottom (y + 200 + 600) goes onto the aisle's top at 1130.
        assert out['girado']['y'] == 1130 - 600 - 200

    def test_guides_go_with_the_hand(self, out):
        assert out['guiasSinMano'] == ''

    def test_shift_click_adds_and_a_second_one_takes_out(self, out):
        assert out['mayus'] is True
        assert out['elegidos'] == ['rack:k1', 'rack:k2']
        assert 'data-p2dmany' in out['panel']
        assert out['quitado'] == ['rack:k1']

    def test_a_plain_click_on_a_loose_thing_is_the_ordinary_path(self, out):
        assert out['clicSuelto'] is False
        assert out['trasClicSuelto'] == 0

    def test_the_box_shows_the_first_time_too(self, out):
        """Reported: the first drag after loading drew no box; the second did. With nothing
        chosen yet, the drawing returned before the box."""
        assert out['primerRecuadro']

    def test_a_box_picks_what_it_touches(self, out):
        assert out['recuadro'] == ['feature:f1', 'rack:k1']

    def test_a_group_is_picked_whole_and_moves_together(self, out):
        assert out['grupo'] == ['feature:f1', 'rack:k1']
        assert out['cogeGrupo'] is True
        assert out['arrastre'] == ['many', 2]
        # The aisle (grabbed) goes to the tile: 2000 → 1800, 4130 → 4200; the rack, the same
        # 1800 × 3070 move.
        assert out['movidos'] == [1800, 3070, 1800, 4200]

    def test_moving_several_is_one_undo(self, out):
        assert out['lote'] == [2, 2]
        assert out['loteTitulo']
        assert out['loteDeshecho'] == [1800, 1800]
        assert out['loteRehecho'] == [2600, 2600]
        assert out['unoNoLote']

    def test_the_history_is_the_editors_not_the_inventorys(self, out):
        """Any screen with a source of its own gets undo: what it records, what undo sends."""
        assert out['ajenaApunta'] == [1, {'pos_x': 1}]
        assert out['ajenaDeshace'] == [['PUT', '/otra/x', {'pos_x': 1}]]
        assert out['ajenaBotones']

    def test_export_and_import_are_one_group_of_one_style(self, out):
        """Asked for: export and import went apart, each with an icon of its own style. They are
        one group, download and upload; the file control sits outside it (inside, it would be the
        group's last child and square the import button's corners); a viewer gets export only."""
        h = out['jsonEdita']
        grupo = h[h.index('btn-group'):]
        assert grupo.count('<button') == 2 and 'bi-download' in grupo and 'bi-upload' in grupo
        assert h.index('type="file"') < h.index('btn-group')
        assert 'bi-filetype-json' not in h
        assert out['jsonMira'].count('<button') == 1 and 'type="file"' not in out['jsonMira']
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        dcim = os.path.join(src, 'lib', 'web_admin', 'templates', 'partials', 'dcim')
        for f in ('_plan.html', '_siteplan.html'):
            assert 'p2dJsonTools({' in io.open(os.path.join(dcim, f), encoding='utf-8').read(), f

    def test_save_as_is_one_button_with_its_formats(self, out):
        """Asked for: PNG and SVG were two buttons; «save as» is one, with a menu of both."""
        h = out['guardarComo']
        menu = h[h.index('dropdown-toggle'):]
        assert 'data-bs-toggle="dropdown"' in menu
        assert "'png'" in menu and "'svg'" in menu and menu.count('dropdown-item') == 2
        assert h.count('<button') == 4, 'three to look, one to save'

    def test_a_rack_dropped_in_another_room_asks_and_then_moves(self, out):
        """Asked for: dragging a rack into another room changes its room, with a confirmation
        first. It goes back to its place, the question is asked, and confirmed it is moved to the
        other room where it was dropped (its centre in the new room's frame). Dropped in its own
        room, or several at once, it is saved as ever."""
        o = out['otraSala']
        assert o['tomada'] is True and o['vuelve'] == [1000, 1000] and o['pregunta'] == 1
        assert o['envio'][:2] == ['PUT', '/api/v1/dcim/racks/kq']
        assert o['envio'][2] == {'room_uid': 'q2', 'pos_x': 1000, 'pos_y': 1000, 'rotation': 0}
        assert out['mismaSala'] is False and out['variosNo'] is False
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        motor = io.open(os.path.join(src, 'lib', 'core', 'plan2d', 'web', '_plan2d.html'), encoding='utf-8').read()
        assert 'if (P.ad.dropped && P.ad.dropped(drag)) return;' in motor

    def test_the_background_plan_is_the_editors_not_the_inventorys(self, out):
        """Any screen with a source of its own calibrates its background plan: what it shows to
        start, where the scale is saved, and its own upload buttons, scale and permission."""
        assert out['fondoAjeno'] == [['pl'], [['/otra/planos/pX', {'plan_mm': 20000, 'plan_x': 0, 'plan_y': 0}]]]
        assert out['fondoRutas'] == [True, False]
        assert out['fondoEscala'] is True
        assert out['fondoSinPermiso'] == ''

    def test_a_room_item_is_undone_too_and_drawn_from_its_box(self, out):
        assert out['equipoEnDeshacer']
        assert out['cajaEquipo'] == [100, 200]

    def test_the_minted_group_id_is_one_the_server_takes(self, out):
        assert out['idGrupo']

    def test_room_arrows_stop_at_the_wall_that_is_seen(self, out):
        """A door turned a quarter is drawn 440 mm right of its stored corner: the arrow takes its
        visible edge to the wall, not the corner."""
        assert out['flechaEsDeAqui'] is True
        assert out['flechaPared'] == -440

    def test_room_keys_reach_each_kind(self, out):
        """R and Delete were for pieces only; through the engine they turn a rack and remove a
        room item too, each by its own route."""
        assert out['teclasSala'] == ['k2', 'i1']

    def test_escape_lets_go_of_anything(self, out):
        assert out['escape'] == [True, None]


@pytest.mark.skipif(shutil.which('node') is None, reason='no node to run the script with')
class TestPointerModeAndTheFloor:
    """Asked for: a button so that dragging in empty space chooses instead of moving the view —
    in the room's plan and the floor's—, and the floor's list naming what is on it, not only its
    rooms."""

    def test_choose_mode_boxes_and_the_middle_button_still_pans(self, out):
        assert out['modoElegir'] == [True, False]

    def test_choose_mode_changes_the_cursor(self):
        """Reported: switching to choose mode left the cursor as the hand that moves the view."""
        src = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        css = io.open(os.path.join(src, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'),
                      encoding='utf-8').read()
        assert '.ss-infra-canvas.ss-pick-mode { cursor: crosshair; }' in css
        dcim = os.path.join(src, 'lib', 'web_admin', 'templates', 'partials', 'dcim')
        for f in ('_plan.html', '_siteplan.html'):
            assert 'ss-infra-canvas position-relative${p2dPointerClass(' in                 io.open(os.path.join(dcim, f), encoding='utf-8').read(), f

    def test_the_cursor_class_follows_the_mode(self, out):
        assert out['cursorElegir'] == [' ss-pick-mode', ''], 'not in a view where the mode does not apply'
        assert out['cursorMover'] == ''

    def test_pan_mode_boxes_only_with_shift(self, out):
        assert out['modoMover'] == [False, True]
        assert 'data-p2dpointer="pan"' in out['botones'] and 'data-p2dpointer="select"' in out['botones']

    def test_a_thing_in_a_turned_room_is_where_it_is_drawn(self, out):
        assert sorted(out['esquinas']) == sorted([[4000, 0], [4000, 600], [3000, 600], [3000, 0]])

    def test_a_box_takes_what_it_touches_and_a_room_only_whole(self, out):
        assert out['recuadroRack'] == ['rack|k9']
        assert out['recuadroTodo'] == ['rack|k9', 'ritem|i9', 'room|r1']

    def test_a_move_on_the_floor_reaches_a_turned_room_turned_back(self, out):
        assert out['giradoDeVuelta'] == [0, -1000]

    def test_what_is_in_a_moving_room_moves_with_it_not_twice(self, out):
        assert out['conSuSala'] == [1500, 0, -1000]

    def test_several_on_the_floor_are_outlined_and_can_be_grouped(self, out):
        assert out['plantaElegidos'] == ['rack|k9', 'ritem|i9']
        assert out['plantaContornos'] == 2
        assert out['plantaPanel']

    def test_the_floor_lists_its_things_room_by_room(self, out):
        lista = out['lista']
        assert 'data-dcselem="rack"' in lista and 'data-dcselem="ritem"' in lista
        assert 'R09' in lista and 'Imp-1' in lista
        assert 'data-dcselem="rack"' in out['panelPlanta'], 'the inspector of the floor does not show it'

    def test_the_floor_list_holds_everything_on_the_plan(self, out):
        """Asked for: the list shows everything put on the plan. An empty room is there, and its
        heading picks it (the general area is no room that is placed, and is not picked); the
        stairs or the lift; and the walls, with how many, opening their review for an editor."""
        t = out['listaToda']
        assert t['vacia'] and t['salaElige'] and t['zonaNoSeElige']
        assert t['nucleo'] and t['muros']

    def test_picking_one_leaves_the_rest(self, out):
        assert out['trasSoltar'] == 0


@pytest.mark.skipif(shutil.which('node') is None, reason='no node to run the script with')
class TestTheFloorEditsLikeARoom:
    """Asked for: the floor editor with the room editor's tools — the snap to neighbours, a press
    again for what is underneath and «send to back», the keys, the rows and their warnings, and
    the plan to and from JSON. One editor; each screen with its own things."""

    def test_a_room_snaps_to_the_room_beside_it(self, out):
        assert out['salaPegada'] == {'dx': -100, 'dy': 0}
        assert {'x': 4000} in out['salaGuias']

    def test_alt_leaves_only_the_steps(self, out):
        assert out['salaAlt'] == {'dx': 0, 'dy': 0}

    def test_a_rack_snaps_to_the_one_beside_it(self, out):
        assert out['rackPegado'] == {'dx': -50, 'dy': 0}

    def test_a_second_press_goes_to_what_is_underneath(self, out):
        assert out['ciclo'] is True
        assert out['trasCiclo'] == ['rA', None]
        assert out['cicloPrimeraVez'] is False

    def test_send_to_back_and_bring_back(self, out):
        assert out['alFondo'] == [True, True, True]
        assert out['traidas'] == 0

    def test_arrows_move_and_shift_moves_a_metre(self, out):
        assert out['flecha'] is True and out['flechaMayus'] is True
        assert out['trasFlechas'] == [200, 1100]

    def test_delete_on_a_room_asks_before_taking_it_off(self, out):
        assert out['suprSala'] is True
        assert 'Sala B' in out['pregunta']

    def test_rows_are_listed_by_room_with_their_warnings(self, out):
        assert 'data-dcsrowwarn' in out['filas'] and 'Sala A' in out['filas']
        assert '_dcsRowNew(' in out['filas'] and '_dcsRowEdit(' in out['filas']
        assert out['panelFilas']

    def test_a_floor_opens_on_what_is_there_not_on_the_origin(self, out):
        """Reported: the floor opened with its plan stuck to the bottom and half the window
        empty — the frame always began at (0, 0), and a plan 35 m from it had 35 m of nothing
        above. Now it spans the plan alone, with its margin."""
        arriba, abajo, alto = out['encuadrePlanta']
        assert 34000 < arriba < 35573, arriba
        assert abajo >= 35573 + 175000 * 0.6
        assert alto < 175000 * 0.6 + 3000

    def test_the_general_area_does_not_frame_the_origin_either(self, out):
        assert out['encuadreZona'] == [True, True]

    def test_a_room_with_a_size_still_frames_from_its_corner(self, out):
        assert out['encuadreSala'] == [True, True, True, True]

    def test_the_floor_goes_to_a_file_room_by_room(self, out):
        assert out['exportado'] == ['floor', 3, 1, ['RA1', 'RA2']]
        assert out['esPlanta'] == [True, False, False]
