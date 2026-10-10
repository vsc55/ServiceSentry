#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El mapa de sedes de la sección, **dibujado**.

Tres cosas que se veían mal a la vez en la misma pantalla, y las tres eran la misma: el encuadre
no tenía la forma del hueco donde se dibuja.

* **El mapa no llenaba su sitio.** `meet` encaja el dibujo entero dentro del elemento, así que un
  encuadre cuadrado en un hueco apaisado sale como una columna en medio con dos bandas vacías a
  los lados.
* **Las cajas de las sedes salían ilegibles.** Con el encuadre más alto que el hueco, la escala
  real la manda la ALTURA — y `_dcmScale` la calculaba del ancho, así que pedía cajas mucho más
  pequeñas que las que hacían falta. Un texto que no se lee y nada que diga por qué.
* **No se podía acercar.** El tope de fábrica del lienzo compartido es el de un plano de sala:
  ocho veces. Desde medio continente eso no llega ni a una ciudad, y lo que se busca al acercarse
  a una sede es su calle.

Se comprueban ejecutando, porque ninguna de las tres se ve leyendo: las funciones existen, no
revientan y devuelven números perfectamente creíbles.
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

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='sin node: no hay con qué ejecutar el guion')

#: Las sedes de una casa de verdad: repartidas por el norte, con dos casi juntas. La forma que
#: tiene el hueco en la pantalla desde la que se reportó esto: 1400 x 400.
_SEDES = [
    {'uid': 's1', 'name': 'Nave Norte', 'state': 'ok', 'lat': 42.81, 'lon': -1.64,
     'ok': 9, 'total': 12, 'rooms': 1, 'racks': 1},
    {'uid': 's2', 'name': 'Oficina', 'state': 'error', 'lat': 42.79, 'lon': -1.68,
     'ok': 0, 'total': 4, 'rooms': 1, 'racks': 1},
    {'uid': 's3', 'name': 'Planta Sur', 'state': 'warning', 'lat': 41.65, 'lon': -0.88,
     'ok': 2, 'total': 3, 'rooms': 2, 'racks': 3},
    {'uid': 's4', 'name': 'Nube París', 'state': '', 'lat': 48.85, 'lon': 2.35,
     'ok': 0, 'total': 0, 'rooms': 1, 'racks': 0},
]

_PRUEBA = """
const SEDES = %(sedes)s;
const ANCHO = 1400, ALTO = 400;

// El mapa encendido y con teselas, que es el caso en el que se vio.
_dcimBoard = {sites: SEDES, links: [],
              map: {tiles: 'https://tile.example.org/{z}/{x}/{y}.png',
                    attribution: '© Quien sea'}};
_dcimMap = true;

__out = {};

// ── El encuadre toma la forma del hueco ─────────────────────────────────────────
const box = _dcmExtent(SEDES, ALTO / ANCHO);
__out.box = JSON.stringify(box);
__out.fuera = JSON.stringify(SEDES.map((s, i) => {
    const p = _dcmAt(s, i);
    return (p.x >= box.x && p.x <= box.x + box.width
            && p.y >= box.y && p.y <= box.y + box.height) ? '' : s.uid;
}).filter(Boolean));
// Y sin decir la forma sigue dando un encuadre, que es como se dibuja la primera vez.
__out.boxSinForma = JSON.stringify(_dcmExtent(SEDES, 0));

// ── La escala de las cajas sale del lado que MANDA ──────────────────────────────
// Un `<svg>` de mentira donde el lienzo lo busca, con una ventana MÁS ALTA que el hueco: ahí la
// escala la pone la altura, y calcularla del ancho es lo que dejaba las cajas ilegibles.
const CID = 'dcim-sitemap';
const svgFalso = {
    // `zoomIn` lo escribe `_dcmFit` al medir; aquí se pone a mano lo que él pondría, porque
    // esta prueba llama al lienzo directamente.
    dataset: {x: box.x, y: box.y, w: box.width, h: box.height,
              zoomIn: String(ssGeoZoomIn(box.width, ANCHO)), zoomOut: '3'},
    clientWidth: ANCHO, clientHeight: ALTO, _vb: '',
    setAttribute(k, v) { if (k === 'viewBox') this._vb = v; },
    querySelector() { return {innerHTML: ''}; },
    getBoundingClientRect() { return {top: 0, left: 0, width: ANCHO, height: ALTO}; },
};
const _getOrig = document.getElementById;
document.getElementById = (id) => (id === CID ? svgFalso : _getOrig(id));
ssCanvasReset(CID);
ssCanvasFit(CID);
__out.escalaAjustada = _dcmScale();
// Y con una ventana el doble de alta de lo que le tocaría: la escala tiene que subir con ella.
ssCanvasReset(CID);
_ssVB[CID] = {x: box.x, y: box.y, w: box.width, h: box.height * 2};
__out.escalaAlta = _dcmScale();
// Lo que mide una caja con cada una de las dos.
__out.cajaAjustada = _dcmSite(SEDES[0], 0);
_ssVB[CID] = {x: box.x, y: box.y, w: box.width, h: box.height};
__out.anchoCaja = Number((_dcmSite(SEDES[0], 0).match(/<rect width="([\\d.]+)"/) || [])[1]);

// ── Y se puede acercar hasta la calle ───────────────────────────────────────────
ssCanvasReset(CID);
ssCanvasFit(CID);
__out.anchoSalida = ssCanvasWindow(CID).w;
for (let i = 0; i < 60; i++) ssCanvasZoomAt(CID, 1.18, box.x + box.width / 2,
                                            box.y + box.height / 2);
__out.anchoCerca = ssCanvasWindow(CID).w;
__out.natural = ssGeoDeepest(ANCHO);
// Y lo que mide una caja AHÍ, con el mapa a ras de calle. En pantalla tiene que verse igual que
// al abrir; en unidades del dibujo, por tanto, muchísimo más pequeña — y sobre todo tiene que
// CABER. Con el suelo que tenía la escala medía cuatro pantallas y tapaba el mapa entero.
const anchoRect = (html) => Number((html.match(/<rect width="([\\d.]+)"/) || [])[1]);
__out.cajaCerca = anchoRect(_dcmSite(SEDES[0], 0));
__out.ventanaCerca = ssCanvasWindow(CID).w;
__out.radioCerca = Number((_dcmSite(SEDES[0], 0).match(/<circle r="([\\d.]+)"/) || [])[1]);
ssCanvasReset(CID);
document.getElementById = _getOrig;

// ── El marcado dice cuánto se puede acercar ─────────────────────────────────────
__out.html = _dcimMapHtml(SEDES);

// ── Mover una sede está apagado hasta que se enciende ───────────────────────────
// Sobre un mapa, arrastrar una sede es CAMBIAR SUS COORDENADAS, y arrastrar es también lo que se
// hace para mover el mapa: con las dos cosas en el mismo gesto, un tirón para ver otro país
// acababa mudando una sede allí, sin preguntar.
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
_dcimMove = false;
__out.sinMover = _dcmSite(SEDES[0], 0);
_dcimMove = true;
__out.conMover = _dcmSite(SEDES[0], 0);
__out.htmlConMover = _dcimMapHtml(SEDES);

// Y con el interruptor apagado, bajar el puntero sobre una caja NO empieza a moverla.
// Con el `<svg>` de mentira puesto: sin él no hay dónde medir un punto y el arrastre no empieza
// nunca — la prueba pasaría por el motivo que no es.
document.getElementById = (id) => (id === CID ? svgFalso : _getOrig(id));
ssCanvasReset(CID);
ssCanvasFit(CID);
const evFalso = (uid) => ({target: {closest: () => ({dataset: {dcm: uid}})},
                           clientX: 10, clientY: 10, pointerId: 1,
                           currentTarget: {setPointerCapture() {}, style: {}}});
_dcimMove = false;
_dcmDrag = null;
_dcmDown(evFalso('s1'));
__out.arrastreApagado = _dcmDrag === null;
_dcimMove = true;
_dcmDrag = null;
_dcmDown(evFalso('s1'));
__out.arrastreEncendido = _dcmDrag !== null;
_dcmDrag = null;
document.getElementById = _getOrig;
ssCanvasReset(CID);

// ── Y señalar trae la caja al frente, y la resalta ──────────────────────────────
// En un dibujo no hay «encima»: manda el orden, y lo último escrito es lo que tapa. Y el
// resalte se DIBUJA con la escala del mapa: un filtro de CSS aquí son seis unidades del mundo,
// o sea nada.
const grupoFalso = {innerHTML: ''};
const _getOrig2 = document.getElementById;
document.getElementById = (id) => (id === 'dcim-sitemap-pins' ? grupoFalso : _getOrig2(id));
//: En qué orden salen las sedes dibujadas, leído del marcado.
const orden = (html) => (html.match(/data-dcm="([^"]+)"/g) || [])
                        .map(x => x.slice(10, -1)).join(',');

_dcmHot = '';
_dcmRedraw();
__out.ordenAntes = orden(grupoFalso.innerHTML);
_dcmRaise('s1');
__out.ordenDespues = orden(grupoFalso.innerHTML);
// El halo: una caja con un borde de más, y sólo una.
__out.halos = (grupoFalso.innerHTML.match(/stroke="var\\(--bs-body-color\\)"/g) || []).length;
_dcmRaise('s3');
__out.ordenOtra = orden(grupoFalso.innerHTML);
__out.halosOtra = (grupoFalso.innerHTML.match(/stroke="var\\(--bs-body-color\\)"/g) || []).length;
_dcmCool();
__out.halosTrasSalir = (grupoFalso.innerHTML.match(/stroke="var\\(--bs-body-color\\)"/g) || []).length;
// Y el resalte aguanta un repintado, que es lo que pasa en cada rueda y en cada arrastre.
_dcmRaise('s2');
_dcmRedraw();
__out.ordenTrasRepintar = orden(grupoFalso.innerHTML);
__out.halosTrasRepintar = (grupoFalso.innerHTML.match(/stroke="var\\(--bs-body-color\\)"/g) || []).length;
__out.apagadas = (grupoFalso.innerHTML.match(/opacity="\.35"/g) || []).length;
_dcmHot = '';
_dcmRedraw();
__out.apagadasSinSenalar = (grupoFalso.innerHTML.match(/opacity="\.35"/g) || []).length;
document.getElementById = _getOrig2;

// ── Lo peor se dibuja encima, y se pinta de su color ────────────────────────────
// Con dos sedes en la misma ciudad, la caja que dice «caído» la tapaba la de al lado, que está
// bien: se esconde justo lo que se venía a ver.
__out.ordenPrimerDibujo = orden(__out.html);
__out.cajaMala = _dcmSite(SEDES[1], 1);      // «Oficina», caída
__out.cajaBuena = _dcmSite(SEDES[0], 0);     // «Nave Norte», bien

// ── Varias sedes de la misma ciudad no son varios rótulos ───────────────────────
// Tres a un kilómetro unas de otras caen en el mismo píxel, y cada rótulo mide ciento noventa:
// no son tres rótulos, son una maraña donde no se lee ninguno —tampoco el de arriba, porque los
// de debajo asoman por los bordes—. Se vio en pantalla con cinco sedes de la misma comarca.
const PILA = [
    {uid: 'p1', name: 'Nave A', state: '', lat: 42.8169, lon: -1.6432,
     ok: 0, total: 0, rooms: 1, racks: 1},
    {uid: 'p2', name: 'Nave B', state: 'ok', lat: 42.8125, lon: -1.6458,
     ok: 3, total: 3, rooms: 1, racks: 1},
    {uid: 'p3', name: 'Nave C', state: 'error', lat: 42.8100, lon: -1.6400,
     ok: 9, total: 13, rooms: 1, racks: 1},
];
document.getElementById = (id) => (id === CID ? svgFalso : _getOrig(id));
ssCanvasReset(CID);
ssCanvasFit(CID);
_dcmHot = '';
__out.rotulosPila = Object.keys(_dcmLabels(PILA)).sort();
// Y la tapada se lee señalándola: una señalada nunca pierde el sitio.
_dcmHot = 'p1';
__out.rotulosSenalando = Object.keys(_dcmLabels(PILA)).sort();
_dcmHot = '';
// Sedes lejos unas de otras: todas llevan el suyo, que es lo que no puede romperse al arreglar
// lo anterior.
__out.rotulosSueltas = Object.keys(_dcmLabels(SEDES)).sort();
const LEJOS = [
    {uid: 'lis', name: 'Lisboa', state: '', lat: 38.72, lon: -9.14, ok: 0, total: 0,
     rooms: 1, racks: 1},
    {uid: 'ber', name: 'Berlín', state: '', lat: 52.52, lon: 13.40, ok: 0, total: 0,
     rooms: 1, racks: 1},
    {uid: 'rom', name: 'Roma', state: 'error', lat: 41.90, lon: 12.50, ok: 1, total: 2,
     rooms: 1, racks: 1},
];
__out.rotulosLejos = Object.keys(_dcmLabels(LEJOS)).sort();
// Y la que se queda sin rótulo sigue diciendo cuál es y dónde está.
__out.pinSolo = _dcmSite(PILA[0], 0, false);
// Sin mapa no se reparte nada: ahí las cajas van en rejilla y no hay chincheta que quede.
_dcimBoard = {sites: PILA, links: [], map: {tiles: '', attribution: ''}};
__out.rotulosSinMapa = Object.keys(_dcmLabels(PILA)).sort();
_dcimBoard = {sites: SEDES, links: [],
              map: {tiles: 'https://tile.example.org/{z}/{x}/{y}.png',
                    attribution: '© Quien sea'}};
document.getElementById = _getOrig;
ssCanvasReset(CID);
""" % {'sedes': json.dumps(_SEDES)}


@pytest.fixture(scope='module')
def mapa():
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


class TestElMapaLlenaSuHueco:

    def test_el_encuadre_tiene_la_forma_del_hueco(self, mapa):
        """`meet` encaja el dibujo entero dentro, así que lo que sobra se queda vacío: un
        encuadre cuadrado en un hueco apaisado sale como una columna con negro a los lados."""
        box = json.loads(mapa['box'])
        assert abs(box['height'] / box['width'] - 400 / 1400) < 0.001, box

    def test_y_ninguna_sede_se_queda_fuera(self, mapa):
        """Estirar y nunca encoger: encoger sacaría fuera lo que ya cabía, que en este dibujo
        es esconder una sede."""
        assert json.loads(mapa['fuera']) == []

    def test_sin_medir_todavia_sigue_habiendo_encuadre(self, mapa):
        """Es como se dibuja la primera vez, antes de que el hueco exista en ninguna pantalla:
        un `viewBox` de tamaño cero no dibujaría nada."""
        box = json.loads(mapa['boxSinForma'])
        assert box['width'] > 0 and box['height'] > 0


class TestLasCajasSeLeen:
    """Se dibujan en coordenadas del mundo, así que su tamaño hay que calcularlo — y se calculaba
    del ancho. Con el encuadre más alto que el hueco manda la altura, y las cajas salían mucho
    más pequeñas de lo pedido: un texto que no se lee y nada que diga por qué."""

    def test_la_escala_la_pone_el_lado_que_no_cabe(self, mapa):
        assert mapa['escalaAlta'] > mapa['escalaAjustada'] * 1.9, (
            mapa['escalaAjustada'], mapa['escalaAlta'])

    def test_y_con_el_encuadre_ajustado_la_caja_mide_lo_suyo(self, mapa):
        """Ni gigante ni ilegible: lo que mide en el dibujo por lo que hay que agrandarlo."""
        assert mapa['anchoCaja'] > 0
        assert 'Nave Norte' in mapa['cajaAjustada']

    def test_y_a_ras_de_calle_la_caja_sigue_cabiendo(self, mapa):
        """Es la mitad que se rompió al poder acercarse de verdad: la escala tenía un suelo de
        0,2 que con ocho aumentos no se alcanzaba nunca, y a ras de calle la escala real es 0,007
        — así que el suelo mandaba y una caja pasaba a medir cuatro pantallas, tapando el mapa.
        Reportado desde la pantalla, con la chincheta del tamaño de una manzana."""
        assert mapa['cajaCerca'] < mapa['ventanaCerca'], (
            mapa['cajaCerca'], mapa['ventanaCerca'])

    def test_y_lo_hace_en_la_misma_proporcion_que_al_abrir(self, mapa):
        """Que es lo que quiere decir «se ve del mismo tamaño»: la caja ocupa la misma parte de
        la pantalla de lejos que de cerca."""
        lejos = mapa['anchoCaja'] / mapa['anchoSalida']
        cerca = mapa['cajaCerca'] / mapa['ventanaCerca']
        assert abs(lejos - cerca) < 0.02, (lejos, cerca)

    def test_y_la_chincheta_tampoco_crece(self, mapa):
        """Un círculo de radio fijo en coordenadas del mundo tapa la manzana entera."""
        assert mapa['radioCerca'] < mapa['ventanaCerca'] / 10

    def test_el_fondo_de_la_caja_es_un_color_solido(self, mapa):
        """Y no un tinte, que es lo que parecía. `--bs-danger-bg-subtle` **no es un color** en
        este panel: el tema oscuro la redefine como `rgba(220,53,69,.10)`, un rojo al diez por
        ciento. En una tarjeta funciona porque debajo está el fondo opaco de la página; sobre un
        mapa el noventa por ciento restante es el satélite, y el rótulo salía con el mapa
        dentro. Se reportó tres veces desde la pantalla y las dos primeras se diagnosticó mal.

        Así que debajo va siempre `--bs-body-bg`, que sí es sólido en los dos temas, y el tinte
        encima."""
        for caja in (mapa['cajaMala'], mapa['cajaBuena']):
            suelo = caja.split('<rect width=')[1].split('>')[0]
            assert 'var(--bs-body-bg)' in suelo, suelo
            assert 'subtle' not in suelo, suelo

    def test_y_la_caja_es_opaca(self, mapa):
        """Llevaba un 95 %, y ese 5 % dejaba pasar la caja de detrás: con dos sedes de la misma
        ciudad, dos rótulos escritos uno encima del otro. Sobre un mapa claro apenas se nota;
        sobre uno oscuro se lee perfectamente, porque ahí cualquier cosa que aclare el fondo
        destaca — que es como se vio, con el rótulo del vecino dentro del de la sede caída."""
        for caja in (mapa['cajaMala'], mapa['cajaBuena']):
            rect = caja.split('<rect width=')[1].split('>')[0]
            assert 'opacity' not in rect, rect


class TestSePuedeAcercarHastaLaCalle:

    def test_hasta_donde_acaban_las_teselas(self, mapa):
        """Y no un número de veces, que es relativo a lo que se ve al abrir: el mismo número
        deja una calle o dos kilómetros según dónde estén las sedes."""
        assert abs(mapa['anchoCerca'] - mapa['natural']) < 0.01, (
            mapa['anchoSalida'], mapa['anchoCerca'], mapa['natural'])

    def test_y_eso_es_mucho_mas_que_el_tope_de_fabrica(self, mapa):
        """Ocho veces es lo que le basta a un plano de sala. Desde medio continente no llega ni
        a enseñar una ciudad."""
        assert mapa['anchoCerca'] < mapa['anchoSalida'] / 8

    def test_y_el_dibujo_lo_dice_en_su_marcado(self, mapa):
        """Lo declara quien pinta, porque el lienzo no puede saber si lo que le dan es una sala
        o el mundo."""
        assert 'data-zoom-in="' in mapa['html']
        # Y con un número que sirve: el de fábrica no llega ni a una ciudad.
        tope = float(mapa['html'].split('data-zoom-in="')[1].split('"')[0])
        assert tope > 100, tope


class TestMoverUnaSedeSeEnciende:
    """Sobre un mapa, arrastrar una sede es **cambiar sus coordenadas**: se guardan y pasan a ser
    dónde está ese edificio para todo el panel. Y arrastrar es también lo que se hace para mover
    el mapa, así que con las dos cosas en el mismo gesto un tirón para ver otro país mudaba una
    sede allí — sin preguntar, y sin que nadie se enterara hasta mucho después."""

    def test_apagado_una_pulsacion_no_empieza_a_mover(self, mapa):
        assert mapa['arrastreApagado'] is True

    def test_encendido_si(self, mapa):
        """Si no, el interruptor no encendería nada — que es la otra forma de estar roto."""
        assert mapa['arrastreEncendido'] is True

    def test_y_la_mano_abierta_solo_sale_cuando_se_puede_agarrar(self, mapa):
        """Una mano abierta sobre algo que no se mueve es una promesa que no se cumple."""
        assert 'ss-grab' not in mapa['sinMover']
        assert 'ss-grab' in mapa['conMover']


class TestSeñalarUnaSedeLaTraeAlFrente:
    """En un dibujo no hay «encima»: manda el ORDEN, y lo último que se escribe es lo que tapa.
    Con dos naves del mismo polígono, la que quedó primera se leía a medias siempre."""

    def test_la_señalada_pasa_a_ser_la_ultima(self, mapa):
        # `s1` está bien, así que sin señalar no es la última: la de arriba es la que está mal.
        assert mapa['ordenAntes'].split(',')[-1] != 's1', mapa['ordenAntes']
        assert mapa['ordenDespues'].split(',')[-1] == 's1', mapa['ordenDespues']

    def test_y_aguanta_un_repintado(self, mapa):
        """Que es lo que pasa en cada rueda y en cada arrastre. Con la marca puesta a mano en el
        nodo, el primer movimiento del mapa se llevaba por delante el orden y el resalte."""
        assert mapa['ordenTrasRepintar'].split(',')[-1] == 's2', mapa['ordenTrasRepintar']
        assert mapa['halosTrasRepintar'] == 1

    def test_y_las_tarjetas_de_abajo_la_señalan(self, mapa):
        """Que es de donde vino la petición: se pasa el ratón por la tarjeta de una sede y su
        caja del mapa tiene que subir."""
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        board = _io.open(_os.path.join(src, 'lib', 'web_admin', 'templates', 'partials',
                                       'dcim', '_board.html'), encoding='utf-8-sig').read()
        assert 'onmouseenter="_dcmRaise(' in board


class TestLoPeorSeDibujaEncima:
    """La caja que dice «caído» es la que hay que poder leer. Con sedes en la misma ciudad las
    cajas se solapan siempre, y la que quedaba tapada era la que había que mirar — por sorteo,
    según el orden en que estuvieran guardadas las sedes."""

    #: De mejor a peor: sin vigilar, bien, aviso, caído. Lo último dibujado es lo que tapa.
    _ESPERADO = 's4,s1,s3,s2'

    def test_las_cajas_salen_de_mejor_a_peor(self, mapa):
        assert mapa['ordenAntes'] == self._ESPERADO, mapa['ordenAntes']

    def test_y_tambien_en_el_primer_dibujo(self, mapa):
        """Que es el que se ve al abrir la pantalla, y el que salía sin ordenar: el orden vivía
        en el repintado, así que hasta que alguien tocaba el mapa mandaba el azar."""
        assert mapa['ordenPrimerDibujo'] == self._ESPERADO, mapa['ordenPrimerDibujo']

    def test_y_lo_que_esta_mal_se_pinta_entero_de_su_color(self, mapa):
        """A la distancia a la que se mira un cuadro de mando, un borde de un píxel no está."""
        assert 'var(--bs-danger-bg-subtle)' in mapa['cajaMala']
        assert 'bg-subtle' not in mapa['cajaBuena']
        assert 'var(--bs-body-bg)' in mapa['cajaBuena']

    def test_y_lleva_un_simbolo_ademas_del_color(self, mapa):
        """Quien no separa el rojo del verde tiene que saber igual qué caja hay que mirar."""
        assert '>!</text>' in mapa['cajaMala']
        assert '>!</text>' not in mapa['cajaBuena']


class TestVariasSedesDeLaMismaCiudadNoSonVariosRotulos:
    """Un rótulo mide ciento noventa píxeles y una comarca entera cabe en uno. Cinco sedes de la
    misma ciudad pintaban cinco rótulos en el mismo sitio: no se leía ninguno —tampoco el de
    arriba, porque los de debajo asoman por los bordes— y el de la sede caída era uno más de la
    maraña. Reportado desde la pantalla dos veces, la segunda con las cajas ya opacas: el
    problema nunca fue la transparencia.

    Se reparte el sitio por importancia y el que choca se queda en chincheta. Que es lo que hace
    cualquier mapa, y lo único que no miente: dibujar los cinco no enseña más, enseña menos."""

    def test_solo_una_de_la_pila_lleva_rotulo(self, mapa):
        assert mapa['rotulosPila'] == ['p3'], mapa['rotulosPila']

    def test_y_es_la_que_esta_caida(self, mapa):
        """El sitio se reparte de peor a mejor: la que hay que leer es la que se queda con él."""
        assert 'p3' in mapa['rotulosPila']

    def test_y_señalar_una_tapada_le_da_el_sitio(self, mapa):
        """Porque señalarla es preguntar explícitamente por ella. Sin esto, una sede de una
        ciudad con vecinas no se podría leer nunca."""
        assert mapa['rotulosSenalando'] == ['p1'], mapa['rotulosSenalando']

    def test_pero_las_que_no_se_pisan_lo_conservan(self, mapa):
        """Lo que no puede romperse al arreglar lo otro: tres capitales europeas son tres
        rótulos, y ahí no sobra ninguno."""
        assert mapa['rotulosLejos'] == ['ber', 'lis', 'rom'], mapa['rotulosLejos']

    def test_y_de_dos_vecinas_se_queda_la_que_esta_peor(self, mapa):
        """Las dos primeras del juego están a cuatro kilómetros, que a la escala de un mapa de
        Europa es el mismo punto: `s2` está caída y `s1` bien, así que el sitio es de `s2`."""
        assert 's2' in mapa['rotulosSueltas'] and 's1' not in mapa['rotulosSueltas'], (
            mapa['rotulosSueltas'])
        # …y la de París, que no se pisa con nadie, conserva el suyo.
        assert 's4' in mapa['rotulosSueltas']

    def test_y_la_que_se_queda_sin_el_sigue_diciendo_cual_es(self, mapa):
        """Una chincheta muda es un punto de color en un mapa: dice que ahí hay algo y no dice
        qué. Lleva su nombre, y sigue teniendo su color y su clic."""
        assert '<title>Nave A</title>' in mapa['pinSolo']
        assert 'data-dcm="p1"' in mapa['pinSolo']
        assert '<rect width=' not in mapa['pinSolo']

    def test_y_sin_mapa_no_se_reparte_nada(self, mapa):
        """Ahí las cajas van en rejilla, no se pisan, y no hay chincheta que quede en su sitio:
        quitar un rótulo sería quitar la sede."""
        assert mapa['rotulosSinMapa'] == ['p1', 'p2', 'p3'], mapa['rotulosSinMapa']


class TestLaSedeSeñaladaSeResalta:
    """Subirla no basta: con siete cajas parecidas, saber CUÁL ha subido cuesta más que leerlas
    todas."""

    def test_la_señalada_lleva_su_halo(self, mapa):
        assert mapa['halos'] == 1, mapa['halos']

    def test_y_solo_una(self, mapa):
        """Dos resaltes a la vez no señalan ninguno."""
        assert mapa['halosOtra'] == 1
        assert mapa['ordenOtra'].split(',')[-1] == 's3'

    def test_y_las_demas_se_atenuan(self, mapa):
        """Lo que de verdad hace destacar a una entre siete: resaltar sube una; apagar las
        otras seis deja una sola encendida."""
        assert mapa['apagadas'] == len(_SEDES) - 1, mapa['apagadas']

    def test_pero_no_cuando_no_se_señala_ninguna(self, mapa):
        """Un mapa permanentemente a media luz no destaca nada."""
        assert mapa['apagadasSinSenalar'] == 0

    def test_y_al_salir_de_la_lista_se_apaga(self, mapa):
        """Un resalte que se queda puesto deja de querer decir «esta»."""
        assert mapa['halosTrasSalir'] == 0

    def test_el_resalte_se_dibuja_con_la_escala_del_mapa(self, mapa):
        """Y no con un filtro de CSS: dentro de este dibujo las unidades son píxeles del mundo,
        así que una sombra de seis se queda en seis millonésimas de la pantalla. Se probó así y
        no se veía nada."""
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        js = _io.open(_os.path.join(src, 'lib', 'web_admin', 'templates', 'partials',
                                    'dcim', '_sitemap.html'), encoding='utf-8-sig').read()
        trozo = js.split('const hot =')[1].split('</g>')[0]
        assert '* k' in trozo, 'el halo no sigue la escala del mapa'
        css = _io.open(_os.path.join(src, 'lib', 'web_admin', 'static', 'css',
                                     'web_admin.css'), encoding='utf-8-sig').read()
        assert '.dcm-hot' not in css, 'quedó la regla que no se veía'

    def test_y_no_pisa_el_color_del_estado(self, mapa):
        """El borde de una caja ya dice CÓMO ESTÁ la sede: pisarlo para decir «es esta» le
        quitaría lo único que dice de un vistazo. Por eso el halo va por fuera."""
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        js = _io.open(_os.path.join(src, 'lib', 'web_admin', 'templates', 'partials',
                                    'dcim', '_sitemap.html'), encoding='utf-8-sig').read()
        trozo = js.split('${hot ?')[1].split(': \'\'}')[0]
        assert 'fill="none"' in trozo, 'el halo tapa la caja en vez de rodearla'


class TestElMapaSeVeDeSalida:
    """La pregunta que trae a alguien a este cuadro es dónde está lo que va mal; esconder el mapa
    hasta que se pide es guardar la respuesta en un cajón."""

    def test_esta_encendido_sin_tocar_nada(self, mapa):
        import io as _io                                            # noqa: PLC0415
        import os as _os                                            # noqa: PLC0415
        src = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        js = _io.open(_os.path.join(src, 'lib', 'web_admin', 'templates', 'partials',
                                    'dcim', '_sitemap.html'), encoding='utf-8-sig').read()
        assert 'let _dcimMap = true;' in js
