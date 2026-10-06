#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Una planta, o el edificio entero, en 3D: ejecutado en `node` sobre el guion del panel.

El visor de la sala levanta ahora cualquier escena, y el plano de la sede le da la suya. Lo
que fijan estas pruebas:

- una sala de la planta sale en el MISMO sitio que en el plano de la planta, girada incluida;
- sus muros se vuelven cristal según la cámara esté dentro o fuera de ESA sala, girada;
- la zona general no lleva ni muros ni suelo, y la sala sin medidas sale tenue en lo que la
  delimita, no en lo que tiene dentro;
- el plano del arquitecto va al suelo, con su tamaño;
- el edificio apila las plantas por su nivel —el sótano debajo—, las de encima de la que se
  mira tenues, y separarlas las aleja;
- un clic sobre una sala dice su nombre, y otro la abre;
- el contenido de la sede se pide de una vez.
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
const sala = {uid: 's1', name: 'CPD', floor_uid: 'p0', pos_x: 5000, pos_y: 2000, rotation: 90,
              width_mm: 4000, depth_mm: 3000};
const sinMedidas = {uid: 's2', name: 'Almacén', floor_uid: 'p0', pos_x: 12000, pos_y: 0};
const zona = {uid: 'z0', name: 'Baja · zona general', floor_uid: 'p0', pos_x: 0, pos_y: 0};
const arriba = {uid: 's3', name: 'Despachos', floor_uid: 'p1', pos_x: 0, pos_y: 0,
                width_mm: 6000, depth_mm: 4000};
const sotano = {uid: 's4', name: 'Archivo', floor_uid: 'pm1', pos_x: 0, pos_y: 0,
                width_mm: 6000, depth_mm: 4000};
_dcsPlan = {
    site: {uid: 'sede', name: 'Sede', rooms: [sala, sinMedidas, zona, arriba, sotano]},
    floors: [{uid: 'pm1', name: 'Sótano', level: -1},
             {uid: 'p0', name: 'Baja', level: 0, area_uid: 'z0', plan: 'x.png', plan_mm: 30000},
             {uid: 'p1', name: 'Primera', level: 1}],
    floor: 'p0', image: {data: 'data:image/png;base64,AAAA', ratio: 0.5},
    kinds: {column: {layer: 'room', h: 3000}},
    content: {
        s1: {racks: [{uid: 'k1', name: 'R1', pos_x: 1000, pos_y: 1000, width_mm: 600,
                      depth_mm: 1000, u_height: 42, rotation: 0, roll: {state: 'ok'}}],
             features: []},
        s2: {racks: [{uid: 'k2', name: 'R2', pos_x: 0, pos_y: 0, u_height: 42, roll: {}}],
             features: []},
        z0: {racks: [{uid: 'k0', name: 'PASILLO', pos_x: 9000, pos_y: 4000, u_height: 12,
                      roll: {}}],
             features: [{uid: 'f0', kind: 'column', pos_x: 100, pos_y: 100}]},
        s3: {racks: [], features: []}, s4: {racks: [], features: []},
    },
};
__out = {};
const M = 0.001;
// Una esquina de una caja en el suelo (x, z) en metros, a partir de su matriz.
const esquina = (m, u, w) => [m[0] * u + m[8] * w + m[12], m[2] * u + m[10] * w + m[14]];
const cerca = (a, b) => Math.abs(a - b) < 1e-6;

// ── La planta ───────────────────────────────────────────────────────────────────
_ds3Mode = 'floor';
const planta = _ds3FloorScene(_dcsPlan.floors[1], _dcsPlan.image);
// El rack R1, colocado como lo coloca el plano de la planta: su esquina en la sala, la sala
// girada 90° sobre su centro y puesta en su sitio.
const r1 = planta.cajas.find(k => k.lee && k.lee.name === 'R1');
const c = esquina(r1.m, 0, 0);
const ang = 90 * Math.PI / 180;
const lx = 1000 - 2000, ly = 1000 - 1500;                // la esquina, desde el centro de la sala
const esperado = [(5000 + 2000 + lx * Math.cos(ang) - ly * Math.sin(ang)) * M,
                  (2000 + 1500 + lx * Math.sin(ang) + ly * Math.cos(ang)) * M];
__out.rackEnSuSitio = cerca(c[0], esperado[0]) && cerca(c[1], esperado[1]);
__out.salas = planta.salas.map(s => s.uid).sort().join(',');
__out.murosConMarco = planta.cajas.filter(k => k.muro).every(k => k.frame);
// La zona general: lo de dentro sí, muros no. Tres salas con muros = s1 y s2, ocho muros.
__out.murosPlanta = planta.cajas.filter(k => k.muro).length;
__out.columnaZona = planta.cajas.some(k => k.lee && k.lee.name === '' && k.lee.kind);
__out.pasillo = planta.cajas.some(k => k.lee && k.lee.name === 'PASILLO');
// La sala sin medidas: sus muros tenues, su rack no.
const deS2 = planta.cajas.filter(k => k.frame && cerca(k.frame.x, 12));
__out.sinMedidasTenue = deS2.length === 4 && deS2.every(k => k.color[3] < 1);
__out.rackDeSinMedidasMacizo = planta.cajas.find(k => k.lee && k.lee.name === 'R2').color[3] === 1;
__out.plano = planta.planos.length === 1 && cerca(planta.planos[0].m[0], 30)
    && cerca(planta.planos[0].m[10], 15);
__out.sinBaldosas = !planta.cajas.some(k => k.color === _DC3_COLOR.tile);

// ── Los muros de una sala girada ────────────────────────────────────────────────
// Girada 90°, la sala de 4×3 m ocupa en la planta x 5.5–8.5, z 1.5–5.5. Con la cámara en su
// centro, todo macizo; desde muy a la izquierda (x = 0), uno de cristal.
const muros = planta.cajas.filter(k => k.muro && k.frame && cerca(k.frame.x, 5));
const dentro = muros.map(k => ss3dWallAlphaOf(k, [7, 1.5, 3.5], planta));
const fuera = muros.map(k => ss3dWallAlphaOf(k, [0, 1.5, 3.5], planta));
__out.murosDentro = dentro.every(a => a === 1);
__out.murosFueraUnoDeCristal = fuera.filter(a => a < 1).length === 1;

// ── El edificio ─────────────────────────────────────────────────────────────────
_ds3Mode = 'building';
_ds3Explode = false;
const edificio = _ds3Scene();
const alturas = edificio.cajas.filter(k => k.muro && k.frame && k.frame.W === 6)
    .map(k => Math.round(k.frame.y * 10) / 10);
__out.alturas = Array.from(new Set(alturas)).sort((a, b) => a - b).join(',');
__out.arribaTenue = edificio.cajas.filter(k => k.muro && k.frame && cerca(k.frame.y, 4))
    .every(k => k.color[3] < 0.3);
__out.sotanoMacizo = edificio.cajas.filter(k => k.muro && k.frame && cerca(k.frame.y, -4))
    .every(k => k.color[3] === 1);
__out.salasDeLaActual = edificio.salas.map(s => s.uid).sort().join(',');
__out.miraLaActual = edificio.mira && cerca(edificio.mira[1], 1);
__out.sotanoBajoCero = edificio.Y0 < -4;
_ds3Explode = true;
const separadas = _ds3Scene();
__out.separadas = separadas.cajas.some(k => k.muro && k.frame && cerca(k.frame.y, 10));
_ds3Apart = 20;
const a20 = _ds3Scene();
__out.separacion = a20.cajas.some(k => k.muro && k.frame && cerca(k.frame.y, 20))
    && a20.cajas.some(k => k.muro && k.frame && cerca(k.frame.y, -20));
_ds3Explode = false;
__out.juntasNoCambian = _ds3Scene().cajas.some(k => k.muro && k.frame && cerca(k.frame.y, 4));
_ds3Apart = 10;
_ds3Explode = false;
// Ver la planta de abajo desde arriba: las losas y los planos, tan opacos como diga el
// deslizador; las salas y lo que tienen, no.
const losas = (e) => e.cajas.filter(k => k.color[0] === _DC3_COLOR.ground[0] && k.color[1] === _DC3_COLOR.ground[1]);
_ds3Veil = 0.3;
const velado = _ds3Scene();
__out.veloLosas = losas(velado).length > 0 && losas(velado).every(k => k.color[3] <= 0.3 + 1e-9);
__out.veloPlanos = velado.planos.length > 0 && velado.planos.every(p => p.alpha <= 0.3);
__out.veloSalasMacizas = velado.cajas.filter(k => k.muro && k.frame && cerca(k.frame.y, -4)).every(k => k.color[3] === 1);
const prep = ss3dPrepare(velado);
__out.losasAntesDelPlano = prep.bajos.length === losas(velado).length && !prep.vidrios.some(k => k.bajo);
_ds3Veil = 1;
__out.sinVeloLosas = losas(_ds3Scene()).filter(k => k.color[3] === 1).length > 0;
_ds3Mode = 'floor';
_ds3Veil = 0.3;
__out.plantaSolaSinVelo = losas(_ds3Scene()).every(k => k.color[3] === 1);
_ds3Veil = 1;
_ds3Mode = 'building';

// ── Señalar y abrir ─────────────────────────────────────────────────────────────
_ds3Mode = 'floor';
const vPick = {escena: planta};
let abierta = '';
_dcimOpenPlan = (uid) => { abierta = uid; };
const abajo = {o: [7, 30, 3.5], d: [0, -1, 0]};
__out.primerClic = _ds3Pick(abajo, vPick);
__out.noAbreAlPrimero = abierta === '';
_ds3Pick(abajo, vPick);
__out.abreAlSegundo = abierta;
__out.fueraDeTodo = _ds3Pick({o: [-0.5, 30, -0.5], d: [0, -1, 0]}, vPick);

// ── La rueda acerca hacia el cursor ─────────────────────────────────────────────
const escZ = {W: 40, D: 30, H: 3};
const camZ = {mira: [20, 1, 15], radio: 30, theta: Math.PI / 3, phi: 0.95};
const ojoDe = (c) => [c.mira[0] + c.radio * Math.sin(c.phi) * Math.cos(c.theta),
                      c.mira[1] + c.radio * Math.cos(c.phi),
                      c.mira[2] + c.radio * Math.sin(c.phi) * Math.sin(c.theta)];
const lienzo = {getBoundingClientRect: () => ({left: 0, top: 0, width: 1000, height: 500})};
const vZ = {cam: camZ, escena: escZ, cv: lienzo};
vZ.ojo = ojoDe(camZ);
// En el centro de la pantalla el punto bajo el cursor es el centro: acercar no lo mueve.
const rueda = (x, y) => ({clientX: x, clientY: y, deltaY: -1, preventDefault() {}});
ss3dWheel(vZ, rueda(500, 250));
__out.centroQuieto = Math.hypot(camZ.mira[0] - 20, camZ.mira[2] - 15) < 1e-6;
// A un lado: el punto bajo el cursor se queda donde estaba y el centro se le acerca en la
// misma proporción que el radio.
vZ.ojo = ojoDe(camZ);
const p = ss3dCursorGround(vZ, {clientX: 850, clientY: 300}, camZ.mira[1]);
const d0 = Math.hypot(p[0] - camZ.mira[0], p[2] - camZ.mira[2]), r0 = camZ.radio;
ss3dWheel(vZ, rueda(850, 300));
const d1 = Math.hypot(p[0] - camZ.mira[0], p[2] - camZ.mira[2]);
__out.haciaElCursor = d0 > 0.5 && Math.abs(d1 / d0 - camZ.radio / r0) < 1e-6;
// Alejando al tope, la rueda no anda hacia delante.
camZ.radio = 90;
const antesTope = camZ.mira.slice();
ss3dWheel(vZ, {clientX: 500, clientY: 250, deltaY: 1, preventDefault() {}});
__out.topeQuieto = camZ.mira.every((v, i) => Math.abs(v - antesTope[i]) < 1e-9);

// ── Los rótulos ─────────────────────────────────────────────────────────────────
const salaR = _dc3dRoomBoxes({width_mm: 6000, depth_mm: 5000},
    [{uid: 'r', name: 'Rack01', pos_x: 1000, pos_y: 1000, u_height: 42, roll: {}}],
    [{uid: 'm', kind: 'bench', label: 'MesaTaller', pos_x: 3000, pos_y: 3000},
     {uid: 'd', kind: 'door', label: '', pos_x: 0, pos_y: 0}],
    {bench: {h: 750, layer: 'room'}, door: {h: 2100, layer: 'room'}}, {});
const rot = ss3dLabelsOf(salaR);
__out.rotulos = rot.map(e => e.name).sort().join(',');
const r01 = rot.find(e => e.name === 'Rack01');
__out.rackArriba = Math.abs(r01.p[1] - 42 * 44.45 * 0.001) < 1e-6;
// En la planta, las salas por su nombre; en el edificio, no las de las plantas tenues.
__out.rotulosPlanta = ss3dLabelsOf(planta).filter(e => e.area).map(e => e.name).sort().join(',');
_ds3Mode = 'building';
const edif = _ds3Scene();
__out.rotulosEdificio = ss3dLabelsOf(edif).filter(e => e.area).map(e => e.name).sort().join(',');
_ds3Mode = 'floor';
// En pantalla: lo de delante de la cámara se coloca; lo de detrás se oculta.
const camL = {mira: [3, 1, 2.5], radio: 8, theta: Math.PI / 3, phi: 0.95};
const ojoL = [camL.mira[0] + camL.radio * Math.sin(camL.phi) * Math.cos(camL.theta),
              camL.mira[1] + camL.radio * Math.cos(camL.phi),
              camL.mira[2] + camL.radio * Math.sin(camL.phi) * Math.sin(camL.theta)];
const vpL = ss3dMul(ss3dPerspective(0.96, 2, 0.05, 400), ss3dLookAt(ojoL, camL.mira));
const elDelante = {style: {}}, elDetras = {style: {}};
ss3dShowLabels = true;
ss3dLabelsTurn({cv: {clientWidth: 1000, clientHeight: 500}, ojo: ojoL, cam: camL,
                 escena: {etiquetas: [{name: 'A', p: camL.mira}, {name: 'B', p: [ojoL[0] * 3, ojoL[1], ojoL[2] * 3]}]},
                 labelEls: [elDelante, elDetras]}, vpL);
__out.delante = elDelante.style.display === '' && /translate\(500\.0px, 250\.0px\)/.test(elDelante.style.transform || '');
__out.detras = elDetras.style.display === 'none';

// ── El visor de la sala sigue igual ─────────────────────────────────────────────
_dc3d = null;
_dcimPlan = {room: {width_mm: 6000, depth_mm: 5000, tile_mm: 600},
             racks: [{uid: 'r0', pos_x: 1000, pos_y: 1000, u_height: 42, roll: {}}]};
_dcpFeat = {features: [], kinds: {}};
const deSala = _dc3dScene();
__out.salaConBaldosas = deSala.cajas.some(k => k.color === _DC3_COLOR.tile);
__out.salaMuros = deSala.cajas.filter(k => k.muro).length;

// ── Lo de la sede, de una vez ───────────────────────────────────────────────────
const pedidas = [];
apiGet = async (url) => { pedidas.push(url); return {rooms: {s1: {racks: [], features: []}}}; };
_dcsLoadContents();
__out.unaPeticion = pedidas.join('|');

// ── El 3D sigue a lo que se cambia en el plano ──────────────────────────────────
// Reportado: una mesa arrastrada se guardaba, y el 3D la seguía enseñando en su sitio viejo.
const relojes = [];
let quitados = 0;
setTimeout = (f, ms) => { relojes.push({f, ms}); return relojes.length; };
clearTimeout = () => { quitados++; };
_dc3d = null;
_dc3dSoon();
__out.soonApagado = relojes.length;
_dc3d = {on: true};
for (let i = 0; i < 20; i++) _dc3dSoon();
__out.soon = {programados: relojes.length, quitados, rehace: relojes[0].f === _dc3dRebuild,
              espera: relojes[0].ms};
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


class TestUnaPlantaEn3D:
    def test_cada_rack_en_el_mismo_sitio_que_en_el_plano_de_la_planta(self, out):
        assert out['rackEnSuSitio'], 'una sala girada sale en 3D en otro sitio que en el plano'

    def test_se_senalan_las_salas_y_no_la_zona_general(self, out):
        assert out['salas'] == 's1,s2'

    def test_la_zona_general_sin_muros_pero_con_lo_de_dentro(self, out):
        assert out['murosPlanta'] == 8
        assert out['pasillo'] and out['columnaZona']

    def test_cada_muro_sabe_de_que_sala_es(self, out):
        assert out['murosConMarco']

    def test_sin_medidas_tenue_lo_que_la_delimita_no_lo_de_dentro(self, out):
        assert out['sinMedidasTenue']
        assert out['rackDeSinMedidasMacizo']

    def test_el_plano_del_arquitecto_al_suelo_con_su_tamano(self, out):
        assert out['plano'], '30 m dichos y la mitad de alto que de ancho'

    def test_sin_lineas_de_baldosa(self, out):
        """Son la mayor parte de las cajas de una sala grande y desde la planta no se leen."""
        assert out['sinBaldosas']


class TestLosMurosDeUnaSalaGirada:
    def test_desde_dentro_todo_macizo(self, out):
        assert out['murosDentro']

    def test_desde_fuera_el_de_delante_de_cristal(self, out):
        assert out['murosFueraUnoDeCristal']


class TestElEdificio:
    def test_las_plantas_apiladas_por_su_nivel(self, out):
        assert out['alturas'] == '-4,4'
        assert out['sotanoBajoCero']

    def test_las_de_encima_tenues_las_de_debajo_macizas(self, out):
        assert out['arribaTenue']
        assert out['sotanoMacizo']

    def test_se_senalan_solo_las_salas_de_la_planta_que_se_mira(self, out):
        assert out['salasDeLaActual'] == 's1,s2'
        assert out['miraLaActual']

    def test_separar_las_aleja(self, out):
        assert out['separadas']


class TestSenalarYAbrir:
    def test_un_clic_dice_cual_y_otro_la_abre(self, out):
        assert out['primerClic'] == 's1'
        assert out['noAbreAlPrimero']
        assert out['abreAlSegundo'] == 's1'

    def test_fuera_de_las_salas_nada(self, out):
        assert out['fueraDeTodo'] is None


class TestLaRuedaAcercaHaciaElCursor:
    """Se pidió: la rueda acercaba siempre al centro de la vista, y lo que se quería ver
    estaba donde apuntaba el ratón."""

    def test_en_el_centro_no_se_mueve(self, out):
        assert out['centroQuieto']

    def test_a_un_lado_se_acerca_a_lo_que_hay_bajo_el_cursor(self, out):
        assert out['haciaElCursor']

    def test_alejando_al_tope_no_anda(self, out):
        assert out['topeQuieto']


class TestLosRotulos:
    """Se pidió ver en el 3D el nombre de cada cosa: Rack01, MesaTaller…"""

    def test_lo_que_tiene_nombre_y_nada_mas(self, out):
        assert out['rotulos'] == 'MesaTaller,Rack01', 'una puerta sin etiqueta no lleva rótulo'

    def test_encima_de_lo_que_nombra(self, out):
        assert out['rackArriba']

    def test_las_salas_por_su_nombre(self, out):
        assert out['rotulosPlanta'].split(',') == ['Almacén', 'CPD']

    def test_en_el_edificio_no_las_de_las_plantas_tenues(self, out):
        assert 'Despachos' not in out['rotulosEdificio']
        assert 'CPD' in out['rotulosEdificio'] and 'Archivo' in out['rotulosEdificio']

    def test_en_pantalla_donde_cae_y_lo_de_detras_oculto(self, out):
        assert out['delante'], 'el punto que se mira cae en el centro de la pantalla'
        assert out['detras']


class TestLaSalaSigueIgual:
    def test_su_visor_conserva_baldosas_y_muros(self, out):
        assert out['salaConBaldosas']
        assert out['salaMuros'] == 4


class TestLoDeLaSedeDeUnaVez:
    def test_una_peticion_por_sede(self, out):
        assert out['unaPeticion'] == '/api/v1/dcim/sites/sede/contents'


class TestElTresDSigueAlPlano:
    """Reportado: una pieza arrastrada en el plano se guardaba, pero el 3D abierto la seguía
    enseñando en su sitio viejo hasta el siguiente repintado completo."""

    def test_sin_3d_no_se_programa_nada(self, out):
        assert out['soonApagado'] == 0

    def test_se_rehace_una_vez_cuando_el_plano_para(self, out):
        s = out['soon']
        assert s['rehace'] and s['espera'] > 0
        assert s['quitados'] >= 19, 'cada cambio aplaza el anterior: un arrastre rehace una vez'


class TestVerLaPlantaDeAbajo:
    """Se pidió poder ver desde arriba la planta de abajo en el edificio: la losa y el plano de
    cada planta la tapaban entera."""

    def test_las_losas_y_los_planos_tan_opacos_como_el_deslizador(self, out):
        assert out['veloLosas'] and out['veloPlanos']

    def test_las_salas_siguen_macizas(self, out):
        assert out['veloSalasMacizas']

    def test_sin_velo_como_estaba_y_la_planta_sola_no_cambia(self, out):
        assert out['sinVeloLosas']
        assert out['plantaSolaSinVelo']

    def test_la_losa_translucida_se_dibuja_antes_que_el_plano(self, out):
        """Reportado: al 99 % el plano desaparecía — la losa, debajo de él, se dibujaba encima."""
        assert out['losasAntesDelPlano']


class TestLaSeparacionSeAjusta:
    """Se pidió ajustar la separación entre plantas como la opacidad."""

    def test_separadas_cada_planta_a_la_distancia_del_deslizador(self, out):
        assert out['separacion']

    def test_juntas_siguen_a_la_altura_de_una_planta(self, out):
        assert out['juntasNoCambian']
