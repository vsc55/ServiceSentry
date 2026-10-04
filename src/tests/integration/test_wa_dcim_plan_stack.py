#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que queda tapado en el plano de una sala, ejecutado en `node` sobre el guion del panel.

Una bandeja de cables encima de una mesa tapaba la mesa: el clic llega a lo de arriba y la mesa
no se podía seleccionar nunca. Reportado desde la pantalla. Lo que fijan estas pruebas:

- pulsar otra vez, sin moverse, sobre lo ya seleccionado pasa a lo de debajo, y en vuelta;
- lo seleccionado sigue siendo lo que se arrastra aunque otra pieza lo tape;
- «Enviar al fondo» lo pinta tenue y transparente al puntero, suelta la selección y la barra
  dice cuántas hay al fondo con un botón para traerlas; elegirla desde la lista la trae.
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
_dcimPlan = {room: {uid: 'r1', name: 'Sala'}, racks: [{uid: 'k1', name: 'Rack01', pos_x: 0, pos_y: 0}]};
_dcpFeat = {kinds: {table: {layer: 'room'}, tray: {layer: 'air'}},
            features: [{uid: 'mesa', kind: 'table', pos_x: 0, pos_y: 0, width_mm: 1200, depth_mm: 600},
                       {uid: 'bandeja', kind: 'tray', pos_x: 0, pos_y: 0, width_mm: 3000, depth_mm: 300}]};
_dcpView = 'top';
let pintado = 0, inspector = 0, pantalla = 0;
_dcpRedraw = () => { pintado++; };
_dcpInspectorDraw = () => { inspector++; };
renderDcim = () => { pantalla++; };
ssCanvasPoint = () => ({x: 0, y: 0});
ssCanvasPanStart = () => {};
ssCanvasPanEnd = () => {};
_dcpFloatShow = () => {};

// Un `<g>` de mentira con su rectángulo: `closest` sube del rectángulo a su grupo.
function grupo(attr, uid) {
    const g = {dataset: {[attr]: uid}};
    g.closest = (sel) => sel.includes('g[data-' + attr + ']') ? g : null;
    const rect = {closest: (sel) => sel.startsWith('[data-dcph]') ? null : g.closest(sel)};
    return rect;
}
const bandeja = grupo('dcpf', 'bandeja'), mesa = grupo('dcpf', 'mesa'), rack = grupo('dcp', 'k1');
// De arriba abajo, como lo devuelve el navegador: la bandeja tapa la mesa, que tapa el rack.
document.elementsFromPoint = () => [bandeja, mesa, rack];
const ev = {clientX: 10, clientY: 10, target: bandeja, type: 'pointerup',
            currentTarget: {setPointerCapture() {}}};
__out = {};

// ── La pila bajo el puntero ─────────────────────────────────────────────────────
const pila = _dcpStackOf([bandeja, bandeja, mesa, rack]);
__out.pila = pila.map(p => p.kind + ':' + p.uid).join(',');

// ── Pulsar otra vez pasa a lo de debajo ─────────────────────────────────────────
_dcpSel = null;
_dcpDown(ev); _dcpUp(ev);
__out.primera = _dcpSel && _dcpSel.uid;
_dcpDown(ev); _dcpUp(ev);
__out.segunda = _dcpSel && _dcpSel.uid;
_dcpDown(ev); _dcpUp(ev);
__out.tercera = _dcpSel && (_dcpSel.kind + ':' + _dcpSel.uid);
_dcpDown(ev); _dcpUp(ev);
__out.vuelta = _dcpSel && _dcpSel.uid;

// ── Lo seleccionado se arrastra aunque esté tapado ──────────────────────────────
_dcpSel = {kind: 'feature', uid: 'mesa'};
_dcpDown(ev);
__out.arrastraLaMesa = _dcpDrag && _dcpDrag.uid;
// …y si se movió, soltar no cambia de pieza.
_dcpDrag.moved = true;
_dcpSave = () => {};
_dcpUp(ev);
__out.movidaSigue = _dcpSel && _dcpSel.uid;

// ── Enviar al fondo ─────────────────────────────────────────────────────────────
_dcpSel = {kind: 'feature', uid: 'bandeja'};
const ficha = String(_dcpInspectorBody());
__out.botonEnFicha = ficha.includes('_dcpSendBack(&quot;feature&quot;,&quot;bandeja&quot;)');
_dcpSendBack('feature', 'bandeja');
__out.sueltaSeleccion = _dcpSel === null;
__out.tenue = _dcpFeature(_dcpFeat.features[1]).includes('ss-dcp-back')
    && !_dcpFeature(_dcpFeat.features[0]).includes('ss-dcp-back');
__out.chip = _dcpBackChip().includes('_dcpBringAll()') && _dcpBackChip().includes(tf('dcim_n_back', 1));
// Elegida desde la lista, vuelve al frente.
_dcpPick('feature', 'bandeja');
__out.listaLaTrae = !_dcpIsBack('feature', 'bandeja') && _dcpBackChip() === '';
// Un rack también, y «traer todo» lo trae.
_dcpSendBack('rack', 'k1');
__out.rackTenue = _dcpRack(_dcimPlan.racks[0]).includes('ss-dcp-back');
_dcpBringAll();
__out.traerTodo = _dcpBack.size === 0;

// ── La barra flotante también lo envía al fondo ─────────────────────────────────
__out.flotantePieza = _dcpFloatHtml('mesa', 'feature').includes('_dcpSendBackFeature(&quot;mesa&quot;)');
__out.flotanteRack = _dcpFloatHtml('k1', 'rack').includes('_dcpSendBackRack(&quot;k1&quot;)');

// ── El cursor de las asas gira con la pieza ─────────────────────────────────────
__out.cursor0 = ['e', 'n', 'ne', 'nw'].map(a => _dcpHandleCursor(a, 0)).join(',');
__out.cursor90 = ['e', 'n', 'ne', 'nw'].map(a => _dcpHandleCursor(a, 90)).join(',');
__out.cursor270 = _dcpHandleCursor('e', 270);
__out.cursorEnAsa = _dcpHandles(10, 10, 90).includes('data-dcph="e"') &&
    /data-dcph="e"[^>]*cursor:ns-resize/.test(_dcpHandles(10, 10, 90));
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


class TestLoQueQuedaTapado:
    def test_la_pila_va_de_arriba_abajo_sin_repetir(self, out):
        assert out['pila'] == 'feature:bandeja,feature:mesa,rack:k1'

    def test_el_primer_clic_coge_lo_de_arriba(self, out):
        assert out['primera'] == 'bandeja'

    def test_pulsar_otra_vez_pasa_a_lo_de_debajo(self, out):
        assert out['segunda'] == 'mesa', 'la mesa bajo la bandeja sigue sin poder seleccionarse'
        assert out['tercera'] == 'rack:k1'

    def test_y_tras_lo_ultimo_vuelve_a_lo_primero(self, out):
        assert out['vuelta'] == 'bandeja'

    def test_lo_seleccionado_se_arrastra_aunque_este_tapado(self, out):
        assert out['arrastraLaMesa'] == 'mesa', 'arrastrar la mesa elegida mueve la bandeja'
        assert out['movidaSigue'] == 'mesa', 'soltar tras arrastrar cambió de pieza'


class TestEnviarAlFondo:
    def test_la_ficha_lleva_el_boton(self, out):
        assert out['botonEnFicha']

    def test_al_fondo_suelta_la_seleccion_y_se_pinta_tenue(self, out):
        assert out['sueltaSeleccion']
        assert out['tenue']

    def test_la_barra_dice_cuantas_y_las_trae(self, out):
        assert out['chip']
        assert out['traerTodo']

    def test_elegirla_en_la_lista_la_trae_al_frente(self, out):
        assert out['listaLaTrae']

    def test_un_rack_tambien(self, out):
        assert out['rackTenue']

    def test_la_barra_flotante_tambien(self, out):
        assert out['flotantePieza'], 'la barra que sale al pasar por la pieza no envía al fondo'
        assert out['flotanteRack']


class TestElCursorDeLasAsasGira:
    def test_sin_girar_cada_asa_su_flecha(self, out):
        assert out['cursor0'] == 'ew-resize,ns-resize,nesw-resize,nwse-resize'

    def test_girada_90_el_ancho_y_el_alto_se_cambian(self, out):
        """Reportado desde la pantalla: girada, el asa de ancho enseñaba la flecha de alto."""
        assert out['cursor90'] == 'ns-resize,ew-resize,nwse-resize,nesw-resize'
        assert out['cursor270'] == 'ns-resize'
        assert out['cursorEnAsa']
