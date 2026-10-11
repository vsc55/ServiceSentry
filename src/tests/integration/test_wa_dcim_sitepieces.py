#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las piezas sueltas de una planta: estirarlas, y su zona general con el plano de la planta. En
`node`, sobre el guion del panel.

Reportado desde la pantalla: en el plano de la planta no se podía hacer más grande una puerta
—las piezas no tenían asas—, y al entrar en la zona general de la planta, que es donde se editan
las piezas sueltas, el plano de fondo desaparecía. Lo que fijan estas pruebas:

- una pieza delgada (una puerta) lleva solo las asas de los lados: las esquinas tapaban las otras;
- en el plano de la planta, la pieza elegida lleva asas y se estira con la cuenta de siempre,
  también dentro de una sala girada, y se guarda su medida y su sitio; un rack no lleva;
- la zona general de una planta sin plano propio usa el de la planta, con su calibración.
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
                                reason='sin node: no hay con qué ejecutar el guion')

_PRUEBA = r"""
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
_dcimData = {orgs: [], sites: []};
renderDcim = () => {};
const enviados = [];
_dcimSend = (metodo, url, cuerpo) => { enviados.push({url, cuerpo}); return Promise.resolve({ok: true}); };
const S = _DCP_SCALE;
__out = {};

// ── Una puerta: un metro por doce centímetros ───────────────────────────────────
const asas = (html) => (html.match(/data-dcph=/g) || []).length;
__out.asasPuerta = asas(_dcpHandles(1000 * S, 120 * S, 0));
__out.asasMesa = asas(_dcpHandles(1200 * S, 800 * S, 0));

// ── En el plano de la planta ────────────────────────────────────────────────────
const puerta = {uid: 'f1', kind: 'door', pos_x: 1000, pos_y: 2000, width_mm: 1000, depth_mm: 120,
                rotation: 0};
const girada = {uid: 'f2', kind: 'door', pos_x: 0, pos_y: 0, width_mm: 1000, depth_mm: 120,
                rotation: 0};
_dcsPlan = {site: {uid: 's', rooms: [{uid: 'z0', floor_uid: 'p'},
                                     {uid: 'r9', floor_uid: 'p', rotation: 90, pos_x: 5000,
                                      pos_y: 0, width_mm: 4000, depth_mm: 3000}]},
            floors: [{uid: 'p', area_uid: 'z0'}], floor: 'p', image: null, kinds: {},
            content: {z0: {racks: [{uid: 'k1', pos_x: 0, pos_y: 0}], features: [puerta]},
                      r9: {racks: [], features: [girada]}}};
_dcsItem = {kind: 'feature', uid: 'f1', room: 'z0'};
__out.conAsas = asas(_dcsThing('feature', puerta, 'z0', 1000, 120, _dcpLook('door'), 'Puerta')) > 0;
_dcsItem = {kind: 'rack', uid: 'k1', room: 'z0'};
__out.rackSinAsas = asas(_dcsThing('rack', {uid: 'k1', pos_x: 0, pos_y: 0}, 'z0', 600, 1000,
                                   {fill: 'x', line: 'y'}, 'R')) === 0;

// Un asa de la derecha, cogida y llevada un metro más allá.
ssCanvasPoint = (svg, ev) => ev.p;
const grupoDe = (uid, room) => ({dataset: {dcsi: 'feature', uid, room}});
const asaDe = (lado, g) => ({dataset: {dcph: lado},
                             closest: (sel) => (sel === '[data-dcph]' ? asaDe(lado, g)
                                                : sel === 'g[data-dcsi]' ? g : null)});
const pulsar = (lado, g, mx, my) => ({target: asaDe(lado, g), p: {x: mx * S, y: my * S},
                                      currentTarget: {setPointerCapture() {}, style: {}},
                                      clientX: 0, clientY: 0, type: 'pointerup'});
_dcsDown(pulsar('e', grupoDe('f1', 'z0'), 2000, 2060));
_dcsMove({p: {x: 3000 * S, y: 2060 * S}});
__out.estirada = [puerta.width_mm, puerta.depth_mm, puerta.pos_x, puerta.pos_y];
_dcsUp({type: 'pointerup', clientX: 0, clientY: 0, currentTarget: {style: {}}});
__out.guardada = enviados[0];

// Dentro de una sala girada 90°: su «derecha» es hacia abajo de la planta.
enviados.length = 0;
_dcsItem = {kind: 'feature', uid: 'f2', room: 'r9'};
_dcsDown(pulsar('e', grupoDe('f2', 'r9'), 0, 0));
_dcsMove({p: {x: 0, y: 1000 * S}});
__out.girada = girada.width_mm;

// ── La zona general lleva el plano de su planta ─────────────────────────────────
_dcsPlan = null;
_dcimPlan = {room: {uid: 'z0', site_uid: 's', width_mm: 0}, racks: [],
             image: {data: 'data:image/png;base64,AAAA', ratio: 0.5},
             planFloor: {uid: 'p', plan: 'x.png', plan_mm: 40000, plan_x: -1000, plan_y: -500,
                         north_deg: 30}};
_dcpFeat = {features: [], kinds: {}};
const b = _dcpPlanBox();
__out.zona = [b.w, b.x, b.y, b.scaled];
__out.zonaNorte = _dc3dNorth();
__out.zonaOjo = _dcimPlanHtml().includes('_dcPlanBgToggle()');

// ── The floor's palette: everything a room's has, and the stairs and the lift ───
_dcimPlan = null;
const impresora = {uid: 'i1', role: 'printer', label: 'IMP-1', pos_x: 500, pos_y: 500, rotation: 0,
                   box: {w: 520, d: 480}};
const detector = {uid: 'f9', kind: 'smoke_detector', pos_x: 100, pos_y: 100, width_mm: 120, depth_mm: 120,
                  rotation: 0};
_dcsPlan = {site: {uid: 's', rooms: [{uid: 'rc', floor_uid: 'p', pos_x: 0, pos_y: 0, width_mm: 40000,
                                      depth_mm: 30000, rotation: 0}]},
            floors: [{uid: 'p', area_uid: ''}], floor: 'p', image: null,
            kinds: {zone: {w: 2000, d: 2000, layer: 'floor'}, smoke_detector: {w: 120, d: 120, layer: 'air'}},
            content: {rc: {racks: [], features: [detector], items: [impresora]}}};
const paleta = _dcsPaletteHtml();
__out.paleta = {aire: paleta.includes('_dcsAdd("smoke_detector")') || paleta.includes("_dcsAdd('smoke_detector')")
                      || paleta.includes('_dcsAdd(&quot;smoke_detector&quot;)'),
                equipos: (paleta.match(/_dcsAddItem\(/g) || []).length,
                escalera: paleta.includes("_dcsCoreAdd('stairs')"),
                ascensor: paleta.includes("_dcsCoreAdd('lift')")};
const dentro = _dcsInside(_dcsPlan.site.rooms[0]);
__out.dibuja = {equipo: dentro.includes('data-dcsi="ritem"') && dentro.includes('data-uid="i1"'),
                techo: dentro.includes('data-uid="f9"')};
__out.urls = [_dcsItemUrl('ritem', 'i1'), _dcsItemUrl('ritem', 'i1', true), _dcsItemUrl('feature', 'f9')];
_dcsItem = {kind: 'ritem', uid: 'i1', room: 'rc'};
__out.fila = (_dcsItemRow() || {}).label;
enviados.length = 0;
_dcsReload = async () => {};
ssCanvasWindow = () => ({x: 0, y: 0, w: 20000 * S, h: 15000 * S});
_dcsAddItem('printer');
__out.puesta = enviados.map(e => [e.url, (e.cuerpo || {}).role]);
// The stairs: the palette's button asks where, the click puts it there, and the plan draws it —
// also on a floor that already had one. Dragged, it moves and is saved.
const encolados = [];
_dcpQueue = (url, cuerpo) => encolados.push([url, cuerpo]);
_dcsInspectorDraw = () => {};
_dcsRedraw = () => {};
showToast = () => {};
_dcsPlan.floors[0] = {uid: 'p', area_uid: '', core_kind: 'lift', core_x: 1000, core_y: 1000};
_dcsCoreAdd('stairs');
const marcando = _dcsCoreMark;
_dcsDown({target: {closest: () => null}, p: {x: 12000 * S, y: 8000 * S}, currentTarget: {style: {}}});
const f = _dcsFloor();
const tras = [f.core_kind, f.core_x, f.core_y];
const dibujo = _dcsCoreSvg();
// Dragged two metres to the right.
_dcsDown({target: {closest: (sel) => (sel === '[data-dcscore]' ? {} : null)}, p: {x: 12000 * S, y: 8000 * S},
          currentTarget: {style: {}, setPointerCapture() {}}, pointerId: 1});
_dcsMove({p: {x: 14000 * S, y: 8000 * S}});
_dcsUp({type: 'pointerup', clientX: 0, clientY: 0, currentTarget: {style: {}}});
__out.escalera = {marcando, tras, dibuja: dibujo.includes('data-dcscore'),
                  peldanos: (dibujo.match(/<line/g) || []).length, movida: [f.core_x, f.core_y],
                  guardada: encolados.filter(e => 'core_x' in e[1]).pop()};
"""


@pytest.fixture(scope='module')
def out():
    """Una sola ejecución de `node` para todo el módulo: arrancarlo cuesta más que mirar."""
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
    return node_run(panel_bundle(c), _PRUEBA)


class TestLaPaletaDeLaPlanta:
    """Reportado: en el plano de una planta no había cómo poner impresoras, escaleras ni otras
    cosas que la demo sí tiene. Su paleta trae ahora lo mismo que la de una sala —cada tipo de
    pieza, también las del techo, y los equipos de sala— y los botones de la escalera y el
    ascensor (el núcleo de la planta). Los equipos de sala se dibujan en la planta, se eligen y se
    guardan por su ruta."""

    def test_la_paleta_trae_el_techo_los_equipos_y_el_nucleo(self, out):
        p = out['paleta']
        assert p['aire'] and p['equipos'] == 7 and p['escalera'] and p['ascensor']

    def test_los_equipos_y_el_techo_se_dibujan_en_la_planta(self, out):
        assert out['dibuja'] == {'equipo': True, 'techo': True}
        assert out['fila'] == 'IMP-1'

    def test_un_equipo_se_guarda_y_se_quita_por_su_ruta(self, out):
        assert out['urls'] == ['/api/v1/dcim/room-items/i1', '/api/v1/dcim/items/i1',
                               '/api/v1/dcim/features/f9']

    def test_la_escalera_se_marca_se_dibuja_y_se_mueve(self, out):
        """Reportado: «añadir escalera» no aparecía en ningún sitio. El plano no dibujaba el
        núcleo —solo el 3D— y el botón solo pedía sitio si la planta no tenía. Ahora siempre lo
        pide, el clic lo pone ahí, el plano lo dibuja con sus peldaños, y arrastrado se mueve y
        se guarda."""
        e = out['escalera']
        assert e['marcando'] is True and e['tras'] == ['stairs', 12000, 8000]
        assert e['dibuja'] and e['peldanos'] == 9
        assert e['movida'] == [14000, 8000]
        assert e['guardada'][0] == '/api/v1/dcim/floors/p' and e['guardada'][1] == {'core_x': 14000, 'core_y': 8000}

    def test_poner_una_impresora_la_pone_en_la_sala_que_se_mira(self, out):
        assert out['puesta'] == [['/api/v1/dcim/rooms/rc/items', 'printer']]


class TestUnaPiezaDelgada:
    def test_solo_las_asas_de_los_lados(self, out):
        assert out['asasPuerta'] == 4, 'las esquinas tapan las asas de los lados'
        assert out['asasMesa'] == 8


class TestEstirarEnElPlanoDeLaPlanta:
    def test_la_pieza_elegida_lleva_asas_y_un_rack_no(self, out):
        assert out['conAsas']
        assert out['rackSinAsas']

    def test_se_estira_desde_su_asa(self, out):
        assert out['estirada'] == [2000, 120, 1000, 2000]

    def test_y_se_guarda_medida_y_sitio(self, out):
        g = out['guardada']
        assert g['url'] == '/api/v1/dcim/features/f1'
        assert g['cuerpo'] == {'width_mm': 2000, 'depth_mm': 120, 'pos_x': 1000, 'pos_y': 2000}

    def test_dentro_de_una_sala_girada(self, out):
        assert out['girada'] == 2000


class TestLaZonaGeneralLlevaElPlanoDeSuPlanta:
    def test_con_la_calibracion_de_la_planta(self, out):
        assert out['zona'] == [40000, -1000, -500, True]

    def test_y_su_norte(self, out):
        assert out['zonaNorte'] == 30

    def test_y_el_ojo_para_ocultarlo(self, out):
        assert out['zonaOjo']
