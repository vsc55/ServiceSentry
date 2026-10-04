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
