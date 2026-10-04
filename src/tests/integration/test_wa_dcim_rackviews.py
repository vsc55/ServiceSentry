#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las cuatro vistas de un armario, ejecutadas en `node` sobre el guion de verdad del panel.

«Rack y pestañas», «Por U», «Cuadro» y «Compacta» leen el mismo armario y los mismos cables,
corriente e historial que las pestañas. Lo que tiene que cumplirse, y lo que fijan estas pruebas:

- el selector ofrece las cuatro y la elegida se recuerda en el navegador;
- la cabecera común lleva «Colocar algo» y el selector; la ficha bajo el dibujo existe aunque
  no se señale nada;
- «Por U» recorre TODAS las U de arriba abajo —las libres también, con «Colocar aquí»—, mete lo
  montado en una bandeja debajo de ella, enseña los cables y las ramas de cada equipo, y su
  buscador filtra;
- «Cuadro» saca «Requiere atención» de los datos de verdad (garantía caducada, cable en otro
  puerto, enlace sin declarar, una sola rama, U libre) y colorea el dibujo por lo que se pregunta;
- «Compacta» lista una cara cada vez y sus pestañas de abajo abren las pestañas de verdad;
- las pestañas avisan sin abrirlas, y Cableado y Alimentación tienen la forma del diseño.
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
currentUser = {permissions: ['dcim_view', 'dcim_edit', 'dcim_cable_edit']};
_dcimData = {orgs: [], sites: []};
_dcimRack = {
    rack: {uid: 'k1', name: 'Rack01', u_height: 7, width_mm: 600, desc_units: 1},
    items: [
        {uid: 'i1', label: 'Router01', u_start: 1, u_height: 1, face: 'full', state: 'ok',
         device_uid: 'd1', serial: 'HF1090WER2Y'},
        {uid: 'i2', label: 'Digitus DN-91424', u_start: 2, u_height: 1, face: 'front'},
        {uid: 'i3', label: 'SW01', u_start: 3, u_height: 1, face: 'full', state: 'ok', device_uid: 'd3'},
        {uid: 't5', label: 'Bandeja', u_start: 5, u_height: 1, face: 'full'},
        {uid: 'p1', label: 'PVE01', parent_uid: 't5', state: 'ok', device_uid: 'dp1',
         serial: '8CC0321NZY', warranty_until: '2020-01-30'},
        {uid: 'p2', label: 'PVE02', parent_uid: 't5', state: 'ok', device_uid: 'dp2'},
        {uid: 't6', label: 'Bandeja', u_start: 6, u_height: 1, face: 'full'},
        {uid: 'i7', label: 'Equip 333293', u_start: 7, u_height: 1, face: 'front'},
        {uid: 'r1', label: 'SoloDetras', u_start: 4, u_height: 1, face: 'rear'},
        {uid: 'b1', label: 'Back-UPS RS 1600SI', placement: 'near'},
        {uid: 'b2', label: 'PVE20', placement: 'inside', state: 'maintenance'},
    ],
    free: {front: [4], rear: [2, 7]},
    roll: {total: 6, state: 'ok', bad: 0, unwatched: 0},
    counts: {cables: 2, power: 3, hist: 1},
};
_dcCables = {checked: true, counts: {seen: 1, via: 0, unseen: 0, other_port: 1, undeclared: 1},
    cables: [
        {uid: 'c1', label: 'C-001', a_item: 'i1', b_item: 'i3', seen: 'seen', color: '#3d8bfd', kind: 'copper'},
        {uid: 'c3', label: 'C-003', a_item: 'i3', b_item: 'p2', a_port: 'Gi0/3', b_port: 'eno1',
         seen: 'other_port', ports_seen: ['Gi0/5'], kind: 'copper'},
    ],
    undeclared: [{from: 'd3', to: 'dp1', ports: {x: ['Gi0/6']}, a_item: 'i3', b_item: 'p1'}]};
_dcPower = {watts_said: 840, by_branch: {a: 595, b: 245},
    pdus: [{uid: 'pa', name: 'PDU-A', feed: 'a', color: '#2f6fde', load: 0.16, free: 4, outlets: 8},
           {uid: 'pb', name: 'PDU-B', feed: 'b', color: '#b35400', load: 0.07, free: 5, outlets: 8}],
    items: [{uid: 'i1', u_start: 1, feeds: [{pdu_uid: 'pa', pdu: 'PDU-A', outlet: 1},
                                            {pdu_uid: 'pb', pdu: 'PDU-B', outlet: 1}],
             branches: ['a', 'b'], watts_said: 60},
            {uid: 'p2', u_start: 5, feeds: [{pdu_uid: 'pa', pdu: 'PDU-A', outlet: 4}],
             branches: ['a'], watts_said: 350}],
    warnings: [{kind: 'single_branch', item: 'p2', label: 'PVE02', branch: 'a'}],
    site_uid: 's1',
    sources: [{uid: 'sai1', name: 'SAI 1', kind: 'ups', bypass: 1, item_uid: ''},
              {uid: 'cg', name: 'CGBT', kind: 'panel', bypass: 0, item_uid: ''}],
    source_warnings: [{kind: 'on_bypass', pdu: 'pa', label: 'PDU-A', ups: ['SAI 1']}],
    ups_items: [{uid: 'b1', label: 'Back-UPS RS 1600SI', rack: 'k1', rack_name: 'Rack01', source: ''}]};
_dcPower.pdus[0].source_uid = 'sai1';
_dcPower.pdus[0].path = {known: true, now: [{uid: 'cg', name: 'CGBT', kind: 'panel', bypass: false}],
                         clean: ['sai1', 'cg'], ups: []};
_dcPower.pdus[1].source_uid = '';
_dcPower.pdus[1].path = {known: false, now: [], clean: [], ups: []};
_dcHist = {rows: [{uid: 'h1', at: '2026-10-03 18:40', by: 'admin', items: 11,
                   changed: [{kind: 'add', label: 'PVE20'}]}]};
__out = {};

// ── El selector y la cabecera ───────────────────────────────────────────────────
_dcRackView = 'rack';
const cab = _dcimRackHtml();
__out.picker = ['rack', 'byu', 'board'].every(v => cab.includes('_dcRackViewSet(&quot;' + v + '&quot;)'))
    && !cab.includes('_dcRackViewSet(&quot;compact&quot;)');
// En un móvil: siempre la compacta, sin selector, recordando la elegida para cuando haya sitio.
const mmOrig = window.matchMedia;
window.matchMedia = () => ({matches: true});
const movil = _dcimRackHtml();
__out.movilCompacta = movil.includes('ss-cmp-tabs') && !movil.includes('_dcRackViewSet(');
__out.movilRecuerda = _dcRackView;
window.matchMedia = mmOrig;
__out.colocar = cab.includes("_dcimOpen('new','item',&quot;k1&quot;,'')");
__out.fichaVacia = cab.includes('ss-elev-card-idle');
__out.leyenda = cab.includes('ss-mark-bar');
__out.avisoCorriente = _dcRackPanelHtml(_dcimRack.items).includes('text-bg-warning">1<');

// ── Por U ───────────────────────────────────────────────────────────────────────
const byu = _dcByUGrid();
__out.byuOrden = byu.indexOf('Router01') < byu.indexOf('SW01') && byu.indexOf('SW01') < byu.indexOf('Equip 333293');
__out.byuLibreSoloDetras = !byu.includes('_dcRackPlaceAt(&quot;4&quot;)') && byu.includes('SoloDetras');      // U4 tiene algo detrás
__out.byuLibres = (byu.match(/ss-byu-free/g) || []).length;
__out.byuHijos = (byu.match(/ss-byu-kid/g) || []).length;
__out.byuHijoTrasBandeja = byu.indexOf('PVE01') > byu.indexOf('Bandeja');
__out.byuCableRojo = byu.includes('background:var(--bs-danger)');
__out.byuUnaRama = byu.includes('text-bg-warning fw-normal');
__out.byuFuera = byu.includes('Back-UPS RS 1600SI') && byu.includes('ss-byu-group');
_dcByUQuery = 'pve02';
const filtrada = _dcByUGrid();
__out.byuBusca = filtrada.includes('PVE02') && !filtrada.includes('Router01');
_dcByUQuery = '';

// ── Cuadro ──────────────────────────────────────────────────────────────────────
const att = _dcBoardAttention();
__out.attGarantia = att.includes('PVE01');
__out.attOtroPuerto = att.includes('C-003');
__out.attSinDeclarar = att.includes('_dcCableFromSeen(0)');
__out.attUnaRama = att.includes("_dcRackJump('power')");
__out.attMantenimiento = att.includes('PVE20');
__out.attLibre = att.includes('_dcRackPlaceAt(&quot;4&quot;)');
__out.attRojoPrimero = att.indexOf('var(--bs-danger)') < att.indexOf('var(--bs-secondary)');
_dcBoardColor = 'warranty';
const cara = _dcBoardFace(_dcimRack.rack, _dcimRack.items, 'front');
__out.cuadroGarantiaRoja = /--c:var\(--bs-danger\)"[^>]*\n?[^>]*title="PVE01"/.test(cara)
    || cara.split('title="PVE01"')[0].lastIndexOf('var(--bs-danger)') > cara.split('title="PVE01"')[0].lastIndexOf('<button');
const traseraCuadro = _dcBoardFace(_dcimRack.rack, _dcimRack.items, 'rear');
__out.cuadroDetrasAlReves = traseraCuadro.indexOf('PVE02') < traseraCuadro.indexOf('PVE01');
__out.cuadroKpis = (_dcBoardKpis().match(/ss-kpi"/g) || []).length;
_dcBoardColor = 'state';

// ── Compacta ────────────────────────────────────────────────────────────────────
_dcCompactFace = 'front';
const delante = _dcCompactList(_dcimRack.rack, _dcimRack.items);
__out.cmpDelanteSinTrasera = !delante.includes('SoloDetras') && delante.includes('Digitus');
_dcCompactFace = 'rear';
const detras = _dcCompactList(_dcimRack.rack, _dcimRack.items);
__out.cmpDetras = detras.includes('SoloDetras') && !detras.includes('Digitus');
_dcCompactFace = 'front';
_dcRackTab = 'cables';
__out.cmpPestanaCables = _dcRackCompactHtml().includes('C-003');
_dcRackTab = 'items';

// ── Las pestañas con la forma del diseño ────────────────────────────────────────
__out.cablesFichas = _dcCablesHtml().includes('bg-danger-subtle') && _dcCablesHtml().includes('ss-warn-box');
__out.corrienteCifras = _dcPowerHtml().includes('ss-pw-figs') && _dcPowerHtml().includes('ss-warn-box');

// ── Lo que encontró el navegador ────────────────────────────────────────────────
// «Equipos» del cuadro con nada vigilado: gris y «sin vigilar», como la cabecera.
const rollAntes = _dcimRack.roll;
_dcimRack.roll = {total: 6, state: '', bad: 0};
const kpis = _dcBoardKpis();
__out.kpiSinVigilar = !kpis.includes('text-success') && kpis.includes(tf('dcim_unwatched_n', 6));
_dcimRack.roll = rollAntes;
// Alimentación: lo que no ocupa U no lleva una «U» suelta delante.
_dcPower.items.push({uid: 'b1', u_start: 0, label: 'Back-UPS RS 1600SI', feeds: [{pdu_uid: 'pa', pdu: 'PDU-A'}],
                     branches: ['a'], watts_said: 0});
__out.sinUSuelta = !/>U<\/span>/.test(_dcPowerItems(_dcPower.items, _dcPower.pdus));
// Historial: comparar dos versiones del mismo segundo lee de la vieja a la nueva, se marquen
// en el orden que se marquen; y lo que no ocupa U no sale como «U0».
_dcHist = {rows: [
    {uid: 'nueva', at: '2026-10-04T11:42:54Z', data: {items: [{uid: 'x', label: 'SAI', placement: 'near'}]}},
    {uid: 'vieja', at: '2026-10-04T11:42:54Z', data: {items: []}},
]};
_dcHistPick = ['nueva', 'vieja'];
const comp = _dcHistDiffHtml(_dcHist.rows);
__out.histOrden = comp.includes('+ SAI') && !comp.includes('− SAI');
__out.histSinU0 = !comp.includes('U0');
// Y el cambio de sitio, con sus palabras: ni `placement` ni `side → near`.
const sitio = _dcHistOne({kind: 'edit', label: 'PVE20', field: 'placement', from: 'side', to: 'near'});
__out.histSitio = !sitio.includes('placement') && !sitio.includes(': side') && !sitio.includes('→ near')
    && sitio.includes(t('dcim_place_col_near')) && sitio.includes(t('dcim_item_place'));
_dcHistPick = [];

// ── Las fuentes, enlazadas con el armario ───────────────────────────────────────
const pw = _dcPowerHtml();
__out.pwCadena = pw.includes('ss-pw-chain') && pw.includes('CGBT') && pw.includes(t('dcim_chain_unknown'));
__out.pwBypassEnCadena = /EN BYPASS|BYPASS/i.test(pw.split('ss-pw-chain')[1] || '');
__out.pwSelector = pw.includes('_dcPduSourceSet(&quot;pa&quot;') && pw.includes('value="sai1" selected');
__out.pwSaiSuelto = pw.includes('_dcUpsDeclare(&quot;b1&quot;');
__out.pwAvisoBypass = pw.includes('SAI 1') && pw.includes('PDU-A');
const att2 = _dcBoardAttention();
__out.attBypass = att2.includes(tf('dcim_att_on_bypass', 'PDU-A'));
__out.attSaiSuelto = att2.includes(tf('dcim_att_ups_undeclared', 'Back-UPS RS 1600SI'));
_dceOn = 'b1';
__out.fichaSaiSinFuente = _dceCard().includes(t('dcim_card_source_none'));
_dcPower.ups_items[0].source = 'sai1';
__out.fichaSaiFuente = _dceCard().includes(tf('dcim_card_source', 'SAI 1'));
_dcPower.ups_items[0].source = '';
_dceOn = '';
// Lo que no ocupa U dice dónde está, y su chip rellena la ficha como una caja del dibujo.
__out.spanAlLado = _dceSpan({placement: 'near', face: 'full'}).startsWith(t('dcim_place_col_near'));
__out.chipHover = _dceBesideHtml(_dcimRack.items).includes('onpointerenter="_dceHover(');
// Abrir un rack desde Fuentes lo abre en Alimentación aunque no fuera el que estaba abierto:
// la carga respeta la pestaña pedida en vez de volver a la primera.
__out.pestanaPedida = _dcSrcGoRack.toString().includes('_dcRackTabNext')
    && _dcimLoadRack.toString().includes('_dcRackTabNext ||');

// ── La vista elegida se recuerda ────────────────────────────────────────────────
try { _dcRackViewSet('board'); } catch (e) { /* el DOM de mentira no pinta */ }
__out.recordada = localStorage.getItem('ss_dcim_rack_view');
try { _dcRackViewSet('inventada'); } catch (e) { /* idem */ }
__out.inventada = _dcRackView;
try { _dcRackViewSet('compact'); } catch (e) { /* idem */ }
__out.compactaNoSeElige = _dcRackView;
"""


@pytest.fixture(scope='module')
def vistas():
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


class TestElSelectorYLaCabecera:

    def test_ofrece_las_tres_vistas_y_no_la_compacta(self, vistas):
        assert vistas['picker'] is True

    def test_en_un_movil_sale_la_compacta_sin_selector(self, vistas):
        assert vistas['movilCompacta'] is True
        assert vistas['movilRecuerda'] == 'rack'       # la elegida sigue ahí para cuando haya sitio

    def test_colocar_algo_abre_el_formulario_en_este_armario(self, vistas):
        assert vistas['colocar'] is True

    def test_la_ficha_bajo_el_dibujo_existe_sin_senalar_nada(self, vistas):
        assert vistas['fichaVacia'] is True

    def test_el_dibujo_explica_sus_marcas(self, vistas):
        assert vistas['leyenda'] is True

    def test_alimentacion_avisa_de_la_rama_unica_sin_abrirla(self, vistas):
        assert vistas['avisoCorriente'] is True

    def test_la_vista_se_recuerda_y_una_inventada_no_entra(self, vistas):
        assert vistas['recordada'] == 'board'
        assert vistas['inventada'] == 'rack'
        assert vistas['compactaNoSeElige'] == 'rack'


class TestPorU:

    def test_de_arriba_abajo(self, vistas):
        assert vistas['byuOrden'] is True

    def test_las_u_libres_salen_y_una_ocupada_por_detras_no(self, vistas):
        """U4 tiene algo por detrás: no es libre. No queda ninguna U del todo vacía."""
        assert vistas['byuLibreSoloDetras'] is True
        assert vistas['byuLibres'] == 0

    def test_lo_montado_va_debajo_de_su_bandeja(self, vistas):
        assert vistas['byuHijos'] == 2 and vistas['byuHijoTrasBandeja'] is True

    def test_cables_y_ramas_en_cada_fila(self, vistas):
        assert vistas['byuCableRojo'] is True and vistas['byuUnaRama'] is True

    def test_lo_que_no_ocupa_u_va_al_final_en_su_grupo(self, vistas):
        assert vistas['byuFuera'] is True

    def test_el_buscador_filtra(self, vistas):
        assert vistas['byuBusca'] is True


class TestCuadro:

    def test_requiere_atencion_sale_de_los_datos(self, vistas):
        for k in ('attGarantia', 'attOtroPuerto', 'attSinDeclarar', 'attUnaRama',
                  'attMantenimiento', 'attLibre'):
            assert vistas[k] is True, k

    def test_lo_rojo_primero(self, vistas):
        assert vistas['attRojoPrimero'] is True

    def test_colorea_por_garantia(self, vistas):
        assert vistas['cuadroGarantiaRoja'] is True

    def test_por_detras_la_bandeja_va_al_reves(self, vistas):
        assert vistas['cuadroDetrasAlReves'] is True

    def test_las_seis_cifras(self, vistas):
        assert vistas['cuadroKpis'] == 6


class TestLoQueEncontroElNavegador:

    def test_equipos_sin_vigilar_no_sale_en_verde(self, vistas):
        assert vistas['kpiSinVigilar'] is True

    def test_alimentacion_sin_u_suelta(self, vistas):
        assert vistas['sinUSuelta'] is True

    def test_comparar_no_depende_del_orden_de_los_clics(self, vistas):
        assert vistas['histOrden'] is True

    def test_lo_que_no_ocupa_u_no_sale_como_u0(self, vistas):
        assert vistas['histSinU0'] is True

    def test_el_cambio_de_sitio_se_dice_con_palabras(self, vistas):
        assert vistas['histSitio'] is True


class TestLasFuentesEnlazadasConElArmario:

    def test_alimentacion_ensena_la_cadena_de_cada_regleta(self, vistas):
        assert vistas['pwCadena'] is True and vistas['pwBypassEnCadena'] is True

    def test_cada_regleta_elige_su_fuente(self, vistas):
        assert vistas['pwSelector'] is True

    def test_un_sai_del_armario_sin_fuente_se_ofrece_para_declarar(self, vistas):
        assert vistas['pwSaiSuelto'] is True

    def test_los_avisos_de_la_cadena_salen_en_la_pestana_y_en_el_cuadro(self, vistas):
        assert vistas['pwAvisoBypass'] is True
        assert vistas['attBypass'] is True and vistas['attSaiSuelto'] is True

    def test_la_ficha_de_un_sai_dice_que_fuente_es(self, vistas):
        assert vistas['fichaSaiSinFuente'] is True and vistas['fichaSaiFuente'] is True

    def test_lo_que_esta_al_lado_dice_donde_y_su_chip_rellena_la_ficha(self, vistas):
        assert vistas['spanAlLado'] is True and vistas['chipHover'] is True

    def test_desde_fuentes_el_rack_se_abre_en_alimentacion(self, vistas):
        assert vistas['pestanaPedida'] is True


class TestCompacta:

    def test_una_cara_cada_vez(self, vistas):
        assert vistas['cmpDelanteSinTrasera'] is True and vistas['cmpDetras'] is True

    def test_sus_pestanas_son_las_de_verdad(self, vistas):
        assert vistas['cmpPestanaCables'] is True


class TestLasPestanasConLaFormaDelDiseno:

    def test_cableado_resume_en_fichas_y_destaca_lo_sin_declarar(self, vistas):
        assert vistas['cablesFichas'] is True

    def test_alimentacion_con_sus_tres_cifras_y_los_avisos_en_caja(self, vistas):
        assert vistas['corrienteCifras'] is True
