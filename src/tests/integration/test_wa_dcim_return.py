#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recargar y volver al inventario sin perder el sitio. En `node`, sobre el guion del panel.

Reportado desde la pantalla: un F5 en el plano de una sede volvía al inventario, y al volver al
inventario —de una sede, una sala o un armario— no quedaba elegido nada: la lista arriba del
todo, la sede plegada, y había que buscar otra vez de dónde se venía. Lo que fijan:

- el plano de una sede, con su planta, va en la dirección, y se quita al salir de él;
- el cuadro de mando llega a la dirección (se escribía después de guardarla);
- al volver de un armario, de una sala o de una sede, esa sede queda elegida y desplegada, y
  lo que se dejó se marca y se lleva a la vista una sola vez;
- elegir otra cosa quita la marca.
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
_dcimData = {orgs: [], sites: [
    {uid: 's1', name: 'Sede 1', rooms: [{uid: 'r1', name: 'Sala 1', rackList: []}]},
    {uid: 's2', name: 'Sede 2', rooms: [{uid: 'r2', name: 'CPD', rackList: [{uid: 'k2'}]}]},
]};
renderDcim = () => {};
CSS = {escape: (s) => String(s)};
window.location.href = 'http://x/admin?tab=dcim';
let escrita = '';
window.history = {replaceState: (estado, titulo, url) => { escrita = String(url); }};
__out = {};

// ── La dirección ────────────────────────────────────────────────────────────────
_dcsPlan = {site: {uid: 's2'}, floor: 'p1', floors: []};
_dcimUrl();
__out.urlPlano = escrita;
window.location.href = escrita;
_dcsPlan = null;
_dcimUrl();
__out.urlSinPlano = escrita;
window.location.href = escrita;
_dcimBoard = {};
_dcimUrl();
__out.urlCuadro = escrita;
_dcimBoard = null;

// ── Volver de un armario ────────────────────────────────────────────────────────
_dcimFold = new Set(['s2']);
_dcimRack = {rack: {uid: 'k2', room_uid: 'r2'}};
_dcimRemember();
__out.deArmario = _dcimCameFrom;
__out.elegida = _dcimSel;
__out.desplegada = !_dcimFold.has('s2');
_dcimRack = null;
// Lo marcado y la vista llevada hasta él, una vez.
const clases = [];
let vistas = 0;
const chip = {classList: {add: (c) => clases.push(c)}, scrollIntoView: () => { vistas++; }};
const qsOrig = document.querySelector;
document.querySelector = (sel) => (sel.includes('data-dcim-rack="k2"') ? chip : null);
_dcimRevealCameFrom();
_dcimRevealCameFrom();
__out.marcado = clases[0];
__out.vistas = vistas;
document.querySelector = qsOrig;

// ── Volver de una sala y de una sede ────────────────────────────────────────────
_dcimPlan = {room: {uid: 'r1'}};
_dcimRemember();
__out.deSala = _dcimCameFrom;
_dcimPlan = null;
_dcsPlan = {site: {uid: 's1'}, floor: '', floors: []};
_dcimRemember();
__out.deSede = _dcimCameFrom;
_dcsPlan = null;
// De una sede no se rodea nada: se rodeaba el bloque entero de la sede (en la ficha, todo).
const clasesSede = [];
const getOrig2 = document.getElementById;
document.getElementById = (id) => ({scrollIntoView() {}, classList: {add: (c) => clasesSede.push(id)}});
_dcimRevealCameFrom();
document.getElementById = getOrig2;
__out.sedeSinBorde = clasesSede.length === 0;

// ── Lo elegido en el inventario, en la dirección ────────────────────────────────
window.location.href = 'http://x/admin?tab=dcim';
_dcimRack = null; _dcimPlan = null; _dcsPlan = null; _dcimBoard = null;
_dcimInvShown = () => false;
_dcimPickSite('s2', 'r2');
__out.urlElegida = escrita;
// Un F5: la dirección vuelve a elegirla, desplegada, y la vista va hasta ella.
_dcimSel = {site: '', room: ''};
_dcimFold = new Set(); _dcimFoldSeen = new Set();
_dcimUrlReadSel(new URL(escrita).searchParams);
_dcimFoldNew();
__out.tras5 = {sel: _dcimSel, plegada: _dcimFold.has('s2')};
let fueA = '';
const getOrig = document.getElementById;
document.getElementById = (id) => ({scrollIntoView: () => { fueA = id; }, classList: {add() {}}});
_dcimCameFrom = null;
_dcimRevealCameFrom();
document.getElementById = getOrig;
__out.vistaA = fueA;
// Con un rack abierto, la dirección es la del rack y no la de lo elegido.
_dcimRack = {rack: {uid: 'k2', room_uid: 'r2'}};
window.location.href = escrita;
_dcimUrl();
__out.urlConRack = escrita;
_dcimRack = null;

// ── «Inventario» en el menú, con un rack abierto ────────────────────────────────
_sbPageView = () => 'inventory';
_sbHighlightSub = () => {};   // el menú lateral no es lo que se prueba aquí
_dcimRack = {rack: {uid: 'k2', room_uid: 'r2'}};
__out.repintadoNoSale = _dcimViewWanted() === false && _dcimRack !== null;
window._ssNavPicked = {pageId: 'dcim', slug: 'inventory'};
__out.menuSale = _dcimViewWanted() === true && _dcimRack === null;
__out.menuMarca = _dcimCameFrom && _dcimCameFrom.rack;

// ── Elegir otra cosa quita la marca ─────────────────────────────────────────────
_dcimInvShown = () => false;
_dcimPickSite('s2');
__out.otraQuita = _dcimCameFrom === null;
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


class TestLaDireccion:
    def test_el_plano_de_una_sede_va_en_la_direccion(self, out):
        assert 'siteplan=s2' in out['urlPlano'] and 'floor=p1' in out['urlPlano']

    def test_y_se_quita_al_salir(self, out):
        assert 'siteplan=' not in out['urlSinPlano'] and 'floor=' not in out['urlSinPlano']

    def test_el_cuadro_de_mando_llega_a_la_direccion(self, out):
        assert 'view=board' in out['urlCuadro']


class TestVolverAlInventario:
    def test_de_un_armario_queda_elegida_su_sede_y_su_sala(self, out):
        assert out['deArmario'] == {'site': 's2', 'room': 'r2', 'rack': 'k2'}
        assert out['elegida'] == {'site': 's2', 'room': 'r2'}
        assert out['desplegada'], 'se vuelve a una sede plegada'

    def test_se_marca_y_se_lleva_a_la_vista_una_vez(self, out):
        assert out['marcado'] == 'ss-came-from'
        assert out['vistas'] == 1

    def test_de_una_sala_y_de_una_sede(self, out):
        assert out['deSala'] == {'site': 's1', 'room': 'r1', 'rack': ''}
        assert out['deSede'] == {'site': 's1', 'room': '', 'rack': ''}

    def test_una_sede_no_se_rodea(self, out):
        """Reportado: al volver del plano de una sede, un borde azul sobre toda la ficha."""
        assert out['sedeSinBorde']

    def test_elegir_otra_cosa_quita_la_marca(self, out):
        assert out['otraQuita']

    def test_inventario_en_el_menu_sale_del_rack(self, out):
        """Reportado: con un rack abierto, «Inventario» en el menú lateral no hacía nada."""
        assert out['repintadoNoSale'], 'un repintado cualquiera no debe sacar del rack'
        assert out['menuSale']
        assert out['menuMarca'] == 'k2'


class TestLoElegidoSobreviveAlF5:
    """Reportado con la ficha en Home › CPD: tras un F5 volvía a elegirse la primera sede."""

    def test_va_en_la_direccion(self, out):
        assert 'site=s2' in out['urlElegida'] and 'site_room=r2' in out['urlElegida']

    def test_se_vuelve_a_elegir_desplegada(self, out):
        assert out['tras5']['sel'] == {'site': 's2', 'room': 'r2'}
        assert not out['tras5']['plegada'], 'el plegado de la primera vez la vuelve a plegar'

    def test_y_la_vista_va_hasta_ella(self, out):
        assert out['vistaA'] == 'dcim-room-r2'

    def test_con_un_rack_abierto_la_direccion_es_la_del_rack(self, out):
        assert 'rack=k2' in out['urlConRack'] and 'site=' not in out['urlConRack']
