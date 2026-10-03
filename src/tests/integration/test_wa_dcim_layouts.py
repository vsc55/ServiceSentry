#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las cuatro vistas del inventario, ejecutadas en `node` sobre el guion de verdad del panel.

Lo que comparten —el filtro, los totales, la barra de ocupación, el menú «⋯»— y lo que cada una
tiene que dar para que el cuadro de mando pueda llevar a una sede: el `id` de esa sede. Y el
clic en una caja del mapa del cuadro, que tiene que llevar a la sede.
"""

from __future__ import annotations

import io
import json
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
_dcimData = {
    orgs: [{uid: 'o1', name: 'Uno', short: 'U1'}, {uid: 'o2', name: 'Dos', short: 'D2'}],
    sites: [
        {uid: 's1', name: 'Norte', address: 'Calle Mayor', org_uid: 'o1', floors: 2, rooms: [
            {uid: 'r1', name: 'CPD', rackList: [
                {uid: 'k1', name: 'R-ALFA', u_height: 42, used_u: 40,
                 roll: {total: 5, state: 'ok', unwatched: 1}},
                {uid: 'k2', name: 'R-BETA', u_height: 42, used_u: 2, org_uid: 'o2'}]},
            {uid: 'r2', name: 'Garaje', rackList: []}]},
        {uid: 's2', name: 'Sur', org_uid: 'o2', rooms: [
            {uid: 'r3', name: 'Sala', rackList: [
                {uid: 'k3', name: 'R-GAMMA', u_height: 10, used_u: 0,
                 roll: {total: 4, state: ''}}]}]},
    ],
};
const forma = (ss) => ss.map(s => s.uid + ':' + s.rooms.map(r =>
    r.uid + '[' + r.rackList.map(k => k.uid).join(',') + ']').join(';'));
__out = {};

// ── El filtro ───────────────────────────────────────────────────────────────────
__out.todo = JSON.stringify(forma(_dcimFiltered()));
_dcimQuery = 'beta';
__out.rack = JSON.stringify(forma(_dcimFiltered()));
_dcimQuery = 'NORTE';
__out.sede = JSON.stringify(forma(_dcimFiltered()));
_dcimQuery = 'mayor';
__out.direccion = JSON.stringify(forma(_dcimFiltered()));
_dcimQuery = 'nada-de-esto';
__out.nada = JSON.stringify(forma(_dcimFiltered()));
__out.nadaHtml = _dcimLayoutHtml();
_dcimQuery = '';
_dcimOrgPick = 'o2';
__out.empresa = JSON.stringify(forma(_dcimFiltered()));
_dcimOrgPick = '';

// ── La tabla: por tipo, y lo que exporta ───────────────────────────────────────────
_dcimTableKind = 'rack';
__out.soloRacks = JSON.stringify(_dcimTableRows(_dcimFiltered()).map(f => f.kind + ':' + f.name));
_dcimTableKind = '';
_dcimTableGroup = 'tree';
_dcimFold = new Set(['s1']);
__out.plegada = JSON.stringify(_dcimTableRows(_dcimFiltered()).map(f => f.name));
let csv = '';
const _blobOrig = ssDownloadBlob;
ssDownloadBlob = (b, nombre) => { csv = b.__texto || ''; __out.csvNombre = nombre; };
const _BlobOrig = typeof Blob === 'undefined' ? null : Blob;
Blob = function (partes) { this.__texto = partes.join(''); };
_dcimCsv();
__out.csv = csv;
_dcimFold = new Set();
_dcimTableCols = new Set(['kind']);
__out.tablaSinColumnas = _dcimTableHtml(_dcimFiltered());
_dcimTableCols = new Set(_DCIM_TABLE_COLS_DEFAULT);

// ── Los huecos para uno más ─────────────────────────────────────────────────────
__out.tarjetas = _dcimCardsHtml(_dcimFiltered());
__out.lista = _dcimListHtml(_dcimFiltered());

// ── Lo que se suma ──────────────────────────────────────────────────────────────
__out.totales = JSON.stringify(_dcimSiteTotals(_dcimData.sites[0]));
__out.barraVacia = _dcimUBar(0, 0);
__out.barraLlena = _dcimUBar(40, 42);
__out.barraHolgada = _dcimUBar(2, 42);
__out.barraDePie = _dcimUBarV(40, 42);

// ── Cada vista da el id de cada sede que enseña ──────────────────────────────────
const ids = {};
for (const v of ['list', 'cards', 'table']) {
    _dcimLayout = v;
    const html = _dcimLayoutHtml();
    ids[v] = ['s1', 's2'].filter(u => html.includes('id="dcim-site-' + u + '"'));
}
_dcimLayout = 'detail';
_dcimSel = {site: 's2', room: ''};
const ficha = _dcimLayoutHtml();
ids.detail = ['s1', 's2'].filter(u => ficha.includes('id="dcim-site-' + u + '"'));
__out.ids = JSON.stringify(ids);
__out.ficha = ficha;
// Una elegida que el filtro esconde no deja la ficha vacía: sale la primera que queda.
_dcimQuery = 'norte';
__out.fichaFiltrada = _dcimLayoutHtml();
_dcimQuery = '';

// ── Una vista que ya no existe, recordada, vuelve a la lista ──────────────────────
_dcimLayout = 'map';
__out.vistaVieja = _dcimLayoutHtml().includes('id="dcim-site-s1"')
                   && _dcimLayoutHtml().includes('ss-fold-head');
_dcimLayout = 'list';

// ── El menú «⋯» es de quien puede editar ─────────────────────────────────────────
__out.menu = _dcimMenu('rack', 'k1', 'R-ALFA', '');
__out.menuSala = _dcimMenu('room', 'r1', 'CPD', 'rack');
currentUser = {permissions: ['dcim_view']};
__out.menuMiron = _dcimMenu('rack', 'k1', 'R-ALFA', '');
currentUser = {permissions: ['dcim_view', 'dcim_edit']};

// ── Un clic en una caja del mapa del cuadro lleva a la sede ──────────────────────
_dcimBoard = {sites: [], links: [], map: {}};
let elegida = '';
_dcimBoardGoSite = (u) => { elegida = u; };
const soltar = (tipo, x, y) => _dcmUp({type: tipo, clientX: x, clientY: y});
_dcmPress = {uid: 's2', x: 10, y: 10};
soltar('pointerup', 12, 11);
__out.clic = elegida;
elegida = '';
_dcmPress = {uid: 's2', x: 10, y: 10};
soltar('pointerup', 80, 10);
__out.arrastre = elegida;
_dcmPress = {uid: 's2', x: 10, y: 10};
soltar('pointerleave', 10, 10);
__out.salir = elegida;
_dcimBoard = null;

// ── La vista elegida se recuerda en este navegador ───────────────────────────────
try { _dcimSetLayout('cards'); } catch (e) { /* el DOM de mentira no pinta; da igual */ }
__out.recordada = localStorage.getItem('ss_dcim_layout');

// ── Cómo empieza cada sede, y su luz ─────────────────────────────────────────────
_dcimFold = new Set();
_dcimFoldSeen = new Set();
_dcimData.sites[0].roll = {state: 'ok'};
_dcimData.sites[1].roll = {state: 'error'};
_dcimFoldNew();
__out.plegadas = JSON.stringify([..._dcimFold]);
_dcimFold.delete('s1');
_dcimFoldNew();
__out.respeta = !_dcimFold.has('s1');
_dcimFold.add('s1');
_dcimQuery = 'gamma';
__out.buscando = _dcimIsFolded('s1');
_dcimQuery = '';
__out.quieta = _dcimIsFolded('s1');
__out.ledRojo = _dcimLed('error', true);
__out.ledAmbar = _dcimLed('warning');
__out.ledVerde = _dcimLed('ok', true);
__out.ledGris = _dcimLed('', true);
_dcimLayout = 'list';
__out.listaLuces = _dcimListHtml(_dcimFiltered());
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


class TestElFiltroDejaDondeEstaCadaCosa:

    def test_sin_filtro_esta_todo(self, vistas):
        assert json.loads(vistas['todo']) == ['s1:r1[k1,k2];r2[]', 's2:r3[k3]']

    def test_un_rack_sale_con_la_sala_y_la_sede_que_lo_tienen(self, vistas):
        """Buscar un rack contesta DÓNDE está: sin su sala y su sede, la respuesta es un nombre."""
        assert json.loads(vistas['rack']) == ['s1:r1[k2]']

    def test_una_sede_sale_con_todo_lo_que_tiene(self, vistas):
        assert json.loads(vistas['sede']) == ['s1:r1[k1,k2];r2[]']

    def test_tambien_se_busca_por_la_direccion(self, vistas):
        assert json.loads(vistas['direccion']) == ['s1:r1[k1,k2];r2[]']

    def test_lo_que_no_coincide_lo_dice(self, vistas):
        assert json.loads(vistas['nada']) == []
        assert 'Nada coincide' in vistas['nadaHtml'] or 'Nothing matches' in vistas['nadaHtml']

    def test_la_empresa_es_la_de_cada_cosa_o_la_de_lo_que_la_tiene(self, vistas):
        """El R-BETA de la filial vive en una sede de otra: sale, con el camino hasta él. La sede
        Sur es de la filial y sale entera."""
        assert json.loads(vistas['empresa']) == ['s1:r1[k2]', 's2:r3[k3]']


class TestLaOcupacion:

    def test_los_totales_de_una_sede(self, vistas):
        assert json.loads(vistas['totales']) == {'rooms': 2, 'racks': 2, 'u': 84, 'used': 42,
                                                 'things': 5, 'quiet': 1}

    def test_sin_racks_no_hay_barra(self, vistas):
        """Una barra vacía diría «vacío», que no es lo mismo que «aquí no hay nada»."""
        assert vistas['barraVacia'] == ''

    def test_pasado_el_ochenta_por_ciento_avisa(self, vistas):
        assert 'bg-warning' in vistas['barraLlena'] and 'bg-info' in vistas['barraHolgada']
        assert 'bg-warning' in vistas['barraDePie']


class TestCadaVistaSabeLlevarAUnaSede:
    """El cuadro de mando lleva a una sede buscando su `id`: una vista que no lo pinta es una
    vista desde la que el cuadro no lleva a ninguna parte."""

    def test_las_listas_pintan_todas(self, vistas):
        ids = json.loads(vistas['ids'])
        for v in ('list', 'cards', 'table'):
            assert ids[v] == ['s1', 's2'], v

    def test_la_ficha_pinta_la_elegida(self, vistas):
        assert json.loads(vistas['ids'])['detail'] == ['s2']

    def test_la_ficha_cuenta_plantas_salas_racks_y_u(self, vistas):
        """Las de Sur: ninguna planta, una sala, un rack, 0 de 10 U."""
        assert '0 / 10 U' in vistas['ficha']

    def test_si_el_filtro_esconde_la_elegida_sale_la_primera_que_queda(self, vistas):
        assert 'id="dcim-site-s1"' in vistas['fichaFiltrada']

    def test_una_vista_que_ya_no_existe_cae_en_la_lista(self, vistas):
        """Hubo una vista de mapa, y quien la eligió la tiene guardada en su navegador."""
        assert vistas['vistaVieja'] is True


class TestElMenuDeAcciones:

    def test_trae_editar_y_eliminar(self, vistas):
        for fn in ("_dcimOpen('edit'", '_dcimDelete('):
            assert fn in vistas['menu']

    def test_el_de_una_sala_crea_racks(self, vistas):
        assert "_dcimOpen('new',&quot;rack&quot;" in vistas['menuSala']

    def test_un_menu_que_se_sale_de_la_lista_no_se_corta(self, vistas):
        """La lista va en su propia caja con scroll: un menú colocado dentro se cortaría."""
        assert '"strategy":"fixed"' in vistas['menu']

    def test_quien_solo_mira_no_lo_tiene(self, vistas):
        assert vistas['menuMiron'] == ''


class TestElClicEnElMapaDelCuadro:

    def test_pulsar_una_caja_lleva_a_la_sede(self, vistas):
        assert vistas['clic'] == 's2'

    def test_arrastrar_desde_una_caja_mueve_el_mapa_y_no_lleva(self, vistas):
        assert vistas['arrastre'] == ''

    def test_salir_del_dibujo_no_es_pulsar(self, vistas):
        assert vistas['salir'] == ''


class TestLaVistaSeRecuerda:

    def test_en_este_navegador(self, vistas):
        assert vistas['recordada'] == 'cards'


class TestLaTabla:

    def test_se_puede_ver_solo_un_tipo(self, vistas):
        assert json.loads(vistas['soloRacks']) == ['rack:R-ALFA', 'rack:R-BETA', 'rack:R-GAMMA']

    def test_plegar_una_sede_esconde_sus_filas(self, vistas):
        assert json.loads(vistas['plegada']) == ['Norte', 'Sur', 'Sala', 'R-GAMMA']

    def test_el_csv_lleva_todas_las_filas_aunque_esten_plegadas(self, vistas):
        """Plegar es mirar, no filtrar: lo exportado no puede depender de qué se plegó."""
        csv = vistas['csv'].lstrip(chr(0xfeff)).split(chr(13) + chr(10))
        assert len(csv) == 1 + 2 + 3 + 3                 # cabecera, sedes, salas, racks
        assert csv[0].startswith(('Nombre,', 'Name,'))
        assert any(l.startswith('R-ALFA,') and '40/42' in l and '95 %' in l for l in csv)
        assert vistas['csvNombre'].endswith('.csv')

    def test_las_columnas_escondidas_no_se_pintan(self, vistas):
        html = vistas['tablaSinColumnas']
        assert 'Calle Mayor' not in html and ('Sede' in html or 'Site' in html)


class TestLosHuecosParaUnoMas:

    def test_las_tarjetas_acaban_con_una_sede_nueva(self, vistas):
        assert "_dcimOpen('new','site','','')" in vistas['tarjetas']

    def test_cada_sala_de_la_lista_acaba_con_un_rack_nuevo(self, vistas):
        assert vistas['lista'].count("_dcimOpen('new','rack'") == 3

    def test_las_tarjetas_cuentan_lo_que_no_se_vigila(self, vistas):
        """Sur tiene un rack con cuatro cosas y ningún estado: cuatro sin vigilar."""
        assert '4 sin vigilar' in vistas['tarjetas'] or '4 unwatched' in vistas['tarjetas']


class TestElEstadoSeVeDeUnVistazo:
    """Pedido desde la pantalla: una luz en cada sede, sala y rack, y las sedes plegadas salvo
    las que tienen algo mal, que se abren solas."""

    def test_empiezan_plegadas_salvo_las_que_van_mal(self, vistas):
        assert json.loads(vistas['plegadas']) == ['s1']

    def test_lo_que_despliega_una_persona_se_queda_desplegado(self, vistas):
        """Se decide UNA vez por sede: volver a plegarla en cada dibujado sería quitárselo."""
        assert vistas['respeta'] is True

    def test_al_buscar_no_hay_nada_plegado(self, vistas):
        """Lo encontrado debajo de una sede plegada es una búsqueda que parece no encontrar."""
        assert vistas['buscando'] is False and vistas['quieta'] is True

    def test_cada_estado_tiene_su_color_y_su_palabra(self, vistas):
        assert 'bg-danger' in vistas['ledRojo'] and 'is-bad' in vistas['ledRojo']
        assert 'bg-warning' in vistas['ledAmbar'] and 'is-bad' in vistas['ledAmbar']
        assert 'bg-success' in vistas['ledVerde'] and 'is-bad' not in vistas['ledVerde']
        assert '>Caído<' in vistas['ledRojo'] or '>Down<' in vistas['ledRojo']

    def test_sin_vigilar_es_gris_y_no_verde(self, vistas):
        """Una luz verde sobre lo que nadie mira es una mentira vista desde la puerta."""
        assert 'bg-secondary' in vistas['ledGris'] and 'bg-success' not in vistas['ledGris']

    def test_la_lista_enciende_una_por_sede_sala_y_rack(self, vistas):
        """Sur va mal, así que está desplegada: su sede, su sala y su rack llevan luz; Norte está
        plegada y solo lleva la suya."""
        assert vistas['listaLuces'].count('class="ss-led ') == 1 + 3
