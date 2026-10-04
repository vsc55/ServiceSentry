#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las estanterías de un armario en su ficha, en `node` sobre el guion del panel.

Se pidió: un armario con su número de estanterías, y poder apuntar el material de cada una. Lo
que fijan estas pruebas (la API la fija `TestLasEstanteriasDeUnArmario` en `test_wa_dcim.py`):

- solo un armario lleva el bloque, y lo pide al servidor una vez;
- se pintan todas sus estanterías de arriba abajo, cada una con lo suyo o «vacía»;
- quien solo mira no ve los controles de editar;
- guardar manda lo escrito, y una cosa sin nombre no sale;
- quitar el armario avisa de lo que se lleva dentro.
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
const pedidas = [], enviados = [];
apiGet = (url) => { pedidas.push(url); return new Promise(() => {}); };
_dcimSend = (metodo, url, cuerpo) => { enviados.push({metodo, url, cuerpo}); return new Promise(() => {}); };
let avisos = [];
showToast = (m) => { avisos.push(m); };
__out = {};

// ── Solo un armario, y se pide una vez ──────────────────────────────────────────
__out.puertaNada = _dcShelfBox({uid: 'p', kind: 'door'}) === '';
_dcShelf = null;
_dcShelfBox({uid: 'a1', kind: 'cabinet'});
_dcShelfBox({uid: 'a1', kind: 'cabinet'});
__out.pedida = pedidas.slice();

// ── Las estanterías, de arriba abajo ────────────────────────────────────────────
_dcShelf = {uid: 'a1', shelves: 3, adding: 0, editing: '',
            items: [{uid: 'i1', shelf: 1, label: 'SFP', qty: 4, notes: '10G'},
                    {uid: 'i2', shelf: 3, label: 'Tornillos', qty: 100, notes: ''}]};
const html = _dcShelfBox({uid: 'a1', kind: 'cabinet'});
__out.tres = [1, 2, 3].every(n => html.includes(tf('dcim_shelf_n', n)));
__out.orden = html.indexOf(tf('dcim_shelf_n', 1)) < html.indexOf('SFP')
    && html.indexOf('SFP') < html.indexOf(tf('dcim_shelf_n', 2))
    && html.indexOf(tf('dcim_shelf_n', 3)) < html.indexOf('Tornillos');
__out.vacia = html.includes(t('dcim_shelf_empty'));
__out.cantidad = html.includes('×4') && html.includes('×100');
__out.conControles = html.includes('_dcShelfCount(') && html.includes('_dcShelfStartAdd(2)');

// ── Quien solo mira ─────────────────────────────────────────────────────────────
currentUser = {permissions: ['dcim_view']};
const lectura = _dcShelfInner();
__out.soloMira = !lectura.includes('_dcShelfCount(') && !lectura.includes('_dcShelfEdit(')
    && lectura.includes('SFP');
currentUser = {permissions: ['dcim_view', 'dcim_edit']};

// ── Guardar ─────────────────────────────────────────────────────────────────────
const campos = {'dcsh-l': {value: ' Cable Cat6 '}, 'dcsh-q': {value: '3'}, 'dcsh-s': {value: '2'},
                'dcsh-n': {value: 'rollo de 305 m'}};
const getOrig = document.getElementById;
document.getElementById = (id) => campos[id] || null;
_dcShelfSave('');
__out.nuevo = enviados[0];
campos['dcsh-l'].value = '   ';
_dcShelfSave('');
__out.sinNombre = enviados.length === 1 && avisos.includes(t('dcim_name_required'));
document.getElementById = getOrig;

// ── El dibujo ───────────────────────────────────────────────────────────────────
const kinds = {cabinet: {h: 2000, layer: 'room', front: true}, bench: {h: 750, layer: 'room', front: true},
               door: {h: 2100, layer: 'room'}};
_dcpFeat = {features: [], kinds};
_dcpSel = null;
const mesa = _dcpFeature({uid: 'b', kind: 'bench', pos_x: 0, pos_y: 0, width_mm: 1600, depth_mm: 800});
const puerta = _dcpFeature({uid: 'd', kind: 'door', pos_x: 0, pos_y: 0, width_mm: 1000, depth_mm: 120});
__out.mesaFrente = mesa.includes('fill="var(--bs-primary)"') && mesa.includes('stroke-dasharray="3 2"');
__out.puertaSinFrente = !puerta.includes('fill="var(--bs-primary)"');
// De frente, las baldas: tres estanterías son dos líneas entre ellas.
__out.baldasFrente = (_dcpElevShelves({shelves: 3}, 0, 0, 10, 30).match(/<line/g) || []).length;
__out.unaSinLineas = _dcpElevShelves({shelves: 1}, 0, 0, 10, 30) === '';
// En 3D, el armario abierto: fondo, dos lados, techo y una tabla por estantería.
const caja3 = _dc3dRoomBoxes({}, [], [{uid: 'a', kind: 'cabinet', pos_x: 0, pos_y: 0, width_mm: 1000,
                                         depth_mm: 500, shelves: 3}], kinds,
                              {walls: false, floor: false, tiles: false});
__out.armario3d = caja3.cajas.length;
const mesa3 = _dc3dRoomBoxes({}, [], [{uid: 'm', kind: 'bench', pos_x: 0, pos_y: 0}], kinds,
                             {walls: false, floor: false, tiles: false});
__out.mesa3d = [mesa3.cajas.length, mesa3.cajas.some(k => k.color === _DC3_COLOR.front)];

// ── El nombre nunca boca abajo ──────────────────────────────────────────────────
const conGiro = (rot) => _dcpFeature({uid: 'x', kind: 'bench', label: 'Mesa', pos_x: 0, pos_y: 0,
                                      width_mm: 1600, depth_mm: 800, rotation: rot});
const volteado = (html) => /<text[^>]*rotate\(180/.test(html);
__out.giros = [0, 90, 180, 270].map(r => volteado(conGiro(r)));
__out.rackVolteado = volteado(_dcpRack({uid: 'k', name: 'Rack01', pos_x: 0, pos_y: 0,
                                        width_mm: 600, depth_mm: 1000, rotation: 180, roll: {}}));

// ── Quitar el armario avisa ─────────────────────────────────────────────────────
__out.aviso = _dcShelfDropWarning('a1');
__out.otroSinAviso = _dcShelfDropWarning('otro');
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


class TestLaFichaDelArmario:
    def test_solo_un_armario_y_se_pide_una_vez(self, out):
        assert out['puertaNada']
        assert out['pedida'] == ['/api/v1/dcim/features/a1/shelf']

    def test_todas_sus_estanterias_de_arriba_abajo(self, out):
        assert out['tres'] and out['orden']
        assert out['vacia'] and out['cantidad']

    def test_quien_edita_tiene_los_controles(self, out):
        assert out['conControles']

    def test_quien_solo_mira_no(self, out):
        assert out['soloMira']


class TestGuardarYQuitar:
    def test_guardar_manda_lo_escrito(self, out):
        n = out['nuevo']
        assert n['metodo'] == 'POST' and n['url'] == '/api/v1/dcim/shelf-items'
        assert n['cuerpo'] == {'feature_uid': 'a1', 'label': 'Cable Cat6', 'qty': 3, 'shelf': 2,
                               'notes': 'rollo de 305 m'}

    def test_sin_nombre_no_sale(self, out):
        assert out['sinNombre']

    def test_quitar_el_armario_avisa_de_lo_que_guarda(self, out):
        assert '2' in out['aviso']
        assert out['otroSinAviso'] == ''


class TestElDibujo:
    """Reportado: las estanterías no se dibujaban, y se pidió marcar el delante y el detrás."""

    def test_en_planta_el_delante_y_el_detras_de_lo_que_los_tiene(self, out):
        assert out['mesaFrente']
        assert out['puertaSinFrente']

    def test_de_frente_las_baldas(self, out):
        assert out['baldasFrente'] == 2
        assert out['unaSinLineas']

    def test_en_3d_el_armario_abierto_con_sus_baldas(self, out):
        assert out['armario3d'] == 7, 'fondo, dos lados, techo y tres tablas'

    def test_en_3d_la_franja_del_delante(self, out):
        assert out['mesa3d'] == [2, True]

    def test_el_nombre_nunca_boca_abajo(self, out):
        """Reportado: una mesa girada media vuelta tenía el nombre cabeza abajo."""
        assert out['giros'] == [False, False, True, True]
        assert out['rackVolteado']
