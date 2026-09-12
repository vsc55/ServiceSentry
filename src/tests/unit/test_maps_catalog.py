#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Con qué se dibuja un mapa: el catálogo, y la puerta de Google.

Sin red y sin panel. Lo que se comprueba aquí es lo que decide si un mapa sale o no sale, y las
tres formas que tiene de no salir sin decir nada:

* **el proveedor elegido no es el que se dibuja** — una tabla mal leída y el mapa sale de otro
  sitio, o no sale;
* **la instalación que ya tenía su plantilla escrita se queda sin mapa** al actualizar, porque
  ahora hay una lista y ella no eligió nada. Nadie tocó su configuración; se apagó sola;
* **Google contesta con una dirección que no vale** —sin sesión, o con una vieja— y lo que se ve
  son sesenta imágenes rotas en vez de un mapa apagado, que es lo que sí se entiende.

Y la atribución, que no es adorno: la licencia de OpenStreetMap la exige, y un crédito que nombra
al proyecto equivocado es peor que ninguno.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.maps import catalog as maps                                # noqa: E402
from lib.maps import google as gmaps                                # noqa: E402


class TestCadaProveedorTraeSuDireccionYSuCredito:

    def test_ninguno_de_serie(self):
        """Encender un mapa hace que el navegador de cada persona le cuente a un tercero dónde
        están los datacenters de la casa. Eso lo decide quien despliega."""
        assert maps.resolve({}) == {'provider': '', 'tiles': '', 'attribution': '', 'zmax': 0}

    @pytest.mark.parametrize('pid', ['osm', 'carto_light', 'carto_dark'])
    def test_los_que_son_una_direccion_y_ya(self, pid):
        r = maps.resolve({'dcim_map_provider': pid})
        assert r['provider'] == pid
        # Las tres marcas de una plantilla XYZ. Sin una de ellas se pide siempre la misma
        # imagen, que es un mapa de una sola tesela repetida.
        for hueco in ('{z}', '{x}', '{y}'):
            assert hueco in r['tiles'], (pid, hueco)
        assert r['tiles'].startswith('https://'), pid
        assert r['attribution'], f'{pid} se dibuja sin decir de quién es'

    def test_openstreetmap_se_nombra_a_si_mismo(self):
        """Su licencia lo exige, y un crédito que nombra a otro proyecto es peor que ninguno."""
        assert 'OpenStreetMap' in maps.resolve({'dcim_map_provider': 'osm'})['attribution']

    def test_carto_nombra_a_los_dos(self):
        """Los datos son de OpenStreetMap; el dibujo, de Carto. Decir solo uno deja fuera a
        quien puso lo que se está mirando."""
        cred = maps.resolve({'dcim_map_provider': 'carto_light'})['attribution']
        assert 'OpenStreetMap' in cred and 'CARTO' in cred

    def test_cada_uno_dice_hasta_donde_llega(self):
        """Pedir una tesela que no existe no da ningún error visible: da un hueco en blanco al
        acercarse, y quien mira cree que el mapa se ha roto. Son distintos de verdad — 19, 20 y
        22— así que uno solo escrito en el panel se equivocaría con dos de cada tres."""
        topes = {p: maps.resolve({'dcim_map_provider': p})['zmax'] for p in maps.ORDER if p}
        assert topes['osm'] == 19
        assert topes['carto_light'] == topes['carto_dark'] == 20
        assert topes[maps.GOOGLE] == 22
        assert len(set(topes.values())) > 1, 'todos iguales: entonces sobra la columna'

    def test_pero_quien_montó_el_suyo_puede_decir_otra_cosa(self):
        """Un espejo interno trae lo que trae, y eso no lo sabe nadie más que quien lo montó."""
        assert maps.resolve({'dcim_map_provider': maps.CUSTOM,
                             'dcim_map_tiles': 'https://x/{z}/{x}/{y}.png',
                             'dcim_map_max_zoom': 16})['zmax'] == 16

    @pytest.mark.parametrize('malo', [0, -3, 99, '', 'mucho', None])
    def test_y_un_numero_que_no_es_un_nivel_se_ignora(self, malo):
        """No es una preferencia rara: es una errata, y hacerle caso apaga el mapa al
        acercarse."""
        assert maps.resolve({'dcim_map_provider': 'osm',
                             'dcim_map_max_zoom': malo})['zmax'] == 19

    def test_cada_uno_dice_como_se_llama_y_ese_nombre_existe(self):
        """Y se pregunta al catálogo, nunca se compone. Componer `'dcim_map_provider_' + id`
        salió a la pantalla: el del IGN se llama `ign_pnoa` y su rótulo es `…_ign`, así que en
        medio de una frase se leyó «dcim_map_provider_ign_pnoa». Una clave construida así no la
        ve nadie —ni el guardián de palabras ni un `grep`— y es la tercera vez que muerde."""
        import importlib                                             # noqa: PLC0415
        for code in ('es_ES', 'en_EN'):
            idioma = None
            mod = importlib.import_module('lib.i18n.lang.' + code)
            for valor in vars(mod).values():
                if isinstance(valor, dict) and 'save' in valor:
                    idioma = valor
                    break
            assert idioma is not None, code
            for pid in maps.ORDER:
                clave = maps.label_key(pid)
                assert clave in idioma, (code, pid, clave)

    def test_y_un_desconocido_no_inventa_un_nombre(self):
        """Enseñar una clave inexistente es enseñarla en crudo."""
        assert maps.label_key('lo-que-sea') == 'dcim_map_provider_off'

    def test_un_proveedor_que_no_existe_es_ninguno(self):
        """Una configuración con una palabra que nadie reconoce no puede acabar en un mapa
        adivinado."""
        assert maps.resolve({'dcim_map_provider': 'bing'})['tiles'] == ''

    def test_todos_los_del_desplegable_estan_en_la_tabla(self):
        """Ofrecer en la lista algo que no se sabe dibujar es una opción que apaga el mapa."""
        for pid in maps.ORDER:
            assert pid == maps.OFF or maps.known(pid), pid


class TestLoPropioSigueSiendoPosible:
    """Una lista cerrada sería una lista que hay que editar para usar el servidor de teselas de
    tu propia casa — y hay instalaciones que no salen a internet."""

    _MIA = 'https://mapas.interno.example/{z}/{x}/{y}.png'

    def test_la_plantilla_propia(self):
        r = maps.resolve({'dcim_map_provider': 'custom', 'dcim_map_tiles': self._MIA,
                          'dcim_map_attribution': 'Cartografía de la casa'})
        assert r['tiles'] == self._MIA
        assert r['attribution'] == 'Cartografía de la casa'

    def test_y_quien_la_escribio_antes_de_que_hubiera_lista_no_se_queda_sin_mapa(self):
        """El día que se añadió el desplegable, ninguna instalación tenía proveedor elegido. Si
        eso valiera «ninguno», el mapa se les apagaría a todas en una actualización, sin que
        nadie hubiera tocado su configuración."""
        r = maps.resolve({'dcim_map_tiles': self._MIA})
        assert r['provider'] == maps.CUSTOM
        assert r['tiles'] == self._MIA

    def test_pero_sin_plantilla_y_sin_proveedor_no_hay_mapa(self):
        assert maps.resolve({'dcim_map_tiles': '   '})['tiles'] == ''

    def test_elegir_un_proveedor_manda_sobre_la_plantilla_vieja(self):
        """Si no, cambiar de proveedor en la pantalla no haría nada y no habría forma de saber
        por qué."""
        r = maps.resolve({'dcim_map_provider': 'osm', 'dcim_map_tiles': self._MIA})
        assert 'openstreetmap' in r['tiles']


class TestLaPoliticaDeContenidoNecesitaElOrigen:
    """La mitad silenciosa: si el origen no está en la cabecera, el navegador bloquea cada
    tesela y **no dice nada en la página**. El mapa sale vacío exactamente igual que si no
    estuviera configurado."""

    def test_el_origen_y_no_la_direccion(self):
        """Una tesela es una de un millón de rutas que hay debajo."""
        assert maps.origin_of('https://tile.example.org/a/{z}/{x}/{y}.png') \
            == 'https://tile.example.org'

    def test_con_su_puerto_cuando_lo_lleva(self):
        """Un espejo interno casi siempre está en un puerto raro, y un origen sin puerto no es
        el mismo origen."""
        assert maps.origin_of('http://mapas:8080/{z}/{x}/{y}.png') == 'http://mapas:8080'

    def test_sin_mapa_no_se_abre_nada(self):
        """La propiedad que importa: una instalación sin mapa no le puede pedir una imagen a
        nadie, y su política queda exactamente como estaba."""
        assert maps.origins_for({}) == []
        assert maps.origins_for({'dcim_map_provider': ''}) == []

    def test_con_mapa_se_abren_todos_los_del_catalogo(self):
        """Y no sólo el elegido. La política viaja en la cabecera de cada página, así que con
        uno solo abierto cambiar de proveedor obligaba a recargar antes de que el mapa nuevo
        pudiera cargar — y mientras tanto no cargaba nada, en silencio."""
        abiertos = maps.origins_for({'dcim_map_provider': 'osm'})
        assert 'https://tile.openstreetmap.org' in abiertos
        assert 'https://basemaps.cartocdn.com' in abiertos
        assert 'https://tile.googleapis.com' in abiertos
        # Direcciones fijas, nunca un comodín: eso sí cambiaría la forma de lo que se permite.
        assert all(o.startswith('https://') and '*' not in o for o in abiertos), abiertos

    def test_y_el_propio_tambien_cuando_lo_hay(self):
        """Un espejo interno no está en la tabla, y sin él no cargaría ni el que se ha
        elegido."""
        abiertos = maps.origins_for({'dcim_map_provider': maps.CUSTOM,
                                     'dcim_map_tiles': 'https://mapas.interno/{z}/{x}/{y}.png'})
        assert 'https://mapas.interno' in abiertos

    def test_sin_repetir_ninguno(self):
        """Dos proveedores del mismo servidor —los dos Carto— son un origen, no dos."""
        abiertos = maps.origins_for({'dcim_map_provider': 'carto_light'})
        assert len(abiertos) == len(set(abiertos)), abiertos

    @pytest.mark.parametrize('mala', ['', '   ', 'no-es-una-url', 'ftp://x/{z}',
                                      '/interno/{z}/{x}/{y}.png', 'javascript:alert(1)'])
    def test_lo_que_no_se_puede_leer_no_abre_nada(self, mala):
        """Abrir un comodín porque una dirección venía rara sería exactamente lo contrario de lo
        que hace esta función."""
        assert maps.origin_of(mala) == ''


class TestGoogleVaPorSuApiYNoPorSuGuion:
    """Sus teselas no se pueden tener de otra forma sin ejecutar su código — y ejecutar su código
    le da la página entera, que es lo que este panel no hace con nadie."""

    def setup_method(self):
        gmaps.forget()

    def teardown_method(self):
        gmaps.forget()

    def _falso(self, respuesta, llamadas):
        class _R:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return json.dumps(respuesta).encode('utf-8')

        def _open(url, data, timeout):
            llamadas.append((url, json.loads(data.decode('utf-8'))))
            return _R()
        return _open

    def test_la_direccion_lleva_la_sesion_y_la_clave(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'SES-1',
                                         'expiry': str(int(time.time()) + 86400)}, llamadas))
        url = gmaps.tiles(maps.PROVIDERS[maps.GOOGLE]['tiles'], 'CLAVE')
        assert 'session=SES-1' in url and 'key=CLAVE' in url
        for hueco in ('{z}', '{x}', '{y}'):
            assert hueco in url, hueco
        # Y la sesión se pidió con la clave, no con la dirección de las teselas.
        assert llamadas and 'key=CLAVE' in llamadas[0][0]
        assert llamadas[0][1]['mapType'] == gmaps.MAP_TYPE

    def test_la_sesion_se_pide_una_vez_y_no_por_pestaña(self, monkeypatch):
        """Es lo que hace que esto lo mine el servidor: una sesión por persona que abre el panel
        serían cientos para un solo mapa."""
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'SES-1',
                                         'expiry': str(int(time.time()) + 86400)}, llamadas))
        for _ in range(5):
            gmaps.tiles(maps.PROVIDERS[maps.GOOGLE]['tiles'], 'CLAVE')
        assert len(llamadas) == 1

    def test_pero_cambiar_la_clave_tira_la_que_habia(self, monkeypatch):
        """Si no, el panel seguiría pidiendo teselas con la clave vieja hasta que caducara — y
        lo que se vería es que cambiar la clave «no hace nada» durante dos semanas."""
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'SES-1',
                                         'expiry': str(int(time.time()) + 86400)}, llamadas))
        gmaps.tiles(maps.PROVIDERS[maps.GOOGLE]['tiles'], 'UNA')
        gmaps.tiles(maps.PROVIDERS[maps.GOOGLE]['tiles'], 'OTRA')
        assert len(llamadas) == 2

    def test_y_una_caducada_tambien(self, monkeypatch):
        """Con margen: entre pedir la dirección y cargar la última tesela pasa un rato, y una
        sesión que caduca por el camino deja media pantalla sin dibujar."""
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'SES-1',
                                         'expiry': str(int(time.time()) + 60)}, llamadas))
        gmaps.tiles(maps.PROVIDERS[maps.GOOGLE]['tiles'], 'CLAVE')
        gmaps.tiles(maps.PROVIDERS[maps.GOOGLE]['tiles'], 'CLAVE')
        assert len(llamadas) == 2, 'una sesión a punto de caducar se da por buena'

    def test_sin_clave_no_se_llama_a_nadie(self, monkeypatch):
        llamadas = []
        monkeypatch.setattr(gmaps, '_open', self._falso({}, llamadas))
        with pytest.raises(gmaps.MapKeyError) as e:
            gmaps.session_for('   ')
        assert e.value.key == 'gmaps_err_nokey'
        assert not llamadas

    def test_una_respuesta_sin_sesion_es_un_error_con_nombre(self, monkeypatch):
        """Y no una dirección con el hueco sin rellenar, que daría sesenta imágenes rotas en vez
        de un mapa apagado."""
        monkeypatch.setattr(gmaps, '_open', self._falso({'error': {'code': 403}}, []))
        with pytest.raises(gmaps.MapKeyError) as e:
            gmaps.session_for('CLAVE')
        assert e.value.key == 'gmaps_err_session'
        # El detalle es lo que dijo el otro extremo, y por eso no se traduce.
        assert '403' in e.value.detail

    def test_y_si_no_contestan_tambien(self, monkeypatch):
        def _revienta(url, data, timeout):
            raise OSError('getaddrinfo failed')
        monkeypatch.setattr(gmaps, '_open', _revienta)
        with pytest.raises(gmaps.MapKeyError) as e:
            gmaps.session_for('CLAVE')
        assert e.value.key == 'gmaps_err_session'
        assert 'getaddrinfo' in e.value.detail

    def test_la_clave_no_se_guarda_para_saber_si_cambio(self, monkeypatch):
        """Se guarda su huella. Una credencial menos escrita en un sitio en el que nadie pensó
        que hubiera credenciales."""
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'SES-1',
                                         'expiry': str(int(time.time()) + 86400)}, llamadas))
        gmaps.tiles(maps.PROVIDERS[maps.GOOGLE]['tiles'], 'SECRETA')
        assert 'SECRETA' not in json.dumps(gmaps._CACHE)

    def test_las_teselas_se_piden_en_el_idioma_del_panel(self, monkeypatch):
        """Unas etiquetas en inglés dentro de un panel en castellano son un mapa que no se lee
        igual — y la región decide cómo se dibujan las fronteras en litigio, que no es un
        detalle estético. Ellos hablan `es-ES` y una región aparte; el panel dice `es_ES`."""
        assert gmaps.lang_of('es_ES') == ('es-ES', 'ES')
        assert gmaps.lang_of('en_EN') == ('en-EN', 'EN')
        # Sin idioma se cae al de último recurso, no a una cadena vacía que ellos rechazarían.
        assert gmaps.lang_of('') == (gmaps.LANG, gmaps.REGION)
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'S', 'expiry': str(int(time.time()) + 8000)},
                                        llamadas))
        gmaps.session_for('CLAVE', lang='es-ES', region='ES')
        assert llamadas[0][1]['language'] == 'es-ES'
        assert llamadas[0][1]['region'] == 'ES'

    def test_y_cambiar_el_idioma_tira_la_sesion(self, monkeypatch):
        """Si no, seguiría dando teselas en el idioma viejo hasta que caducara: cambiar el
        idioma del panel «no haría nada» durante dos semanas — el mismo fallo que ya se evitó
        con la clave."""
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'S', 'expiry': str(int(time.time()) + 8000)},
                                        llamadas))
        gmaps.session_for('CLAVE', lang='es-ES', region='ES')
        gmaps.session_for('CLAVE', lang='en-US', region='US')
        assert len(llamadas) == 2

    def test_se_le_pide_la_clase_de_mapa_que_se_ha_elegido(self, monkeypatch):
        """El callejero sirve para encontrar una nave en un polígono; para una antena en un
        monte, donde ningún callejero dibuja nada, la foto es lo único que reconoce el sitio."""
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'S', 'expiry': str(int(time.time()) + 8000)},
                                        llamadas))
        gmaps.session_for('CLAVE', map_type='satellite')
        assert llamadas[0][1]['mapType'] == 'satellite'

    def test_y_cambiarla_tira_la_sesion(self, monkeypatch):
        """Como con la clave y con el idioma: si no, seguiría dando callejero durante dos
        semanas y cambiarlo parecería no hacer nada."""
        llamadas = []
        monkeypatch.setattr(gmaps, '_open',
                            self._falso({'session': 'S', 'expiry': str(int(time.time()) + 8000)},
                                        llamadas))
        gmaps.session_for('CLAVE', map_type='roadmap')
        gmaps.session_for('CLAVE', map_type='satellite')
        assert len(llamadas) == 2

    def test_las_clases_que_se_ofrecen_son_las_que_el_entiende(self):
        """Ofrecer una que no exista es un desplegable que apaga el mapa al elegirla."""
        assert maps.GOOGLE_TYPES == ('roadmap', 'satellite', 'terrain')
        assert gmaps.MAP_TYPE in maps.GOOGLE_TYPES

    def test_su_plantilla_no_es_una_direccion_normal(self):
        """Los dos huecos de más son lo que hace que Google no pueda ser «una URL y ya», que es
        la pregunta que se hace todo el que la mira."""
        t = maps.PROVIDERS[maps.GOOGLE]['tiles']
        assert '{session}' in t and '{key}' in t
        assert maps.PROVIDERS[maps.GOOGLE].get('needs_key') is True

    def test_y_el_origen_sale_sin_hablar_con_ellos(self, monkeypatch):
        """La cabecera de seguridad se calcula en CADA respuesta: una llamada a Google por
        petición sería el panel entero atado a que ellos contesten."""
        def _nunca(*a, **k):
            raise AssertionError('ha llamado a Google para calcular la cabecera')
        monkeypatch.setattr(gmaps, '_open', _nunca)
        r = maps.resolve({'dcim_map_provider': maps.GOOGLE})
        assert maps.origin_of(r['tiles']) == 'https://tile.googleapis.com'
