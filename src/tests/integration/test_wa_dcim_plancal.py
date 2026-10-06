#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El plano de fondo: dónde cae, a qué escala, y poder quitarlo de la vista. En `node`, sobre
el guion de verdad del panel.

Reportado desde la pantalla: el plano no cuadraba con las medidas reales. Sin «Ancho del plano»,
la imagen de una sala tomaba el ancho del MARCO del dibujo —márgenes incluidos, y cambiaba al
mover un rack—; con él, había que saber el ancho de la imagen entera, márgenes y cajetín
incluidos; y su esquina iba pegada al (0, 0), así que un plano con margen quedaba desplazado.
Lo que fijan estas pruebas:

- sin ancho dicho, una sala usa SU ancho y una planta un tamaño fijo; nunca el marco;
- la imagen se dibuja donde dice `plan_x`/`plan_y`, y el marco del dibujo la abarca entera;
- calibrar: dos puntos y su distancia dan la escala, un punto y su sitio dan dónde cae, y se
  guarda lo uno y lo otro —o solo la escala—, en la sala o en la planta;
- el plano se oculta y se muestra, en 2D y en 3D, y la elección se recuerda.
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
showToast = () => {};
const enviados = [];
_dcimSend = (metodo, url, cuerpo) => { enviados.push({url, cuerpo}); return Promise.resolve({ok: true}); };
const S = _DCP_SCALE;
__out = {};
// ── El lienzo con bandas: la caja más ancha que el dibujo ───────────────────────
// 1000×500 px para una ventana de 100×100: el dibujo, centrado, a 5 px por unidad y con 250 px
// vacíos a cada lado. Antes se estiraba la ventana sobre la caja entera.
const svgFalso = {getBoundingClientRect: () => ({left: 0, top: 0, width: 1000, height: 500}),
                  style: {}};
const svgOrig = ssCanvasSvg, ventanaOrig = ssCanvasWindow, aplicaOrig = ssCanvasApply;
ssCanvasSvg = () => svgFalso;
ssCanvasWindow = () => ({x: 0, y: 0, w: 100, h: 100});
ssCanvasApply = () => {};
const p0 = ssCanvasPoint('x', {clientX: 250, clientY: 0});
const p1 = ssCanvasPoint('x', {clientX: 750, clientY: 500});
__out.bandas = [p0.x, p0.y, p1.x, p1.y];
// Desplazar: 50 px de ratón son 10 unidades en los dos ejes, no 5 en uno y 10 en el otro.
ssCanvasPanStart('x', {clientX: 500, clientY: 250, currentTarget: {style: {}, setPointerCapture() {}}});
ssCanvasPanMove('x', {clientX: 550, clientY: 300});
__out.desplaza = [_ssVB['x'].x, _ssVB['x'].y];
ssCanvasPanEnd(null);
ssCanvasSvg = svgOrig; ssCanvasWindow = ventanaOrig; ssCanvasApply = aplicaOrig;

// Un clic en el lienzo en (x, y) milímetros: `ssCanvasPoint` devuelve unidades del dibujo.
ssCanvasPoint = (svg, ev) => ev.p;
const clic = (x, y) => ({p: {x: x * S, y: y * S}, clientX: 0, clientY: 0, type: 'pointerup'});

// ── Sin ancho dicho ─────────────────────────────────────────────────────────────
_dcimPlan = {room: {uid: 'r1', width_mm: 7000, depth_mm: 5000}, racks: [],
             image: {data: 'data:image/png;base64,AAAA', ratio: 0.5}};
_dcpFeat = {features: [], kinds: {}};
__out.salaSinAncho = _dcpPlanBox().w;
_dcimPlan.room.width_mm = 0;
__out.salaSinNada = _dcpPlanBox().w;
_dcimPlan.room.width_mm = 7000;
_dcsPlan = {site: {uid: 's', rooms: []}, floors: [{uid: 'p', plan: 'x.png'}], floor: 'p',
            image: {data: 'data:image/png;base64,AAAA', ratio: 0.5}, content: {}, kinds: {}};
__out.plantaSinAncho = _dcsPlanBox().w;
// El marco no cambia el plano: un rack lejos no lo estira.
const antes = _dcpPlanImage([]);
_dcimPlan.racks = [{uid: 'k', pos_x: 40000, pos_y: 30000}];
__out.noLoEstiraUnRack = _dcpPlanImage(_dcimPlan.racks) === antes;
_dcimPlan.racks = [];

// ── Donde dice su sitio ─────────────────────────────────────────────────────────
Object.assign(_dcimPlan.room, {plan_mm: 20000, plan_x: -1500, plan_y: -2000});
const img = _dcpPlanImage([]);
__out.imagenEnSuSitio = img.includes(`x="${-1500 * S}"`) && img.includes(`y="${-2000 * S}"`)
    && img.includes(`width="${20000 * S}"`) && img.includes(`height="${10000 * S}"`);
const marco = _dcpExtent([]);
__out.marcoLaAbarca = marco.x <= -1500 * S && marco.y <= -2000 * S
    && marco.x + marco.width >= 18500 * S && marco.y + marco.height >= 8000 * S;
Object.assign(_dcimPlan.room, {plan_mm: 10000, plan_x: 0, plan_y: 0});

// ── Calibrar una sala ───────────────────────────────────────────────────────────
// La imagen mide ahora 10 × 5 m. Dos puntos a 2 m en la imagen que de verdad están a 4 m: la
// imagen entera mide 20 m. El primero, (1, 1) m de la imagen, es la esquina (500, 0) de la sala.
_dcCalStart('room');
_dcCalClick(clic(1000, 1000));
_dcCalClick(clic(3000, 1000));
__out.pasoDistancia = _dcCal.step;
_dcCal.dist = '4';
_dcCalApply();
__out.escala = _dcimPlan.room.plan_mm;
__out.pasoSitio = _dcCal.step;
// Paso 3, punto a punto: un punto del plano —(2, 2) m de la imagen a la escala nueva— y
// después dónde cae: cerca de la esquina (0, 0) de la sala, a la que se pega.
_dcCalClick(clic(2000, 2000));
__out.desdeElegido = !!_dcCal.from;
__out.esquinasVisibles = (_dcCalMarks('room').match(/var\(--bs-warning\)/g) || []).length;
_dcCalClick(clic(30, -20));
__out.encajado = [_dcimPlan.room.plan_x, _dcimPlan.room.plan_y];
__out.sinGuardarAun = enviados.length === 0 && _dcCal !== null;
// El paso 3 se encuadra sobre el plano y lo dibujado.
const ventana = _ssVB[_DCP_SVG];
__out.encuadre = !!ventana && ventana.x <= 0 && ventana.y <= 0
    && ventana.x + ventana.w >= 20000 * S && ventana.y + ventana.h >= 10000 * S;
// Arrastrar, sin «Mover el plano», desplaza la vista y deja el plano donde está.
const raton = (x, y, mmx, mmy) => ({clientX: x, clientY: y, p: {x: mmx * S, y: mmy * S},
                                    type: 'pointerup', currentTarget: {style: {}, setPointerCapture() {}}});
_dcCalDown(raton(100, 100, 3000, 3000));
_dcCalMove(raton(150, 130, 4000, 3500));
_dcCalUp(raton(150, 130, 4000, 3500));
__out.arrastrarNoMueve = [_dcimPlan.room.plan_x, _dcimPlan.room.plan_y];
// Teclear «-» no hace saltar el plano a 0.
_dcCalSetXY('x', '-');
__out.menosNoSalta = _dcimPlan.room.plan_x;
// Con «Mover el plano»: 1 m a la derecha y 0,5 m abajo.
_dcCalToggleMove();
_dcCalDown(raton(100, 100, 3000, 3000));
_dcCalMove(raton(150, 130, 4000, 3500));
_dcCalUp(raton(150, 130, 4000, 3500));
__out.arrastrado = [_dcimPlan.room.plan_x, _dcimPlan.room.plan_y];
_dcCalSave(true);
__out.guardado = enviados.slice(-1)[0];
__out.terminada = _dcCal === null;

// Solo la escala.
enviados.length = 0;
Object.assign(_dcimPlan.room, {plan_mm: 10000, plan_x: 0, plan_y: 0});
_dcCalStart('room');
_dcCalClick(clic(0, 0));
_dcCalClick(clic(0, 2500));        // en vertical: medio alto, 2,5 m de 5
_dcCal.dist = '5';
_dcCalApply();
_dcCalSave(false);
__out.soloEscala = enviados[0];

// En metros, una fachada de 42 m da un plano de edificio; y una unidad equivocada se rechaza.
_dcCalStart('room');
_dcCalClick(clic(0, 0));
_dcCalClick(clic(5000, 0));          // un cuarto de la imagen, que mide 20 m
_dcCal.dist = '42';
_dcCalApply();
__out.metros = _dcimPlan.room.plan_mm;
_dcCalCancel();
_dcCalStart('room');
_dcCalClick(clic(0, 0));
_dcCalClick(clic(5000, 0));
_dcCal.dist = '0.042';               // 42 «mm» escritos donde se piden metros
_dcCalApply();
__out.absurdo = [_dcimPlan.room.plan_mm, _dcCal.step];
_dcCalCancel();
// Calibrar cierra el 3D, que empujaba el lienzo fuera de la pantalla.
_dc3d = {on: true};
_dcCalStart('room');
__out.sin3d = _dc3d === null;
_dcCalCancel();

// Una distancia imposible no cambia nada.
_dcCalStart('room');
_dcCalClick(clic(1000, 1000));
_dcCalClick(clic(1000, 1000));
_dcCal.dist = '3';
const escalaAntes = _dcimPlan.room.plan_mm;
_dcCalApply();
__out.imposible = _dcimPlan.room.plan_mm === escalaAntes && _dcCal.step === 'dist';
_dcCalCancel();

// ── Calibrar una planta ─────────────────────────────────────────────────────────
enviados.length = 0;
_dcsPlan.floors[0].plan_mm = 0;
_dcCalStart('floor');
_dcCalClick(clic(0, 0));
_dcCalClick(clic(10000, 0));       // 10 m de los 50 supuestos
_dcCal.dist = '6';
_dcCalApply();
__out.plantaEscala = _dcsPlan.floors[0].plan_mm;
// Una planta sin salas no tiene con qué encajarlo: lo dice, y se guarda donde está.
__out.plantaVacia = _dcCalBar('floor').includes(t('dcim_cal_fit_empty'));
_dcCalSave(true);
__out.plantaGuardada = enviados[0];

// ── Cancelar deshace lo aplicado; la paleta no está mientras se calibra ─────────
Object.assign(_dcimPlan.room, {plan_mm: 10000, plan_x: 0, plan_y: 0});
_dcCalStart('room');
__out.sinPaleta = _dcpPaletteHtml() === '';
_dcCalClick(clic(0, 0));
_dcCalClick(clic(2000, 0));
_dcCal.dist = '8';
_dcCalApply();
const aplicada = _dcimPlan.room.plan_mm;
_dcCalCancel();
__out.cancelarDeshace = [aplicada, _dcimPlan.room.plan_mm];
__out.conPaleta = _dcpPaletteHtml() !== '';
// «Volver a marcar» parte de lo de antes, no de lo ya aplicado.
_dcCalStart('room');
_dcCalClick(clic(0, 0));
_dcCalClick(clic(2000, 0));
_dcCal.dist = '8';
_dcCalApply();
_dcCalStart('room');
__out.otraVez = _dcimPlan.room.plan_mm;
_dcCalCancel();

// ── La franja dice en qué paso se está ──────────────────────────────────────────
_dcCalStart('room');
__out.franjaSala = _dcCalBar('room').includes(tf('dcim_cal_step', 1)) && _dcCalBar('floor') === '';
_dcCalCancel();

// ── Encajar una planta contra otra ──────────────────────────────────────────────
// La baja ya está colocada con su plano en (-2000, -1000); la primera se encaja contra ella
// por la escalera, que en el plano de la primera está en (3000, 2000) y en el de la baja en
// (1000, 1000).
enviados.length = 0;
_dcsPlan = {site: {uid: 's', rooms: []}, floor: 'p1', content: {}, kinds: {},
            image: {data: 'data:image/png;base64,BBBB', ratio: 0.5},
            floors: [{uid: 'p0', name: 'Baja', plan: 'b.png', plan_mm: 20000, plan_x: -2000, plan_y: -1000},
                     {uid: 'p1', name: 'Primera', plan: 'p.png', plan_mm: 20000, plan_x: 0, plan_y: 0}]};
// Las dos ya tienen escala: se salta directo a encajar, sin volver a medir.
_dcCalStart('floor');
__out.botonSaltar = _dcCalBar('floor').includes('_dcCalSkipScale()');
_dcCalSkipScale();
__out.saltado = [_dcCal.step, _dcsPlan.floors[1].plan_mm];
__out.selectorRef = _dcCalBar('floor').includes('_dcCalSetRef(this.value)')
    && _dcCalBar('floor').includes('value="p0"') && !_dcCalBar('floor').includes('value="p1"');
// Las asas del plano: tirar de la de abajo a la derecha hasta el doble lo duplica, con la
// esquina de arriba a la izquierda quieta; tirar de la de arriba a la izquierda deja quieta la
// de abajo a la derecha.
__out.asasPlano = (_dcCalMarks('floor').match(/data-dccalh=/g) || []).length;
const planta1 = _dcsPlan.floors[1];
const asaPlano = (lado) => ({closest: (sel) => (sel === '[data-dccalh]' ? {dataset: {dccalh: lado}} : null)});
const tirar = (lado, desde, hasta) => {
    _dcCalDown({target: asaPlano(lado), p: {x: desde[0] * S, y: desde[1] * S}, clientX: 0, clientY: 0,
                currentTarget: {setPointerCapture() {}, style: {}}});
    _dcCalMove({p: {x: hasta[0] * S, y: hasta[1] * S}, clientX: 50, clientY: 50});
    _dcCalUp({type: 'pointerup', clientX: 50, clientY: 50, currentTarget: {style: {}}});
};
Object.assign(planta1, {plan_mm: 20000, plan_x: 0, plan_y: 0});
tirar('se', [20000, 10000], [40000, 20000]);
__out.estiradoSE = [planta1.plan_mm, planta1.plan_x, planta1.plan_y];
tirar('nw', [0, 0], [20000, 10000]);
__out.encogidoNW = [planta1.plan_mm, planta1.plan_x, planta1.plan_y];
_dcCalSetWidth('30');
__out.anchoEscrito = planta1.plan_mm;
_dcCalSetWidth('-');
__out.anchoMedio = planta1.plan_mm;
Object.assign(planta1, {plan_mm: 20000, plan_x: 0, plan_y: 0});
_dcCal.ref = 'p0';
_dcCal.refImg = {data: 'data:image/png;base64,AAAA', ratio: 0.5};
const refSvg = _dcCalRefSvg();
__out.refDibujada = refSvg.includes(`x="${-2000 * S}"`) && refSvg.includes('dcCalRefTint');
__out.refEnElDibujo = _dcsContent().includes('dcCalRefTint');
__out.textoRef = _dcCalBar('floor').includes(tf('dcim_cal_fit_ref', 'Baja'));
_dcCalClick(clic(3000, 2000));          // la escalera, en este plano
_dcCalClick(clic(1000, 1000));          // la misma, en el de la baja
__out.encajadaConLaBaja = [_dcsPlan.floors[1].plan_x, _dcsPlan.floors[1].plan_y];
_dcCalCancel();

// ── El norte ────────────────────────────────────────────────────────────────────
enviados.length = 0;
Object.assign(_dcimPlan.room, {plan_mm: 10000, plan_x: 0, plan_y: 0, north_deg: null});
_dcCalStart('room');
_dcCalClick(clic(0, 0));
_dcCalClick(clic(2000, 0));
_dcCal.dist = '2';
_dcCalApply();
_dcCalNorth(true);
__out.pasoNorte = _dcCal.step;
// La flecha del norte del plano apunta a la derecha: el norte está al este del dibujo, 90°.
_dcCalClick(clic(1000, 1000));
_dcCalClick(clic(3000, 1000));
__out.norte = [_dcimPlan.room.north_deg, _dcCal.step];
_dcCalSave(true);
__out.norteGuardado = enviados[0].cuerpo.north_deg;
// Cancelar devuelve el norte de antes.
_dcimPlan.room.north_deg = null;
_dcCalStart('room');
_dcCalClick(clic(0, 0));
_dcCalClick(clic(2000, 0));
_dcCal.dist = '2';
_dcCalApply();
_dcCalNorth(true);
_dcCalClick(clic(0, 1000));
_dcCalClick(clic(0, 0));
const norteArriba = _dcimPlan.room.north_deg;
_dcCalCancel();
__out.norteCancelado = [norteArriba, _dcimPlan.room.north_deg];
// La rosa: nada sin norte dicho; girada con él.
__out.rosaSin = _dcCompass(null) === '' && _dcCompass(undefined) === '';
__out.rosaCon = _dcCompass(90).includes('rotate(90)');
// En el 3D gira con la cámara: mirando hacia arriba del plano, el norte (0°) arriba; mirando
// al este, a la izquierda.
__out.rosa3d = [Math.round(ss3dCompassAngle({theta: Math.PI / 2}, 0)),
                Math.round(ss3dCompassAngle({theta: Math.PI}, 0))];

// ── Ocultar el plano ────────────────────────────────────────────────────────────
_dcPlanBg = true;
_dcPlanBgToggle();
__out.oculto = _dcPlanBg === false && _dcpPlanImage([]) === ''
    && !_dcsContent().includes('<image');
__out.recordado = localStorage.getItem('ss.dcim.planbg');
__out.sin3d = _ds3FloorScene(_dcsPlan.floors[0], _dcsPlan.image).planos.length === 0;
__out.botonOculto = _dcPlanBgButton().includes('bi-eye-slash');
_dcPlanBgToggle();
__out.visible = _dcPlanBg && _dcpPlanImage([]).includes('<image')
    && _ds3FloorScene(_dcsPlan.floors[0], _dcsPlan.image).planos.length === 1;
// Calibrar con el plano oculto lo enseña: no se calibra a ciegas.
_dcPlanBg = false;
_dcCalStart('room');
__out.calibrarLoEnsena = _dcPlanBg === true;
_dcCalCancel();
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


class TestSinAnchoDicho:
    def test_una_sala_usa_su_ancho(self, out):
        assert out['salaSinAncho'] == 7000
        assert out['salaSinNada'] == 10000

    def test_una_planta_un_tamano_fijo(self, out):
        assert out['plantaSinAncho'] == 50000

    def test_mover_un_rack_no_estira_el_plano(self, out):
        assert out['noLoEstiraUnRack'], 'el plano sigue estirándose con el marco del dibujo'


class TestDondeCaeElPlano:
    def test_se_dibuja_donde_dice_su_sitio(self, out):
        assert out['imagenEnSuSitio']

    def test_el_marco_lo_abarca_entero(self, out):
        assert out['marcoLaAbarca'], 'un plano con margen negativo queda fuera del marco'


class TestCalibrar:
    def test_dos_puntos_y_su_distancia_dan_la_escala(self, out):
        assert out['pasoDistancia'] == 'dist'
        assert out['escala'] == 20000
        assert out['pasoSitio'] == 'origin'

    def test_un_punto_del_plano_se_lleva_a_una_esquina_de_lo_dibujado(self, out):
        """Reportado: pedir el punto en (0, 0) obligaba a que el plano tuviera una esquina ahí,
        y un edificio en L no la tiene. Ahora se elige cualquier punto reconocible."""
        assert out['desdeElegido']
        assert out['esquinasVisibles'] >= 4, 'no se ven las esquinas a las que se pega'
        assert out['encajado'] == [-2000, -2000]
        assert out['sinGuardarAun']

    def test_arrastrar_mueve_el_plano_solo_con_su_boton(self, out):
        """Arrastrar para mirar se llevaba el plano consigo."""
        assert out['arrastrarNoMueve'] == [-2000, -2000]
        assert out['arrastrado'] == [-1000, -1500]

    def test_teclear_un_menos_no_lo_hace_saltar(self, out):
        assert out['menosNoSalta'] == -2000

    def test_el_paso_3_se_encuadra_sobre_el_plano(self, out):
        assert out['encuadre']

    def test_la_distancia_va_en_metros(self, out):
        """Reportado: «el plano desaparece en el paso 3». Era 42 escrito en metros donde se
        pedían milímetros: un plano de 52 mm, un píxel."""
        assert out['metros'] == 168000

    def test_una_unidad_equivocada_se_rechaza(self, out):
        assert out['absurdo'] == [20000, 'dist']

    def test_calibrar_cierra_el_3d(self, out):
        assert out['sin3d']

    def test_guardar_guarda_escala_y_sitio(self, out):
        g = out['guardado']
        assert g['url'] == '/api/v1/dcim/rooms/r1'
        assert g['cuerpo'] == {'plan_mm': 20000, 'plan_x': -1000, 'plan_y': -1500}
        assert out['terminada']

    def test_se_puede_guardar_solo_la_escala(self, out):
        """En vertical también: la distancia cuenta la proporción de la imagen."""
        assert out['soloEscala']['cuerpo'] == {'plan_mm': 20000}

    def test_dos_veces_el_mismo_punto_no_cambia_nada(self, out):
        assert out['imposible']

    def test_en_una_planta_igual(self, out):
        assert out['plantaEscala'] == 30000
        assert out['plantaGuardada']['url'] == '/api/v1/dcim/floors/p'
        assert out['plantaGuardada']['cuerpo'] == {'plan_mm': 30000, 'plan_x': 0, 'plan_y': 0}
        assert out['plantaVacia'], 'una planta sin salas no dice que no hay con qué encajar'

    def test_la_franja_es_de_su_pantalla(self, out):
        assert out['franjaSala']


class TestOcultarElPlano:
    def test_se_oculta_en_2d_y_en_3d(self, out):
        assert out['oculto']
        assert out['sin3d']
        assert out['botonOculto']

    def test_y_se_recuerda(self, out):
        assert out['recordado'] == '0'

    def test_y_vuelve(self, out):
        assert out['visible']

    def test_calibrar_lo_ensena(self, out):
        assert out['calibrarLoEnsena']


class TestElLienzoConBandas:
    """Reportado al probar la calibración en el navegador: el plano calibrado quedaba 1,7 m
    desplazado en un eje. El `<svg>` guarda la proporción del dibujo y lo centra con bandas
    vacías; la conversión de clic a dibujo estiraba la ventana sobre la caja entera."""

    def test_un_clic_cae_donde_esta_el_dibujo(self, out):
        assert out['bandas'] == [0, 0, 100, 100]

    def test_desplazar_va_con_el_raton_en_los_dos_ejes(self, out):
        assert out['desplaza'] == [-10, -10]


class TestCancelarYLaPaleta:
    def test_cancelar_deshace_la_escala_aplicada(self, out):
        assert out['cancelarDeshace'] == [40000, 10000]

    def test_volver_a_marcar_parte_de_lo_de_antes(self, out):
        assert out['otraVez'] == 10000

    def test_sin_paleta_mientras_se_calibra(self, out):
        """Un clic que caía en un botón de la paleta creaba una pieza a mitad de calibrar."""
        assert out['sinPaleta'] and out['conPaleta']


class TestElNorte:
    """Se pidió marcar el norte al calibrar el plano."""

    def test_se_marca_con_la_flecha_del_plano(self, out):
        assert out['pasoNorte'] == 'north'
        assert out['norte'] == [90, 'origin']

    def test_se_guarda_con_lo_demas(self, out):
        assert out['norteGuardado'] == 90

    def test_cancelar_devuelve_el_de_antes(self, out):
        assert out['norteCancelado'] == [0, None]

    def test_la_rosa_solo_si_se_sabe_y_girada(self, out):
        assert out['rosaSin'] and out['rosaCon']

    def test_en_el_3d_gira_con_la_camara(self, out):
        assert out['rosa3d'] == [0, -90]


class TestEncajarConOtraPlanta:
    """Reportado: en el edificio las plantas no coincidían. Cada una se colocaba por su esquina
    de arriba a la izquierda; se encaja contra otra planta por algo común, como la escalera."""

    def test_se_elige_entre_las_otras_plantas_con_plano(self, out):
        assert out['selectorRef']

    def test_su_plano_se_ve_en_su_sitio_tenido(self, out):
        assert out['refDibujada'] and out['refEnElDibujo']
        assert out['textoRef']

    def test_con_la_escala_hecha_se_salta_directo_a_encajar(self, out):
        """Reportado: dos plantas ya calibradas que no coinciden obligaban a volver a medir."""
        assert out['botonSaltar']
        assert out['saltado'] == ['origin', 20000]

    def test_el_plano_se_estira_por_sus_esquinas(self, out):
        """Se pidió: con una planta ya colocada, ajustar las otras estirando su plano."""
        assert out['asasPlano'] == 4
        assert out['estiradoSE'] == [40000, 0, 0]
        assert out['encogidoNW'] == [20000, 20000, 10000]

    def test_y_su_ancho_se_escribe(self, out):
        assert out['anchoEscrito'] == 30000
        assert out['anchoMedio'] == 30000, 'a medio escribir no cambia'

    def test_un_punto_comun_lleva_un_plano_sobre_el_otro(self, out):
        assert out['encajadaConLaBaja'] == [-2000, -1000]
