#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probar el mapa: la única pantalla que puede decir **por qué** no sale.

Un mapa que no dibuja no se queja por su cuenta, y esa es toda la razón de que esto exista. El
navegador se traga una imagen que no carga; la política de contenido bloquea en silencio; una
clave sin permiso recibe un 403 que no ve nadie. Las tres cosas se ven igual —el mismo cuadro
vacío— y no hay por dónde empezar.

Así que esta ruta recorre la cadena entera y devuelve **cada paso por separado**, con el detalle
en crudo de lo que contestó el otro extremo. Ese detalle es lo único que distingue «la clave no
tiene activada la Map Tiles API» de «esta máquina no sale a internet», y por eso no se traduce:
no es texto de este panel.

De mentira la red y nada más. Una prueba que llama a Google falla el día que se cae, el día que
caduca una clave y el día que alguien la ejecuta en un tren.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from tests.conftest import _login                                   # noqa: E402

RUTA = '/api/v1/config/map/test'


def _cfg(client, **campos):
    r = client.put('/api/v1/config', json={'web_admin': campos})
    assert r.status_code == 200, r.get_json()


@pytest.fixture()
def sesion(monkeypatch):
    """Google contestando que sí, sin Google."""
    from lib.maps import google as gmaps                            # noqa: PLC0415
    gmaps.forget()

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=None):
            return json.dumps({'session': 'SES', 'expiry': '4102444800'}).encode('utf-8')

    monkeypatch.setattr(gmaps, '_open', lambda url, data, timeout: _R())
    yield
    gmaps.forget()


@pytest.fixture()
def tesela(monkeypatch):
    """Y una tesela que llega."""
    import lib.core.config.routes as rutas                          # noqa: PLC0415,F401
    import lib.maps as maps                                         # noqa: PLC0415
    monkeypatch.setattr(maps, 'probe_tile',
                        lambda tpl: {'ok': True, 'status': 200, 'type': 'image/png',
                                     'bytes': 1234, 'detail': '', 'url': tpl})


class TestSinMapaLoDicePorSuNombre:

    def test_no_hay_nada_que_probar(self, client):
        """Y no un fallo: no tener mapa es el estado de fábrica, no una avería."""
        _login(client)
        r = client.post(RUTA, json={})
        assert r.status_code == 200
        assert r.get_json()['error'] == 'map_err_off'

    def test_personalizado_sin_plantilla_tambien(self, client):
        _login(client)
        _cfg(client, dcim_map_provider='custom', dcim_map_tiles='')
        assert client.post(RUTA, json={}).get_json()['error'] == 'map_err_no_tiles'


class TestConUnProveedorSeRecorreLaCadena:

    def test_dice_cual_es_y_hasta_donde_llega(self, client, tesela):
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        d = client.post(RUTA, json={}).get_json()
        assert d['provider'] == 'osm'
        assert d['zmax'] == 19
        assert not d['error']

    def test_y_el_origen_que_hay_que_abrir(self, client, tesela):
        """La mitad que falla sin dejar rastro: si el servidor trae la tesela y el navegador no
        la pinta, es la política de contenido — y esto es lo que hay que comparar con ella."""
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        assert client.post(RUTA, json={}).get_json()['origin'] \
            == 'https://tile.openstreetmap.org'

    def test_y_el_credito_que_se_va_a_pintar(self, client, tesela):
        """Que la licencia exige, y que no se ve hasta que el mapa dibuja."""
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        assert 'OpenStreetMap' in client.post(RUTA, json={}).get_json()['attribution']

    def test_y_si_la_tesela_no_llega_lo_dice_con_lo_que_paso(self, client, monkeypatch):
        """«No hay salida a internet» y «no nos quieren dar imágenes» se ven igual desde la
        pantalla, y son dos arreglos distintos."""
        import lib.maps as maps                                     # noqa: PLC0415
        monkeypatch.setattr(maps, 'probe_tile',
                            lambda tpl: {'ok': False, 'status': 0, 'type': '', 'bytes': 0,
                                         'detail': 'getaddrinfo failed'})
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        d = client.post(RUTA, json={}).get_json()
        assert d['error'] == 'map_err_tile'
        assert 'getaddrinfo' in d['detail']


class TestConGoogleSeMiraTambienLaSesion:

    def test_una_sesion_concedida_se_cuenta_aparte(self, client, sesion, tesela):
        """Son dos fallos distintos: no dar sesión (la clave) y no dar la imagen (la red)."""
        _login(client)
        _cfg(client, dcim_map_provider='google', dcim_map_google_key='K')
        d = client.post(RUTA, json={}).get_json()
        assert d['session'] is True
        assert not d['error']

    def test_y_si_no_la_dan_se_dice_lo_que_contestaron(self, client, monkeypatch):
        """Aquí está la respuesta entera: la Map Tiles API sin activar, el proyecto sin
        facturación, o una restricción por referente que a una llamada de servidor le falta. Un
        aviso rojo sin esto es otro cuadro vacío."""
        from lib.maps import google as gmaps                        # noqa: PLC0415
        gmaps.forget()

        def _revienta(url, data, timeout):
            raise OSError('HTTP Error 403: API not enabled')
        monkeypatch.setattr(gmaps, '_open', _revienta)
        _login(client)
        _cfg(client, dcim_map_provider='google', dcim_map_google_key='K')
        d = client.post(RUTA, json={}).get_json()
        assert d['error'] == 'gmaps_err_session'
        assert 'API not enabled' in d['detail']
        assert d['session'] is False

    def test_y_no_se_prueba_contra_la_sesion_guardada(self, client, monkeypatch):
        """Probar con la de antes contestaría que todo va bien con una clave recién cambiada."""
        from lib.maps import google as gmaps                        # noqa: PLC0415
        llamadas = []

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=None):
                llamadas.append(1)
                return json.dumps({'session': 'SES',
                                   'expiry': '4102444800'}).encode('utf-8')

        monkeypatch.setattr(gmaps, '_open', lambda url, data, timeout: _R())
        import lib.maps as maps                                     # noqa: PLC0415
        monkeypatch.setattr(maps, 'probe_tile',
                            lambda tpl: {'ok': True, 'status': 200, 'type': 'image/png',
                                         'bytes': 9, 'detail': ''})
        _login(client)
        _cfg(client, dcim_map_provider='google', dcim_map_google_key='K')
        client.post(RUTA, json={})
        client.post(RUTA, json={})
        assert len(llamadas) == 2, 'la segunda prueba reusó la sesión de la primera'


class TestSePruebaLoQueHayEnPantalla:
    """Y no lo guardado. Un botón de probar que sólo mira lo guardado contesta siempre lo mismo
    mientras alguien cambia de proveedor y vuelve a pulsar — y lo que se quiere saber antes de
    guardar es precisamente si lo nuevo va a funcionar. Reportado desde la pantalla."""

    def test_lo_posteado_manda_sobre_lo_guardado(self, client, tesela):
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        d = client.post(RUTA, json={'web_admin': {'dcim_map_provider': 'carto_dark'}}).get_json()
        assert d['provider'] == 'carto_dark', d
        assert d['zmax'] == 20, 'ni siquiera el tope viene del guardado'

    def test_y_vaciar_una_casilla_tambien_es_decir_algo(self, client, tesela):
        """«Sin plantilla propia» es una respuesta, y probar con la de antes contestaría que
        funciona algo que se acaba de borrar."""
        _login(client)
        _cfg(client, dcim_map_provider='custom',
             dcim_map_tiles='https://viejo.example/{z}/{x}/{y}.png')
        d = client.post(RUTA, json={'web_admin': {'dcim_map_provider': 'custom',
                                                  'dcim_map_tiles': ''}}).get_json()
        assert d['error'] == 'map_err_no_tiles'

    def test_pero_la_clave_que_no_viaja_sigue_siendo_la_guardada(self, client, sesion, tesela):
        """Sale enmascarada a la pantalla, así que si nadie la ha tocado no vuelve — y exigirla
        haría que probar sin reescribirla dijera siempre que falta la clave."""
        _login(client)
        _cfg(client, dcim_map_provider='google', dcim_map_google_key='LA-GUARDADA')
        d = client.post(RUTA, json={'web_admin': {'dcim_map_provider': 'google'}}).get_json()
        assert d['session'] is True, d
        assert not d['error']

    def test_y_sin_mandar_nada_se_prueba_lo_guardado(self, client, tesela):
        """Que es lo que pasa al pulsar sin haber tocado nada."""
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        assert client.post(RUTA, json={}).get_json()['provider'] == 'osm'


class TestElCuadroPuedeDibujarElMapa:

    def test_la_direccion_lista_viaja_de_vuelta(self, client, tesela):
        """El servidor se trae una tesela por su cuenta, pero quien tiene que poder traerlas es
        el NAVEGADOR — y eso sólo se ve dibujando."""
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        assert 'openstreetmap' in client.post(RUTA, json={}).get_json()['tiles']

    def test_y_con_la_sesion_de_google_ya_puesta(self, client, sesion, tesela):
        """Sin ella, el navegador pediría una dirección con un hueco dentro."""
        _login(client)
        _cfg(client, dcim_map_provider='google', dcim_map_google_key='K')
        tpl = client.post(RUTA, json={}).get_json()['tiles']
        assert 'session=SES' in tpl and '{session}' not in tpl

    def test_pero_no_si_no_hay_mapa(self, client):
        """Una dirección de vuelta cuando no hay mapa sería un dibujo que no puede salir."""
        _login(client)
        assert client.post(RUTA, json={}).get_json()['tiles'] == ''


class TestElCuadroDibujaPorElPanel:
    """Y no directamente desde el proveedor, que es lo que hace un mapa de verdad.

    La razón es la política de contenido: `img-src` se abre para el origen que sale de la
    configuración **guardada**, así que un proveedor recién elegido en el formulario tiene su
    origen cerrado y el navegador bloquea cada tesela **sin decir una palabra** — sólo queda la
    chincheta sobre un rectángulo vacío. Reportado desde la pantalla: «cambio la selección, doy
    a probar y no sale mapa; hasta que no guardo y refresco con F5 no funciona».
    """

    def test_la_prueba_dice_por_donde_dibujar(self, client, tesela):
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        d = client.post(RUTA, json={}).get_json()
        assert d['preview'].startswith('/api/v1/'), d['preview']
        for hueco in ('{z}', '{x}', '{y}'):
            assert hueco in d['preview']

    def test_y_esa_direccion_sirve_la_tesela(self, client, monkeypatch, tesela):
        import lib.maps as maps                                     # noqa: PLC0415
        monkeypatch.setattr(maps, 'fetch_tile',
                            lambda tpl, z, x, y: (b'PNG-de-mentira', 'image/png'))
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        client.post(RUTA, json={})
        r = client.get('/api/v1/config/map/preview/12/2020/1512')
        assert r.status_code == 200
        assert r.headers['Content-Type'].startswith('image/')
        assert r.data

    def test_incluso_con_un_proveedor_que_no_esta_guardado(self, client, monkeypatch, tesela):
        """Que es el caso entero: sin esto no hay forma de ver el mapa nuevo antes de guardar."""
        vistas = []
        import lib.maps as maps                                     # noqa: PLC0415
        monkeypatch.setattr(maps, 'fetch_tile',
                            lambda tpl, z, x, y: (vistas.append(tpl), (b'PNG', 'image/png'))[1])
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        d = client.post(RUTA, json={'web_admin': {'dcim_map_provider': 'carto_dark'}}).get_json()
        assert d['provider'] == 'carto_dark'
        assert d['saved_provider'] == 'osm', 'no se dice con qué se quedan las demás pantallas'
        assert client.get('/api/v1/config/map/preview/12/2020/1512').status_code == 200
        assert 'cartocdn' in vistas[0], vistas

    def test_cada_prueba_tiene_su_propia_direccion(self, client, tesela):
        """La dirección del cuadro es la MISMA para todos los proveedores —la sirve el panel—,
        así que sin una marca distinta por prueba la tesela que el navegador se trajo probando
        el satélite se reutiliza al probar el callejero: sale un mapa a trozos, mitad foto aérea
        y mitad calles, según cuáles estuvieran ya en la caché. Reportado desde la pantalla, y
        no lo arregla `no-store`: con la misma URL, un `<image>` sale de la caché de la página.
        """
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        una = client.post(RUTA, json={}).get_json()['preview']
        otra = client.post(RUTA, json={'web_admin': {
            'dcim_map_provider': 'esri_imagery'}}).get_json()['preview']
        assert una != otra, una

    def test_y_dice_como_se_llama_lo_guardado_sin_componer_la_clave(self, client, tesela):
        """El del IGN se llama `ign_pnoa` y su rótulo es `…_ign`: componer el nombre con el
        identificador sacó la clave en crudo a la pantalla."""
        _login(client)
        _cfg(client, dcim_map_provider='ign_pnoa')
        d = client.post(RUTA, json={'web_admin': {'dcim_map_provider': 'osm'}}).get_json()
        assert d['saved_label_key'] == 'dcim_map_provider_ign'
        assert d['label_key'] == 'dcim_map_provider_osm'

    def test_sin_haber_probado_no_hay_nada_que_servir(self, client):
        """No es un proxy abierto: la dirección no viene en la petición, viene de lo que esta
        misma persona acaba de probar."""
        _login(client)
        assert client.get('/api/v1/config/map/preview/12/2020/1512').status_code == 404

    def test_y_lo_que_no_sea_una_imagen_no_se_sirve(self, client, monkeypatch, tesela):
        """Hay servidores que contestan una página de error con un 200 encima; devolverla sería
        servir el HTML de otro desde este origen."""
        import lib.maps as maps                                     # noqa: PLC0415
        monkeypatch.setattr(maps, 'fetch_tile', lambda tpl, z, x, y: (b'', ''))
        _login(client)
        _cfg(client, dcim_map_provider='osm')
        client.post(RUTA, json={})
        assert client.get('/api/v1/config/map/preview/12/2020/1512').status_code == 404

    def test_y_pide_el_mismo_permiso_que_configurar(self, client):
        r = client.get('/api/v1/config/map/preview/12/2020/1512')
        assert r.status_code in (401, 403)


class TestCuandoHayQueRecargarYCuandoNo:
    """La política de contenido viaja en la cabecera de cada página: la que tiene delante quien
    guarda se sirvió con la configuración de ANTES. Lo decide el servidor, que es el único que
    sabe con qué se sirvió — la pantalla no puede leer su propia cabecera."""

    def _guarda(self, client, **campos):
        return client.put('/api/v1/config',
                          json={'web_admin': campos}).get_json().get('reload_required')

    def test_encender_el_mapa_pide_recargar(self, client):
        """Antes no había ningún origen abierto: la página no puede pedir ni una tesela."""
        _login(client)
        assert self._guarda(client, dcim_map_provider='osm') is True

    def test_pero_cambiar_de_proveedor_ya_no(self, client):
        """Que es la pregunta que trajo esto: con el mapa encendido, la página ya podía cargar
        de cualquiera de los del catálogo."""
        _login(client)
        self._guarda(client, dcim_map_provider='osm')
        assert self._guarda(client, dcim_map_provider='carto_dark') is False
        assert self._guarda(client, dcim_map_provider='ign_pnoa') is False
        assert self._guarda(client, dcim_map_provider='google') is False

    def test_un_servidor_propio_si(self, client):
        """Su dirección no la conoce nadie de antemano, así que no puede estar abierta."""
        _login(client)
        self._guarda(client, dcim_map_provider='osm')
        assert self._guarda(client, dcim_map_provider='custom',
                            dcim_map_tiles='https://mapas.interno/{z}/{x}/{y}.png') is True

    def test_y_apagarlo_no(self, client):
        """No hay nada que cargar: pedir una recarga para dejar de ver algo es ruido."""
        _login(client)
        self._guarda(client, dcim_map_provider='osm')
        assert self._guarda(client, dcim_map_provider='', dcim_map_tiles='') is False

    def test_y_guardar_cualquier_otra_cosa_tampoco(self, client):
        """Un aviso que sale al guardar cualquier ajuste deja de leerse."""
        _login(client)
        assert self._guarda(client, dcim_map_provider='osm') is True
        assert self._guarda(client, dcim_map_attribution='© Quien sea') is False


class TestEstoEsUnAjusteYSePideComoTal:

    def test_sin_sesion_no_se_prueba_nada(self, client):
        r = client.post(RUTA, json={})
        assert r.status_code in (401, 403), r.status_code

    def test_y_hace_falta_poder_editar_la_configuracion(self, admin):
        """Pide una tesela a un tercero desde este servidor: no es una lectura."""
        from werkzeug.security import generate_password_hash        # noqa: PLC0415
        admin._custom_roles['r-mirona'] = {
            'uid': 'r-mirona', 'name': 'r-mirona', 'description': '',
            'permissions': ['config_view'], 'enabled': True,
            'created_at': '2026-09-06T00:00:00Z', 'updated_at': '2026-09-06T00:00:00Z',
            'updated_by': 'test'}
        admin._users['mirona'] = {'uid': 'u-mirona', 'role': 'r-mirona', 'enabled': True,
                                  'password_hash': generate_password_hash('pw-secret')}
        c = admin.app.test_client()
        c.post('/login', data={'username': 'mirona', 'password': 'pw-secret'},
               follow_redirects=True)
        assert c.post(RUTA, json={}).status_code == 403
