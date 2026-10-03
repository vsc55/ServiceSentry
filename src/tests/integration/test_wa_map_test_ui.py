#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El informe de «Probar el mapa», **dibujado**.

Salió a la pantalla diciendo dos cosas a la vez: **«El mapa funciona»** en verde y, justo debajo,
el proveedor con una cruz roja y los demás pasos en blanco. Reportado tal cual: «esto es
confuso, ¿error u ok?».

La causa no se ve leyendo el informe: `apiSend` devuelve un **sobre** —`{ok, error, data}`— y lo
que hay que dibujar va dentro, en `data`. Leído como si el sobre fuese la carta, la cabecera
miraba `sobre.error` —vacío, porque la petición fue bien— y los pasos miraban campos que no
estaban ahí. Cada mitad hacía exactamente lo que decía su código.

Y la prueba de la ruta pasaba, porque la ruta estaba bien. Lo que había que ejercitar era **la
función que dibuja, con lo que de verdad le llega**, que es lo que hace esto.

De ahí sale también la otra mitad del arreglo: la cabecera se saca de los MISMOS datos que los
pasos, así que ya no puede contradecirlos.
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

#: Un informe de los buenos: proveedor, tesela y origen.
_BIEN = {'provider': 'osm', 'zmax': 19, 'attribution': '© OpenStreetMap contributors',
         'origin': 'https://tile.openstreetmap.org', 'session': False, 'error': '', 'detail': '',
         'tiles': 'https://tile.example.org/{z}/{x}/{y}.png',
         # Por donde dibuja el cuadro: el propio panel. Directamente no puede — `img-src` sólo
         # abre el origen que sale de la configuración GUARDADA, así que un proveedor recién
         # elegido tendría todas sus imágenes bloqueadas sin una palabra.
         'preview': '/api/v1/config/map/preview/{z}/{x}/{y}',
         'saved_provider': 'osm',
         'tile': {'ok': True, 'status': 200, 'type': 'image/png', 'bytes': 4096, 'detail': ''}}

#: Y uno malo de los que traen la respuesta dentro: la clave de Google sin permiso.
_MAL = {'provider': 'google', 'zmax': 22, 'attribution': 'Map data ©Google',
        'origin': 'https://tile.googleapis.com', 'session': False, 'tile': {},
        'preview': '', 'saved_provider': 'google',
        'error': 'gmaps_err_session', 'detail': 'HTTP Error 403: API not enabled'}

_PRUEBA = """
const BIEN = %(bien)s, MAL = %(mal)s;

__out = {};
// Lo que se ejercita es **abrir el sobre**, que es donde estuvo el fallo: llamar a
// `_mapTestHtml` con el informe pelado no lo reproduce, porque el informe pelado sí tiene los
// campos. `mapTest` es asíncrona y el arnés no espera promesas; esta decisión no lo es, y por
// eso vive en su propia función.
__out.ok = _mapReport({ok: true, error: '', data: BIEN});
__out.mal = _mapReport({ok: true, error: '', data: MAL});
// El caso exacto que salió a la pantalla: la petición va bien y el informe viene vacío.
__out.vacio = _mapReport({ok: true, error: '', data: {}});
// Un 403 del propio panel: el sobre trae el error y no hay informe.
__out.prohibido = _mapReport({ok: false, error: 'no', data: {}});
// Y ni siquiera eso: la conexión se cayó.
__out.sinNada = _mapReport(null);
// ── El punto de la ciudad, al acercarse ─────────────────────────────────────────
// Se dibuja en coordenadas del MUNDO, así que con un radio fijo crece al acercarse hasta tapar
// la ciudad. Reportado desde la pantalla: «el punto no redimensiona».
const radio = (html) => Number((html.match(/<circle[^>]*r="([\d.]+)"/) || [])[1]);
__out.pinLejos = radio(_mapPin({x: 100, y: 100}, 1));
__out.pinCerca = radio(_mapPin({x: 100, y: 100}, 0.01));

// Y el caso de probar algo que todavía no está guardado.
const OTRO = JSON.parse(JSON.stringify(BIEN));
OTRO.saved_provider = 'carto_dark';
__out.distinto = _mapReport({ok: true, error: '', data: OTRO});

__out.diceOk = t('map_ok');
__out.diceRaro = t('map_err_unknown');
__out.diceSesion = t('gmaps_err_session');
"""


@pytest.fixture(scope='module')
def informe():
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
    return node_run(panel_bundle(c),
                    _PRUEBA % {'bien': json.dumps(_BIEN), 'mal': json.dumps(_MAL)})


class TestLaCabeceraNoPuedeContradecirALosPasos:
    """Decir «funciona» encima de tres cruces rojas es peor que no decir nada: quien lo lee ya no
    sabe a cuál de las dos mitades hacer caso."""

    def test_cuando_todo_ha_ido_bien_lo_dice_una_vez(self, informe):
        assert informe['diceOk'] in informe['ok']
        assert 'alert-success' in informe['ok']
        assert 'alert-danger' not in informe['ok']
        assert 'bi-x-circle-fill' not in informe['ok'], 'un paso en rojo bajo una cabecera verde'

    def test_un_informe_vacio_no_es_un_mapa_que_funciona(self, informe):
        """El caso exacto que salió a la pantalla: la petición fue bien y no llegó informe."""
        assert 'alert-success' not in informe['vacio']
        assert informe['diceOk'] not in informe['vacio']
        assert informe['diceRaro'] in informe['vacio']

    def test_y_sin_tesela_tampoco(self, informe):
        """Es el paso que de verdad prueba algo: sin él no se ha comprobado nada."""
        assert 'alert-success' not in informe['mal']


class TestYSeVeElMapa:
    """Un informe en verde encima de un cuadro vacío sigue sin convencer a nadie — y hay una
    mitad que el servidor no puede comprobar por mucho que se traiga una tesela: quien tiene que
    poder traerlas es el NAVEGADOR, y lo que se lo impide no deja rastro en la página."""

    def test_se_dibuja_un_trozo_de_mapa_de_verdad(self, informe):
        assert '<svg' in informe['ok']
        assert '<image' in informe['ok'], 'el dibujo no pide ni una tesela'

    def test_y_las_pide_al_panel_y_no_al_proveedor(self, informe):
        """Es lo que hace que se vea un proveedor que todavía no está guardado: su origen está
        cerrado en la política de contenido, y el del panel no."""
        assert '/api/v1/config/map/preview/' in informe['ok']
        assert 'tile.example.org' not in informe['ok'].split('ss-map-credit')[0],             'el dibujo pide las teselas directamente y se las van a bloquear'

    def test_centrado_donde_se_reconozca_algo(self, informe):
        """Y no en las sedes de esta casa: la prueba se hace muchas veces ANTES de que haya
        ninguna con coordenadas, y un mapa centrado en el golfo de Guinea no demuestra nada."""
        # La chincheta cae donde proyecta Pamplona, con los números del propio guion.
        assert 'circle cx=' in informe['ok']

    def test_el_punto_encoge_al_acercarse(self, informe):
        """En coordenadas del mundo, un radio fijo crece con el zoom hasta tapar la ciudad que
        venía a señalar."""
        assert informe['pinCerca'] < informe['pinLejos'] / 50, (
            informe['pinLejos'], informe['pinCerca'])

    def test_y_sin_direccion_no_se_dibuja_un_rectangulo_vacio(self, informe):
        """Un cuadro gris sin explicación se lee como «roto», que es justo lo contrario de lo
        que pasa cuando sencillamente no hay mapa configurado."""
        assert '<svg' not in informe['vacio']
        assert '<svg' not in informe['mal'], 'dibuja un mapa que no se ha podido conseguir'


class TestSiLoProbadoNoEsLoGuardadoSeDice:
    """El cuadro pide las imágenes por el panel, así que enseña un mapa que las demás pantallas
    todavía no pueden pedir. Sin decirlo, «aquí funciona y en el inventario no» es un misterio;
    dicho, son dos pasos que faltan: guardar y recargar."""

    def test_se_avisa_cuando_lo_probado_no_esta_guardado(self, informe):
        assert 'alert-warning' in informe['distinto'], informe['distinto'][:400]

    def test_y_no_se_avisa_cuando_si_lo_esta(self, informe):
        """Un aviso que sale siempre deja de leerse."""
        assert 'alert-warning' not in informe['ok']


class TestLoQueContestoElOtroExtremoSeLee:

    def test_el_fallo_con_nombre_sale_traducido(self, informe):
        assert informe['diceSesion'] in informe['mal']

    def test_y_el_detalle_en_crudo_debajo(self, informe):
        """Ahí está la respuesta entera —la API sin activar, el proyecto sin facturación— y no
        se traduce: no es texto de este panel."""
        assert 'HTTP Error 403: API not enabled' in informe['mal']

    def test_el_origen_se_dice_aunque_todo_vaya_bien(self, informe):
        """Es la mitad que falla sin dejar rastro: si el servidor trae la tesela y el navegador
        no la pinta, es la política de contenido."""
        assert 'https://tile.openstreetmap.org' in informe['ok']

    def test_y_la_sesion_solo_se_mira_en_google(self, informe):
        """Un paso «sesión concedida» en OpenStreetMap sería un paso que no significa nada."""
        assert 'map_step_session' not in informe['ok']


class TestUnFalloDelPanelTambienSeCuenta:

    def test_un_403_no_deja_el_cuadro_en_blanco(self, informe):
        """El cuadro ya está abierto: dejarlo vacío es la peor forma de decir que algo falló."""
        assert 'alert-danger' in informe['prohibido']
        assert len(informe['prohibido']) > 50

    def test_y_una_conexion_caida_tampoco(self, informe):
        assert 'alert-danger' in informe['sinNada']
