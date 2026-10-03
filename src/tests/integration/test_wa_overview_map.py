#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El mapa del panel de control, **dibujado**.

Un mapa falla de una manera que ninguna otra tarjeta puede fallar: **poniendo una cosa en el
sitio de al lado**. No revienta, no sale vacío, no da un error — sale un mapa perfectamente
creíble con una sede a doscientos kilómetros de donde está. Y un mapa que sitúa mal por poco es
peor que uno que no sitúa: el primero se cree.

Por eso esto ejecuta el dibujante con datos delante en lugar de leer el fuente. Lo que se
comprueba es lo que no se puede comprobar leyendo:

* que **todas** las chinchetas caigan dentro del encuadre. Es la trampa que los dos mapas de
  infraestructura ya pisaron: un marco calculado sin contar una de sus cajas la deja fuera de la
  pantalla, y ahí no hay nada que mirar que diga que falta;
* que lo que va mal lleve su nombre escrito y lo que va bien no, que es lo que hace legible una
  tarjeta con quince puntos;
* que una sede **sin coordenadas** no se dibuje y **sí se cuente**. Una sede que desaparece del
  mapa parece una que está bien, y ese es exactamente el engaño que no se puede dejar pasar en
  algo que se mira desde la puerta;
* y que sin servidor de teselas no se pida ni una imagen a nadie. El mapa está apagado de
  fábrica a propósito: encenderlo hace que el navegador de cada persona le cuente a un tercero
  dónde están los datacenters de esta organización.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402
from werkzeug.security import generate_password_hash           # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='sin node: no hay con qué ejecutar el guion')

#: Cuatro sedes muy separadas —Madrid, Fráncfort, Reikiavik y Santiago de Chile— para que el
#: encuadre tenga que estirarse de verdad, más una sin coordenadas y una en el (0, 0), que es lo
#: que deja un formulario con los dos campos vacíos.
_SEDES = [
    {'uid': 's1', 'name': 'Nave Norte', 'state': 'error', 'lat': 40.4168, 'lon': -3.7038,
     'ok': 8, 'total': 12, 'bad': 4, 'unwatched': 0, 'rooms': 2, 'racks': 9},
    {'uid': 's2', 'name': 'Fráncfort', 'state': 'ok', 'lat': 50.1109, 'lon': 8.6821,
     'ok': 30, 'total': 30, 'bad': 0, 'unwatched': 0, 'rooms': 1, 'racks': 4},
    {'uid': 's3', 'name': 'Reikiavik', 'state': 'warning', 'lat': 64.1466, 'lon': -21.9426,
     'ok': 5, 'total': 6, 'bad': 1, 'unwatched': 0, 'rooms': 1, 'racks': 2},
    {'uid': 's4', 'name': 'Santiago', 'state': '', 'lat': -33.4489, 'lon': -70.6693,
     'ok': 0, 'total': 0, 'bad': 0, 'unwatched': 0, 'rooms': 0, 'racks': 0},
    {'uid': 's5', 'name': 'Sin coordenadas', 'state': 'error', 'lat': None, 'lon': None,
     'ok': 1, 'total': 3, 'bad': 2, 'unwatched': 0, 'rooms': 1, 'racks': 1},
    {'uid': 's6', 'name': 'Cero cero', 'state': 'ok', 'lat': 0, 'lon': 0,
     'ok': 2, 'total': 2, 'bad': 0, 'unwatched': 0, 'rooms': 1, 'racks': 1},
]

_VISTA = {'kind': 'map', 'icon': 'bi-geo-alt-fill', 'title_key': 'overview_dcim_sites',
          'accent': 'teal', 'data_url': '/api/v1/overview/widget/dcim_sites',
          'empty_key': 'overview_dcim_sites_none',
          # Adónde lleva pulsar una chincheta, que lo dice quien trae los puntos.
          'pin_nav': 'dcimGoSite'}

_PRUEBA = """
const SEDES = %(sedes)s;
const VISTA = %(vista)s;
const TESELAS = 'https://tile.example.org/{z}/{x}/{y}.png';

/** Dónde cae cada chincheta y qué encuadre se dibujó, leído del MARCADO — que es lo que ve
 *  quien mira, y no lo que la función se dijo por dentro. */
function leer(html) {
    const vb = (html.match(/viewBox="([-\\d.e ]+)"/) || [])[1] || '';
    const [x, y, w, h] = vb.split(' ').map(Number);
    const pines = [];
    // Sin el `>` del final: desde que una chincheta se puede señalar y pulsar, la etiqueta
    // lleva sus gestos escritos detrás de la posición. Y con el `style` detrás, que es lo que
    // separa una chincheta de su rótulo: el rótulo es otro grupo con otra traslación, y
    // contarlo también convertía cuatro sedes en seis.
    const re = /<g transform="translate\\(([-\\d.e]+),([-\\d.e]+)\\)" style/g;
    let m;
    while ((m = re.exec(html))) pines.push({x: Number(m[1]), y: Number(m[2])});
    return {box: {x, y, w, h}, pines, imagenes: (html.match(/<image /g) || []).length};
}

__out = {};

// ── Con teselas ──────────────────────────────────────────────────────────────────
const conMapa = _dwRenderMap('dcim_sites', VISTA,
    {sites: SEDES, tiles: TESELAS, attribution: '© Quien sea', unplaced: 2});
__out.conMapa = conMapa;
const leido = leer(conMapa);
__out.box = JSON.stringify(leido.box);
__out.pines = JSON.stringify(leido.pines);
__out.imagenes = leido.imagenes;
// ¿Cae cada sede CON coordenadas dentro del encuadre?
const dentro = SEDES.filter(ssGeoHas).map(s => {
    const p = ssGeoProject(s.lat, s.lon);
    return (p.x >= leido.box.x && p.x <= leido.box.x + leido.box.w
            && p.y >= leido.box.y && p.y <= leido.box.y + leido.box.h) ? '' : s.uid;
}).filter(Boolean);
__out.fuera = JSON.stringify(dentro);
__out.situadas = SEDES.filter(ssGeoHas).length;

// ── Sin teselas ──────────────────────────────────────────────────────────────────
const sinMapa = _dwRenderMap('dcim_sites', VISTA, {sites: SEDES, tiles: '', unplaced: 2});
__out.sinMapa = sinMapa;
__out.sinImagenes = leer(sinMapa).imagenes;

// ── Todavía sin datos, y sin nada que situar ─────────────────────────────────────
__out.esperando = _dwRenderMap('dcim_sites', VISTA, null);
// Lo que el pie TIENE que decir, preguntado al catálogo: buscar la frase en castellano en una
// sesión en inglés es una comprobación que pasa siempre.
__out.pie = (conMapa.match(/ss-map-credit">([^<]*)</) || [])[1] || '';
__out.diceSinUbicar = tf('overview_map_unplaced', 2);
__out.diceProblemas = tf('overview_map_trouble', 3);
__out.diceSedes = tf('overview_map_sites', 6);
__out.diceSinTeselas = t('overview_map_no_tiles');

// ── El punto que falla dice QUÉ le pasa ─────────────────────────────────────────
// Un nombre dice dónde ir y no dice a qué se va: si son dos máquinas de trece o son las trece,
// si es un aviso o está caída. Eso decide si se llama a alguien de madrugada, y estaba a un
// hover de distancia — que en un panel que se mira de reojo es no estar.
const VISTA_CUENTA = Object.assign({}, VISTA, {count_key: 'dcim_board_tile'});
__out.rotuloMalo = _dwMapPin(SEDES[0], {x: 0, y: 0}, 1, 'w', VISTA_CUENTA, true);
__out.rotuloBueno = _dwMapPin(SEDES[1], {x: 0, y: 0}, 1, 'w', VISTA_CUENTA, true);
__out.rotuloSinSitio = _dwMapPin(SEDES[0], {x: 0, y: 0}, 1, 'w', VISTA_CUENTA, false);
__out.diceCaido = _dwMapWord('error');
__out.diceCuenta = tf('dcim_board_tile', 9, 2);
// Y sin vista tampoco se rompe: sale el rótulo sin el renglón que no se puede escribir.
__out.rotuloSinVista = _dwMapPin(SEDES[0], {x: 0, y: 0}, 1, 'w', {}, true);
// Dos sedes caídas en la misma ciudad: un rótulo, no dos encima.
const JUNTAS = [
    {uid: 'j1', name: 'Nave A', state: 'warning', lat: 42.8169, lon: -1.6432,
     ok: 1, total: 2, rooms: 1, racks: 1},
    {uid: 'j2', name: 'Nave B', state: 'error', lat: 42.8100, lon: -1.6400,
     ok: 0, total: 5, rooms: 1, racks: 1},
];
__out.pinesJuntas = _dwMapDraw({sites: JUNTAS, tiles: TESELAS, wid: 'w'},
                               1400, 400, null, VISTA_CUENTA).chinchetas;

// ── Y el resumen dice CUÁNTAS hay de cada ───────────────────────────────────────
// El dibujo contesta «dónde» y no contesta «cuántas»: dos puntos rojos en la misma ciudad son
// un punto rojo, y contar chinchetas a ojo se cuenta mal.
__out.resumen = _dwMapTally({sites: SEDES});
__out.resumenVacio = _dwMapTally({sites: [SEDES[1]]});
__out.diceVacio = t('overview_dcim_sites_none');
__out.vacio = _dwRenderMap('dcim_sites', VISTA, {sites: [SEDES[4]], tiles: '', unplaced: 1});

// ── Una sola sede: el encuadre no puede medir cero ───────────────────────────────
const una = leer(_dwRenderMap('dcim_sites', VISTA,
    {sites: [SEDES[0]], tiles: TESELAS, unplaced: 0}));
__out.unaBox = JSON.stringify(una.box);

// ── El tamaño de una chincheta no depende de lo que abarque el mapa ──────────────
// Dos sedes juntas y dos muy separadas: el radio EN COORDENADAS DEL MUNDO tiene que crecer con
// el encuadre, que es lo que hace que se vea igual de grande en pantalla.
const radio = (html) => Number((html.match(/<circle r="([\\d.]+)"/) || [])[1]);
__out.radioCerca = radio(_dwRenderMap('x', VISTA, {sites: [
    {uid: 'a', name: 'A', state: 'ok', lat: 40.41, lon: -3.70, ok: 1, total: 1},
    {uid: 'b', name: 'B', state: 'ok', lat: 40.42, lon: -3.71, ok: 1, total: 1}], tiles: ''}));
__out.radioLejos = radio(_dwRenderMap('x', VISTA, {sites: [
    {uid: 'a', name: 'A', state: 'ok', lat: 64.14, lon: -21.94, ok: 1, total: 1},
    {uid: 'b', name: 'B', state: 'ok', lat: -33.44, lon: -70.66, ok: 1, total: 1}], tiles: ''}));

// ── Y con la forma que tiene la tarjeta de verdad, y con zoom ───────────────────
// Una tarjeta del panel es mucho más ancha que alta —en la pantalla desde la que se reportó
// esto, 1400 x 320—, y un encuadre con otra proporción deja bandas vacías a los lados: `meet`
// encaja el dibujo entero dentro y lo que sobra se queda vacío. Sólo se puede arreglar
// midiendo, y sólo se puede medir cuando ya está puesto.
//
// El `<svg>` de mentira tiene que estar DONDE EL LIENZO LO BUSCA (`getElementById`), porque
// desde que el mapa se maneja con la rueda es el lienzo compartido quien escribe el `viewBox`.
const CID = 'dwmap-dcim_sites';
function svgDeMentira(ancho, alto) {
    return {
        // `zoomIn` lo escribe `_dwMapFit` al medir: cuánto se puede acercar depende de lo que
        // abarque el encuadre y de lo ancha que sea la tarjeta.
        dataset: {dwmap: 'dcim_sites', zoomOut: '3'},
        clientWidth: ancho, clientHeight: alto,
        _vb: 'intacto',
        _g: {'.dw-map-tiles': {innerHTML: ''}, '.dw-map-pins': {innerHTML: ''}},
        setAttribute(k, v) { if (k === 'viewBox') this._vb = v; },
        querySelector(sel) { return this._g[sel]; },
        getBoundingClientRect() { return {top: 0, left: 0, width: ancho, height: alto}; },
    };
}
const svgFalso = svgDeMentira(1400, 320);
const _getOrig = document.getElementById;
document.getElementById = (id) => (id === CID ? svgFalso : _getOrig(id));

_dwFetched['dcim_sites'] = {sites: SEDES, tiles: TESELAS, unplaced: 2};
ssCanvasReset(CID);
_dwMapFit(svgFalso);
__out.vbMedido = svgFalso._vb;
__out.pinesMedidos = svgFalso._g['.dw-map-pins'].innerHTML;
__out.teselasMedidas = (svgFalso._g['.dw-map-tiles'].innerHTML.match(/<image /g) || []).length;
// ¿Sigue cayendo todo dentro después de medir? Es la misma pregunta de arriba, con la forma
// que de verdad tiene la tarjeta — y la que decide si un encuadre nuevo esconde una sede.
const dentroDe = (vb) => {
  const [mx, my, mw, mh] = vb.split(' ').map(Number);
  return JSON.stringify(SEDES.filter(ssGeoHas).map(x => {
      const p = ssGeoProject(x.lat, x.lon);
      return (p.x >= mx && p.x <= mx + mw && p.y >= my && p.y <= my + mh) ? '' : x.uid;
  }).filter(Boolean));
};
__out.fueraMedido = dentroDe(svgFalso._vb);

// ── La rueda ────────────────────────────────────────────────────────────────────
const anchoDe = (vb) => Number(vb.split(' ')[2]);
const zNivel = (html) => Number((html.match(/example\.org\/(\d+)\//) || [])[1]);
__out.anchoDeSalida = anchoDe(svgFalso._vb);
__out.zSalida = zNivel(svgFalso._g['.dw-map-tiles'].innerHTML);
__out.zMax = SS_GEO_ZMAX;
__out.radioSalida = Number((svgFalso._g['.dw-map-pins'].innerHTML.match(/<circle r="([\d.]+)"/) || [])[1]);

// Acercarse de verdad: se gira la rueda hasta que no se puede más. Ciento veinte vueltas, que
// desde un encuadre de mil doscientos kilómetros es lo que hay hasta el final.
for (let i = 0; i < 120; i++) ssCanvasZoomAt(CID, 1.18, 513000, 395000);
__out.anchoCerca = anchoDe(svgFalso._vb);
// Y adónde TENÍA que llegar: la ventana que enseña las teselas más finas a tamaño natural.
__out.natural = ssGeoDeepest(1400);
__out.topeDeclarado = Number(svgFalso.dataset.zoomIn);
__out.zCerca = zNivel(svgFalso._g['.dw-map-tiles'].innerHTML);
__out.radioCercaZoom = Number((svgFalso._g['.dw-map-pins'].innerHTML.match(/<circle r="([\d.]+)"/) || [])[1]);
__out.teselasCerca = (svgFalso._g['.dw-map-tiles'].innerHTML.match(/<image /g) || []).length;

// Y que el refresco automático NO le quite el zoom de las manos a quien está mirando.
__out.tocada = ssCanvasWindowKept(CID);
_dwMapFit(svgFalso);
__out.anchoTrasRefresco = anchoDe(svgFalso._vb);

// Dos pulsaciones vuelven al encuadre completo.
ssCanvasFit(CID);
__out.anchoTrasVolver = anchoDe(svgFalso._vb);
__out.fueraTrasVolver = dentroDe(svgFalso._vb);

// Y sin nada medible —una tarjeta escondida mide cero— no se toca nada, en vez de dejar un
// `viewBox` de anchura cero que no dibuja nada.
ssCanvasReset(CID);
const svgCero = svgDeMentira(0, 0);
document.getElementById = (id) => (id === CID ? svgCero : _getOrig(id));
_dwMapFit(svgCero);
__out.vbCero = svgCero._vb;
document.getElementById = _getOrig;
ssCanvasReset(CID);

// ── Y hasta dónde llega el servidor que sirve las imágenes ──────────────────────
// No es el mismo en todos —OpenStreetMap 19, Carto 20, Google 22— y un espejo interno trae lo
// que traiga. Pedir un nivel que no existe no da error: deja huecos en blanco al acercarse.
const conTope = (zmax) => {
    ssCanvasReset(CID);
    _dwFetched['dcim_sites'] = {sites: SEDES, tiles: TESELAS, unplaced: 2, zmax: zmax};
    _dwMapFit(svgFalso);
    const salida = anchoDe(svgFalso._vb);
    for (let i = 0; i < 120; i++) ssCanvasZoomAt(CID, 1.18, 513000, 395000);
    const cerca = anchoDe(svgFalso._vb);
    const z = zNivel(svgFalso._g['.dw-map-tiles'].innerHTML);
    return {salida, cerca, z, tope: Number(svgFalso.dataset.zoomIn)};
};
document.getElementById = (id) => (id === CID ? svgFalso : _getOrig(id));
__out.corto = JSON.stringify(conTope(16));
__out.largo = JSON.stringify(conTope(22));
__out.sinDecir = JSON.stringify(conTope(undefined));
document.getElementById = _getOrig;
ssCanvasReset(CID);
_dwFetched['dcim_sites'] = {sites: SEDES, tiles: TESELAS, unplaced: 2};

// ── El tope de teselas, pedido de verdad ────────────────────────────────────────
// Con el encuadre de la tarjeta salen cuatro o cinco y el tope no llega a decidir nada: para
// saber si existe hay que pedirle el mundo entero al nivel de la calle.
const contar = (h) => (h.match(/<image /g) || []).length;
__out.tope = contar(ssGeoTiles(TESELAS, {x: 0, y: 0, w: SS_GEO_WORLD, h: SS_GEO_WORLD},
                               SS_GEO_Z, 60));
// Y el mundo da la vuelta: una tesela de la columna −1 es la última. Sin eso, cruzar el
// antimeridiano deja media pantalla en blanco — o pide una dirección con un número negativo,
// que ningún servidor de teselas contesta.
__out.vuelta = ssGeoTiles(TESELAS, {x: -600, y: SS_GEO_WORLD / 2, w: 1200, h: 300}, 1, 60);

// ── La ficha que sale al señalar un punto ───────────────────────────────────────
// Con todo lo que una sede puede saber de sí misma, y con una que no sabe nada.
const RICA = {
  uid: 's1', name: 'Nave Norte', state: 'error', lat: 42.81, lon: -1.64,
  ok: 8, total: 12, rooms: 2, racks: 9,
  address: 'Pol. Ind. Ejemplo, 12', contact: 'Portería', phone: '+34 900 00 00 00',
  photo: '/api/v1/dcim/media/own/abc.png', operator: 'IT del grupo',
  description: 'La nave de arriba', timezone: 'Europe/Madrid',
};
const PELADA = {uid: 's2', name: 'Sin nada', state: 'ok', ok: 1, total: 1, rooms: 1, racks: 1};
const MALA = {uid: 's3', name: '<img src=x onerror=alert(1)>', state: 'ok',
              address: '<b>calle</b>', ok: 0, total: 0};
__out.ficha = _dwMapCardHtml(RICA);
__out.fichaPelada = _dwMapCardHtml(PELADA);
__out.fichaMala = _dwMapCardHtml(MALA);

// ── Y pulsar lleva a ESA sede ───────────────────────────────────────────────────
// El arnés no ejecuta lo aplazado, y la navegación lo está a propósito: la sección a la que se
// va no está dibujada hasta que la pestaña se abre.
const _stOrig = setTimeout;
setTimeout = (fn) => { try { fn(); } catch (e) { __out.errNav = String(e); } return 0; };
// Y el cambio de pestaña se sustituye: mueve una interfaz de Bootstrap que aquí no existe, y
// lo que se comprueba es que se pida —con la tarjeta correcta—, no cómo se hace.
const _navOrig = _dwNavigate;
_dwNavigate = (w) => { __out.navegado = w; };
__out.llamado = '';
dcimGoSite = (uid) => { __out.llamado = uid; };
_DW_DEFS['dcim_sites'] = {view: VISTA, canShow: () => true};

// El gesto de verdad, y no la función de dentro: pulsar una chincheta NO es un `onclick` suyo.
// El lienzo captura el puntero para poder arrastrar fuera del dibujo, y con la captura puesta el
// navegador dispara el `click` en el `<svg>` — la chincheta no lo ve pasar. Así estuvo escrito y
// así pasaba esta prueba mientras en la pantalla no ocurría nada.
const chincheta = {dataset: {site: 'u-nave'}};
const baja = (x, y, g) => ({clientX: x, clientY: y, pointerId: 1,
                            target: {closest: () => g},
                            currentTarget: {setPointerCapture() {}, style: {}}});
const sube = (x, y) => ({clientX: x, clientY: y, currentTarget: {style: {}}});

_dwMapDown(baja(10, 10, chincheta), CID, 'dcim_sites');
_dwMapUp(sube(11, 11), CID, 'dcim_sites');
__out.llamadoConPin = __out.llamado;
__out.navegadoConPin = __out.navegado;

// Un arrastre que empezó encima de una chincheta NO es pulsarla: es mover el mapa.
__out.llamado = ''; __out.navegado = '';
_dwMapDown(baja(10, 10, chincheta), CID, 'dcim_sites');
_dwMapMove({clientX: 90, clientY: 60}, CID);
_dwMapUp(sube(90, 60), CID, 'dcim_sites');
__out.llamadoTrasArrastrar = __out.llamado;

// Y pulsar el mapa donde no hay nada tampoco lleva a ninguna parte.
__out.llamado = ''; __out.navegado = '';
_dwMapDown(baja(10, 10, null), CID, 'dcim_sites');
_dwMapUp(sube(10, 10), CID, 'dcim_sites');
__out.llamadoSinChincheta = __out.llamado;
__out.navegadoSinChincheta = __out.navegado;

// Y una tarjeta que no dice adónde lleva no lleva a ninguna parte, en vez de reventar.
__out.llamado = '';
_DW_DEFS['sin_nav'] = {view: {kind: 'map'}, canShow: () => true};
_dwMapDown(baja(10, 10, chincheta), CID, 'sin_nav');
_dwMapUp(sube(10, 10), CID, 'sin_nav');
__out.llamadoSinNav = __out.llamado;
setTimeout = _stOrig;
_dwNavigate = _navOrig;

// ── El tinte de la tarjeta sale de lo que sirvió el widget ───────────────────────
_DW_DEFS['dcim_sites'] = {view: VISTA, canShow: () => true};
_dwFetched['dcim_sites'] = {sites: SEDES, state: 'error'};
__out.tinte = _dwState('dcim_sites', {}, null);
_dwFetched['dcim_sites'] = {sites: SEDES, state: ''};
__out.sinTinte = _dwState('dcim_sites', {}, null);
""" % {'sedes': json.dumps(_SEDES), 'vista': json.dumps(_VISTA)}


@pytest.fixture(scope='module')
def mapa():
    """El mapa, dibujado de verdad."""
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


class TestElPuntoQueFallaDiceQueLePasa:
    """Un nombre dice dónde ir; no dice a qué se va. «Home» sobre un mapa no distingue dos
    máquinas de trece de las trece, ni un aviso de una caída — y eso es lo que decide si se
    llama a alguien de madrugada. Estaba en la ficha que sale al pasar por encima, que en un
    panel que se mira de reojo desde la puerta es como no estar. Reportado desde la pantalla."""

    def _rotulo(self, html):
        """Sólo el rótulo, y no el `<title>` de la chincheta. El nombre y el estado salen
        tambien ahi —es lo que lee un lector de pantalla y lo que sale si la ficha no llegara a
        dibujarse—, asi que buscarlos en el marcado entero da por bueno lo que no lo es: se
        comprobo asi y una mutacion que borraba el renglon del estado pasaba la prueba."""
        return html.split('<rect width=', 1)[1] if '<rect width=' in html else ''

    def test_el_rotulo_lleva_el_estado_y_la_cuenta(self, mapa):
        rotulo = self._rotulo(mapa['rotuloMalo'])
        assert f">{mapa['diceCaido']} " in rotulo, rotulo
        assert '8/12</text>' in rotulo, rotulo
        assert '>Nave Norte</text>' in rotulo, rotulo

    def test_y_los_armarios_cuando_la_vista_dice_con_qué_palabra(self, mapa):
        """El recuento es del dominio que trae los puntos, no de este fichero: sin la clave en
        la vista no hay renglón, y el rótulo sale igual con lo demás."""
        assert mapa['diceCuenta'] in self._rotulo(mapa['rotuloMalo'])
        assert mapa['diceCuenta'] not in self._rotulo(mapa['rotuloSinVista'])
        assert f">{mapa['diceCaido']} " in self._rotulo(mapa['rotuloSinVista'])

    def test_lo_que_esta_bien_no_lleva_rotulo(self, mapa):
        """Quince rótulos en una tarjeta de este tamaño se pisan y no se lee ninguno. Lo que
        hace falta leer es lo que está mal; lo demás es un punto verde que ya lo dice todo."""
        assert '<rect width=' not in mapa['rotuloBueno'], mapa['rotuloBueno']

    def test_el_fondo_del_rotulo_es_un_color_solido(self, mapa):
        """Y no un tinte: `--bs-danger-bg-subtle` es en este panel un rojo al diez por ciento,
        y sobre un mapa no hay fondo de página debajo que lo sostenga. Le pasó al mapa de la
        sección y costó tres rondas; está en `docs/caso-diagnostico.md`."""
        suelo = mapa['rotuloMalo'].split('<rect width=')[1].split('>')[0]
        assert 'var(--bs-body-bg)' in suelo, suelo
        assert 'subtle' not in suelo, suelo

    def test_y_dos_juntas_no_son_dos_rotulos_encima(self, mapa):
        """La misma regla que el mapa de la sección, y por el mismo sitio: el que choca se queda
        con su punto. Aquí sólo llevan rótulo las que van mal, así que la pila es más rara — y
        cuando pasa, se queda con el sitio la que está peor."""
        assert mapa['pinesJuntas'].count('<rect width=') == 3, mapa['pinesJuntas'].count(
            '<rect width=')
        # Por el TEXTO del rótulo: el nombre sale también en el `<title>` de la chincheta —que
        # es lo que lee un lector de pantalla— y buscarlo ahí daría por bueno lo que no lo es.
        assert '>Nave B</text>' in mapa['pinesJuntas']
        assert '>Nave A</text>' not in mapa['pinesJuntas']

    def test_y_la_que_se_queda_sin_el_sigue_siendo_pulsable(self, mapa):
        assert 'data-site="s1"' in mapa['rotuloSinSitio']
        assert '<rect width=' not in mapa['rotuloSinSitio']


class TestElResumenDiceCuantasHayDeCada:
    """El dibujo contesta «dónde», que es lo que ninguna otra tarjeta contesta. No contesta
    «cuántas»: para saber si son dos o siete las que están mal hay que contar chinchetas a ojo, y
    a ojo se cuenta mal — dos puntos rojos en la misma ciudad son un punto rojo."""

    def _n(self, html):
        import re                                                    # noqa: PLC0415
        return [int(x) for x in re.findall(r'</i>(\d+)</span>', html)]

    def test_los_cuatro_estados_con_su_cuenta(self, mapa):
        """Lo peor primero, que es como se lee de izquierda a derecha."""
        assert self._n(mapa['resumen']) == [2, 1, 2, 1], mapa['resumen']

    def test_y_cuenta_TODAS_las_sedes_y_no_las_dibujadas(self, mapa):
        """Una sede sin coordenadas no sale en el mapa, y no salir no es estar bien. Son seis
        sedes y cinco chinchetas; el resumen cuenta seis, y de las que no se dibujan ya avisa el
        pie."""
        assert sum(self._n(mapa['resumen'])) == len(_SEDES)

    def test_el_cero_se_dice_igual(self, mapa):
        """«Ninguna caída» es una respuesta, y la que más se viene a buscar. Enseñarla sólo
        cuando hay alguna obligaría a deducirla de una ausencia."""
        assert self._n(mapa['resumenVacio']) == [0, 0, 1, 0], mapa['resumenVacio']
        assert 'ss-map-tally-none' in mapa['resumenVacio']

    def test_cada_estado_con_su_signo_y_no_solo_su_color(self, mapa):
        """Un punto de color no se lee de todas las formas en que la gente lee: quien no separa
        el rojo del verde ve cuatro puntos iguales con cuatro numeros, y en una pantalla en
        blanco y negro no hay color que valga. Reportado desde la pantalla.

        Cuatro signos DISTINTOS: repetir uno es volver a dejarlo todo en el color."""
        import re                                                    # noqa: PLC0415
        iconos = re.findall(r'class="bi (bi-[a-z-]+) text-', mapa['resumen'])
        assert len(iconos) == 4, iconos
        assert len(set(iconos)) == 4, iconos

    def test_y_el_signo_no_se_construye_con_el_nombre_del_estado(self):
        """Una clave armada con `'bi-' + estado` no la ve nadie —ni un `grep` ni un guardian— y
        asi es como cuatro palabras llegaron a la pantalla sin existir en ningun idioma."""
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        from tests.helpers import _strip_comments                # noqa: PLC0415
        js = _strip_comments(_io.open(
            _os.path.join(src, 'lib', 'web_admin', 'templates', 'partials',
                          'overview', '_widgets.html'), encoding='utf-8-sig').read())
        assert "'bi-' +" not in js and '`bi-${' not in js

    def test_pero_apagado(self, mapa):
        """El color se guarda para lo que sí está pasando."""
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        css = _io.open(_os.path.join(src, 'lib', 'web_admin', 'static', 'css',
                                     'web_admin.css'), encoding='utf-8-sig').read()
        assert '.ss-map-tally-none' in css

    def test_y_no_atrapa_el_puntero(self, mapa):
        """Encima de un mapa que se arrastra, cualquier cosa que atrape el puntero es un trozo
        de mapa que no se puede agarrar. Le pasa igual al pie de créditos."""
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        css = _io.open(_os.path.join(src, 'lib', 'web_admin', 'static', 'css',
                                     'web_admin.css'), encoding='utf-8-sig').read()
        regla = css.split('.ss-map-tally {')[1].split('}')[0]
        assert 'pointer-events: none' in regla, regla


class TestTodoLoQueTieneCoordenadasSeVe:
    """La trampa que los dos mapas de infraestructura ya pisaron: un marco calculado sin contar
    una de sus cajas la deja fuera de la pantalla, y no hay nada que mirar que diga que falta."""

    def test_ninguna_sede_se_queda_fuera_del_encuadre(self, mapa):
        assert json.loads(mapa['fuera']) == [], 'hay sedes fuera del dibujo'

    def test_y_se_dibujan_todas_las_que_tienen_coordenadas(self, mapa):
        pines = json.loads(mapa['pines'])
        assert len(pines) == mapa['situadas'] == 4, (len(pines), mapa['situadas'])

    def test_pero_no_la_que_no_las_tiene(self, mapa):
        """Ni la del (0, 0), que no es una coordenada: es el golfo de Guinea, donde no hay
        ningún datacenter, y es lo que deja un formulario con los dos campos vacíos."""
        assert 'Sin coordenadas' not in mapa['conMapa']
        assert 'Cero cero' not in mapa['conMapa']

    def test_una_sola_sede_no_da_un_encuadre_de_tamaño_cero(self, mapa):
        """Que no es un encuadre: un `viewBox` de anchura cero no dibuja nada."""
        box = json.loads(mapa['unaBox'])
        assert box['w'] > 0 and box['h'] > 0
        # Y abarca lo bastante para ubicar: media ciudad no dice en qué país está.
        assert box['w'] >= 1048576 / 64

    def test_el_encuadre_tiene_la_forma_de_la_tarjeta(self, mapa):
        """Estirado y nunca encogido: encoger sacaría fuera lo que ya cabía — que es el fallo
        de arriba escrito de otra manera."""
        box = json.loads(mapa['box'])
        assert abs(box['h'] / box['w'] - 9 / 16) < 0.001


class TestElMapaLlenaSuTarjeta:
    """Se veía con bandas vacías a los lados. `meet` encaja el dibujo entero dentro de la caja
    y lo que sobra se queda vacío, así que el encuadre tiene que llevar la proporción de la
    caja — y la de una tarjeta del panel no se sabe hasta que está puesta en la pantalla.

    Recortar en vez de encajar sería la otra salida, y es peor: escondería chinchetas, que en un
    mapa de sedes es esconder una sede."""

    def test_el_encuadre_toma_la_proporcion_medida(self, mapa):
        x, y, w, h = [float(v) for v in mapa['vbMedido'].split(' ')]
        assert abs(h / w - 320 / 1400) < 0.001, mapa['vbMedido']

    def test_y_no_la_que_se_supuso_al_escribir_el_html(self, mapa):
        """Si no cambiara nada, medir no serviría de nada — y la prueba de arriba pasaría igual
        con una tarjeta que casualmente fuera 16:9."""
        assert mapa['vbMedido'] != mapa['box']

    def test_y_despues_de_medir_sigue_estando_todo_dentro(self, mapa):
        assert json.loads(mapa['fueraMedido']) == [], 'el encuadre nuevo esconde sedes'

    def test_se_redibuja_lo_que_hay_encima(self, mapa):
        """El encuadre nuevo cambia la escala: unas chinchetas dibujadas para el anterior se
        verían del tamaño que no es, y las teselas serían las de otro trozo de mundo."""
        assert mapa['pinesMedidos'].count('<circle') >= 4
        assert mapa['teselasMedidas'] > 0

    def test_una_tarjeta_que_no_mide_nada_no_se_toca(self, mapa):
        """Escondida, o todavía sin colocar. Un `viewBox` de anchura cero no dibuja nada."""
        assert mapa['vbCero'] == 'intacto'


class TestSePuedeAcercar:
    """Un mapa de sedes encuadrado a todas las sedes enseña un país y ninguna calle, y la
    pregunta que trae a alguien a este mapa es dónde está exactamente esa nave.

    El mismo lienzo que el mapa de la sección —rueda, arrastre y dos pulsaciones para volver—,
    porque dos formas de mover dos mapas del mismo panel son dos que aprender."""

    def test_la_rueda_acerca_hasta_donde_acaban_las_teselas(self, mapa):
        """Y no un número de veces: eso es relativo a lo que se ve al abrir, y lo que se ve al
        abrir depende de dónde estén las sedes. La misma cifra daba una calle en una casa con
        todo en la misma provincia y dos kilómetros y medio en una con sedes de Pamplona a
        Barcelona — reportado desde la pantalla, «no hace suficiente zoom».

        El tope está donde las imágenes dejan de dar más, venga de donde venga el encuadre."""
        assert abs(mapa['anchoCerca'] - mapa['natural']) < 0.01, (
            mapa['anchoDeSalida'], mapa['anchoCerca'], mapa['natural'])

    def test_y_eso_es_mucho_mas_que_el_tope_de_fabrica(self, mapa):
        """Ocho veces es lo que le basta a un plano de sala, que es de donde viene el lienzo."""
        assert mapa['topeDeclarado'] > 100, mapa['topeDeclarado']
        assert mapa['anchoCerca'] < mapa['anchoDeSalida'] / 8

    def test_y_se_piden_las_teselas_de_ese_nivel(self, mapa):
        """Acercarse sin cambiar de nivel es acercarse a una imagen borrosa: la misma foto
        estirada, sin un nombre de calle más. Al final del recorrido, las más finas que hay."""
        assert mapa['zCerca'] > mapa['zSalida'] + 4, (mapa['zSalida'], mapa['zCerca'])
        assert mapa['zCerca'] == mapa['zMax'], (mapa['zCerca'], mapa['zMax'])

    def test_y_no_se_piden_mas_imagenes_por_estar_cerca(self, mapa):
        """Cuanto más cerca, más teselas caben en la pantalla si el nivel no sube con el
        zoom — que es como se le piden cuatrocientas a un servidor voluntario sin querer."""
        assert mapa['teselasCerca'] <= 60

    def test_las_chinchetas_no_crecen_al_acercarse(self, mapa):
        """Se dibujan en coordenadas del mundo: con un radio fijo, al acercarse taparían la
        ciudad entera."""
        assert mapa['radioCercaZoom'] < mapa['radioSalida'] / 100

    def test_el_refresco_no_le_quita_el_zoom_de_las_manos(self, mapa):
        """La tarjeta se repinta sola cada poco. Reencuadrar ahí sería devolver a quien está
        mirando una calle al mapa del país, cada treinta segundos."""
        assert mapa['tocada'] is True
        assert mapa['anchoTrasRefresco'] == mapa['anchoCerca']

    def test_pero_se_puede_volver_al_encuadre(self, mapa):
        """Dos pulsaciones. Sin salida, acercarse es un sitio del que no se vuelve más que
        recargando la página."""
        assert mapa['anchoTrasVolver'] == mapa['anchoDeSalida']
        assert json.loads(mapa['fueraTrasVolver']) == []


class TestLoQueVaMalLlevaSuNombre:
    """Quince rótulos en una tarjeta de este tamaño se pisan y no se lee ninguno. Lo que hace
    falta leer es lo que está mal; lo demás es un punto verde que ya lo dice todo."""

    def test_la_sede_en_error_sale_escrita(self, mapa):
        assert 'Nave Norte' in mapa['conMapa']

    def test_y_la_que_tiene_un_aviso_tambien(self, mapa):
        assert 'Reikiavik' in mapa['conMapa']

    def test_pero_la_que_esta_bien_no(self, mapa):
        """Sale como punto, y su nombre entero al pasar por encima."""
        assert '>Fráncfort<' not in mapa['conMapa'], 'rotula lo que no hace falta leer'
        assert 'Fráncfort' in mapa['conMapa'], 'y ni siquiera se puede consultar'

    def test_cada_estado_lleva_su_color(self, mapa):
        html = mapa['conMapa']
        for tono in ('var(--bs-danger)', 'var(--bs-warning)', 'var(--bs-success)',
                     'var(--bs-secondary)'):
            assert tono in html, tono

    def test_y_lo_que_nadie_vigila_no_sale_verde(self, mapa):
        """Un armario de paneles de parcheo no está bien: es que no hay nada que mirar. Pintarlo
        verde convierte la única pregunta que contesta este dibujo en una mentira."""
        trozo = mapa['conMapa'].split('Santiago')[0]
        assert trozo.rsplit('<g transform', 1)[-1].count('var(--bs-success)') == 0

    def test_al_pasar_por_encima_se_dice_entero(self, mapa):
        """Lo que no cabe escrito tiene que poder consultarse: el nombre, cómo está y cuánto
        contesta de lo que tiene."""
        assert '8/12' in mapa['conMapa']

    def test_una_chincheta_mide_lo_mismo_este_donde_este(self, mapa):
        """En coordenadas del mundo un radio fijo crece al alejarse hasta tapar el país."""
        assert mapa['radioLejos'] > mapa['radioCerca'] * 10


class TestHastaDondeLlegaLoDiceQuienSirveLasImagenes:
    """Y no una constante del guion: no es el mismo en todos —OpenStreetMap llega al 19, Carto al
    20, Google al 22— y un espejo interno trae lo que le hayan cargado. Pedir un nivel que no
    existe no da ningún error: deja huecos en blanco al acercarse, y quien mira cree que el mapa
    se ha roto."""

    def _t(self, mapa, clave):
        return json.loads(mapa[clave])

    def test_un_servidor_que_llega_menos_lejos_deja_acercarse_menos(self, mapa):
        corto, largo = self._t(mapa, 'corto'), self._t(mapa, 'largo')
        assert corto['cerca'] > largo['cerca'], (corto, largo)
        # Seis niveles de diferencia son sesenta y cuatro veces.
        assert abs(corto['cerca'] / largo['cerca'] - 64) < 0.01, (corto, largo)

    def test_y_no_se_le_piden_niveles_que_no_tiene(self, mapa):
        """Es la mitad que se ve: el hueco en blanco sale de pedir una imagen que no existe."""
        assert self._t(mapa, 'corto')['z'] == 16
        assert self._t(mapa, 'largo')['z'] == 22

    def test_sin_decirlo_se_usa_el_mas_comun(self, mapa):
        """Una instalación que no ha tocado nada no puede quedarse sin acercarse."""
        assert self._t(mapa, 'sinDecir')['z'] == 19


class TestSinServidorDeTeselasNoSePideNadaANadie:
    """Apagado de fábrica a propósito: encenderlo hace que el navegador de cada persona le
    cuente a un tercero dónde están los datacenters de esta organización, y en una instalación
    sin salida además no cargaría."""

    def test_no_se_pide_ni_una_imagen(self, mapa):
        assert mapa['sinImagenes'] == 0

    def test_y_aun_asi_las_sedes_se_situan(self, mapa):
        """Sin mapa debajo siguen estando unas respecto a otras, que ya es una respuesta."""
        assert mapa['sinMapa'].count('<circle') >= 4

    def test_y_se_dice_que_no_lo_hay(self, mapa):
        """Un puñado de puntos sobre nada parece una pantalla rota."""
        assert mapa['diceSinTeselas'] in mapa['sinMapa']

    def test_con_teselas_se_piden_las_del_encuadre(self, mapa):
        assert mapa['imagenes'] > 0
        assert 'tile.example.org' in mapa['conMapa']

    def test_y_nunca_mas_de_las_que_caben(self, mapa):
        """Este dibujo se repinta en cada vuelta del refresco automático: pedirle centenares de
        imágenes a un servidor voluntario cada treinta segundos es abusar de quien hace el
        favor.

        Pedido con el mundo entero delante y no con el encuadre de la tarjeta: con cuatro sedes
        salen cinco teselas, el tope no llega a decidir nada, y una comprobación que no puede
        fallar es una que se puede borrar sin que nadie se entere."""
        assert mapa['tope'] == 60

    def test_y_cruzar_el_antimeridiano_no_pide_una_columna_negativa(self, mapa):
        """El mundo da la vuelta: la columna −1 es la última. Una dirección con un número
        negativo dentro no la contesta ningún servidor de teselas, y lo que se ve es media
        pantalla en blanco."""
        assert '/-' not in mapa['vuelta'], mapa['vuelta'][:200]
        assert mapa['vuelta'].count('<image ') >= 2

    def test_el_credito_se_dice_cuando_hay_teselas(self, mapa):
        """La licencia de OpenStreetMap lo exige, y quien apunte esto a otro servidor pondrá el
        suyo — por eso es un campo y no una cadena fija."""
        assert '© Quien sea' in mapa['conMapa']


class TestLoQueElDibujoNoPuedeDecirSeDice:

    def test_las_sedes_sin_coordenadas_se_cuentan(self, mapa):
        """Una sede que desaparece del mapa parece una que está bien."""
        assert mapa['diceSinUbicar'] in mapa['pie'], mapa['pie']

    def test_y_cuantas_van_mal(self, mapa):
        assert mapa['diceProblemas'] in mapa['pie'], mapa['pie']

    def test_y_cuantas_hay_en_total(self, mapa):
        """Seis, no cuatro: las que no se pueden dibujar siguen siendo sedes de esta casa."""
        assert mapa['diceSedes'] in mapa['pie'], mapa['pie']

    def test_mientras_no_ha_llegado_nada_se_ve_que_se_esta_pidiendo(self, mapa):
        assert 'spinner-border' in mapa['esperando']

    def test_y_sin_una_sola_coordenada_se_dice_donde_se_escriben(self, mapa):
        """Un cuadro vacío no se puede distinguir de uno roto, y aquí lo que falta es un dato
        que alguien tiene que ir a escribir."""
        assert mapa['diceVacio'] in mapa['vacio']
        assert '<svg' not in mapa['vacio'], 'dibuja un mapa sin nada que situar'


class TestLaFichaDeUnPunto:
    """Un punto de color dice que algo va mal. Lo que se pregunta a continuación es siempre lo
    mismo —dónde está eso, a quién se llama, qué se ve al llegar— y hasta ahora había que abrir
    tres pantallas para contestarlo."""

    def test_dice_donde_esta(self, mapa):
        assert 'Pol. Ind. Ejemplo, 12' in mapa['ficha']

    def test_y_a_quien_se_llama(self, mapa):
        assert 'Portería' in mapa['ficha']

    def test_con_el_telefono_marcable(self, mapa):
        """Delante de una verja a las tres de la mañana, la diferencia entre un número escrito
        y uno que se pulsa es el número entero. Y en el enlace van los dígitos: un `tel:` con
        espacios dentro no lo marca todo el mundo."""
        assert 'href="tel:+34900000000"' in mapa['ficha'], mapa['ficha']
        assert '+34 900 00 00 00' in mapa['ficha'], 'y se lee como lo escribieron'

    def test_y_ensena_la_foto_del_sitio(self, mapa):
        """Quien va por primera vez busca UNA puerta en un polígono."""
        assert '/api/v1/dcim/media/own/abc.png' in mapa['ficha']

    def test_y_quien_la_lleva_y_que_hora_es_alli(self, mapa):
        assert 'IT del grupo' in mapa['ficha']
        assert 'bi-clock' in mapa['ficha'], 'sin la hora local no se sabe si se puede llamar'

    def test_lo_que_nadie_ha_escrito_no_ocupa_un_renglon(self, mapa):
        """Una ficha con cuatro renglones vacíos enseña sobre todo lo que nadie rellenó."""
        pelada = mapa['fichaPelada']
        for icono in ('bi-geo-alt', 'bi-person', 'bi-telephone', 'bi-building', 'bi-clock',
                      'bi-card-text'):
            assert icono not in pelada, icono
        assert '<img' not in pelada

    def test_pero_lo_que_siempre_hay_si(self, mapa):
        """El nombre, cómo está y cuánto contesta de lo que tiene: eso lo sabe toda sede."""
        assert 'Sin nada' in mapa['fichaPelada']
        assert '1/1' in mapa['fichaPelada']

    def test_y_nada_de_lo_que_alguien_escribio_se_pinta_en_crudo(self, mapa):
        """El nombre y la dirección de una sede los teclea una persona, y esta ficha se dibuja
        con plantillas de texto."""
        assert '<img src=x' not in mapa['fichaMala']
        assert '&lt;img' in mapa['fichaMala']
        assert '<b>calle</b>' not in mapa['fichaMala']


class TestPulsarUnPuntoLlevaAEsaSede:
    """Y adónde lleva lo dice quien trae los puntos, no el panel de control: un mapa de sedes
    va al inventario, y el que traiga mañana otra cosa irá a otro sitio."""

    def test_llama_a_lo_que_declaro_la_tarjeta_con_el_punto_pulsado(self, mapa):
        assert mapa['llamadoConPin'] == 'u-nave', mapa.get('errNav', '')

    def test_y_antes_abre_la_seccion(self, mapa):
        """En ese orden: lo que abre una sede es de una sección que, hasta que la pestaña se
        abre, no está dibujada."""
        assert mapa['navegadoConPin'] == 'dcim_sites'

    def test_arrastrar_desde_una_chincheta_no_es_pulsarla(self, mapa):
        """Con las dos cosas en el mismo botón, una pulsación que viajó es mover el mapa — y
        acabar en otra pantalla por haber arrastrado es perder lo que se estaba mirando."""
        assert mapa['llamadoTrasArrastrar'] == ''

    def test_y_pulsar_donde_no_hay_nada_tampoco(self, mapa):
        """Ni siquiera cambia de pestaña: el mapa entero no es un botón."""
        assert mapa['llamadoSinChincheta'] == ''
        assert mapa['navegadoSinChincheta'] == ''

    def test_y_una_tarjeta_que_no_dice_adonde_no_revienta(self, mapa):
        """Un mapa que traiga otro paquete puede no tener adónde ir."""
        assert mapa['llamadoSinNav'] == ''
        assert not mapa.get('errNav')


class TestLaTarjetaSeTiñeConLoQueSirvio:
    """El panel de control no guarda una lista de qué tarjetas pueden ponerse rojas: el estado
    viaja con los datos de cada una. Así una tarjeta que traiga otro paquete se tiñe diciendo la
    misma palabra."""

    def test_un_mapa_en_error_tiñe_la_tarjeta(self, mapa):
        assert mapa['tinte'] == 'error'

    def test_y_uno_tranquilo_no(self, mapa):
        assert mapa['sinTinte'] == ''


def _as(admin, username, perms):
    """Una sesión con EXACTAMENTE esos permisos, por un rol propio: los permisos en vigor se
    resuelven del rol, así que pegárselos a la cuenta no le da ninguno."""
    role = f'r-{username}'
    admin._custom_roles[role] = {
        'uid': role, 'name': role, 'description': '', 'permissions': list(perms),
        'enabled': True, 'created_at': '2026-09-06T00:00:00Z',
        'updated_at': '2026-09-06T00:00:00Z', 'updated_by': 'test'}
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash('pw-secret')}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': 'pw-secret'},
           follow_redirects=True)
    return c


@pytest.fixture()
def sedes(client):
    """Tres sedes: una situada, una sin coordenadas y una en el (0, 0)."""
    _login(client)
    uids = {}
    for nombre, cuerpo in (
            ('situada', {'name': 'DC Norte', 'lat': 40.4168, 'lon': -3.7038}),
            ('sin', {'name': 'DC Sin Coordenadas'}),
            ('cero', {'name': 'DC Cero', 'lat': 0, 'lon': 0})):
        uids[nombre] = client.post('/api/v1/dcim/sites', json=cuerpo).get_json()['uid']
    return uids


class TestLoQueElServidorSirve:
    """La otra mitad: el dibujo no puede enseñar lo que nunca le llegó."""

    def test_las_sedes_llegan_con_donde_estan_y_como_estan(self, client, sedes):
        c = client.get('/api/v1/overview/widget/dcim_sites').get_json()['content']
        situada = [s for s in c['sites'] if s['uid'] == sedes['situada']][0]
        assert situada['lat'] == 40.4168 and situada['lon'] == -3.7038
        assert 'state' in situada and 'ok' in situada and 'total' in situada

    def test_una_sede_sin_coordenadas_se_cuenta_y_no_se_calla(self, client, sedes):
        """Contarlas es lo que hace que alguien vaya a escribir su latitud."""
        c = client.get('/api/v1/overview/widget/dcim_sites').get_json()['content']
        assert c['placed'] == 1
        assert c['unplaced'] == 2, 'el (0, 0) no es una coordenada, es un formulario vacío'
        assert len(c['sites']) == 3, 'y siguen siendo sedes de esta casa'

    def test_y_con_que_dibujar_el_mapa_viaja_con_ellas(self, client, sedes):
        """Es configuración del panel y no del navegador: una petición más en cada apertura
        para dos cadenas es una petición más."""
        c = client.get('/api/v1/overview/widget/dcim_sites').get_json()['content']
        assert 'tiles' in c and 'attribution' in c

    def test_apagado_de_fabrica(self, client, sedes):
        """Encenderlo hace que el navegador de cada persona le cuente a un tercero dónde están
        los datacenters de esta organización. Es una decisión de quien despliega."""
        c = client.get('/api/v1/overview/widget/dcim_sites').get_json()['content']
        assert c['tiles'] == ''

    def test_esto_es_del_inventario_y_pide_su_permiso(self, admin, sedes):
        """Dónde están los datacenters de la casa no es una tarjeta pública del panel de
        control: la trae el inventario y se pide como se pide el inventario."""
        assert _as(admin, 'sin-inventario', ['overview_view']).get(
            '/api/v1/overview/widget/dcim_sites').status_code == 403
        assert _as(admin, 'con-inventario', ['overview_view', 'dcim_view']).get(
            '/api/v1/overview/widget/dcim_sites').status_code == 200

    def test_y_sin_sesion_no_se_sirve(self, client):
        r = client.get('/api/v1/overview/widget/dcim_sites')
        assert r.status_code in (401, 403), r.status_code
