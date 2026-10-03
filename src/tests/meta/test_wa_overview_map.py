#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La tarjeta de mapa: que sea del panel y no del inventario, y que haya UNA proyección.

Dos reglas, y las dos se rompen sin que nada falle:

**El panel de control dibuja mapas; no sabe de inventarios.** La tarjeta de mapa es una clase de
tarjeta, como el recuento y la tabla: se le dan cosas con latitud, longitud y un estado. En
cuanto una línea suya nombra al inventario —una palabra `dcim_…`, el identificador de su
widget—, el siguiente paquete que tenga cosas con coordenadas no puede usarla sin editar el
núcleo, que es exactamente lo que este proyecto evita en todas partes. Ya pasó al escribirla:
decía el estado «sin vigilar» con la palabra del inventario.

**Y una sola proyección para todo el panel.** Dos copias de la aritmética de Web Mercator son
dos mapas que pueden discrepar sobre dónde está el mismo edificio, y la discrepancia no daría
ningún error: daría una chincheta en la calle de al lado. Un mapa que sitúa mal por poco es peor
que uno que no sitúa — el primero se cree.
"""

from __future__ import annotations

import glob
import os
import re

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials')
WIDGETS = os.path.join(TPL, 'overview', '_widgets.html')
GEO = os.path.join(TPL, 'core', '_geo.html')


class TestElPanelDibujaMapasYNoSabeDeInventarios:

    def _funciones(self):
        """TODAS las del mapa, buscadas por su nombre y no escritas a mano.

        La lista escrita a mano ya falló: se puso con cinco funciones, la ficha del punto se
        añadió después y entró diciendo «tres armarios en dos salas» con la clave del
        inventario. Un guardián que hay que acordarse de ampliar es uno que se queda corto el
        día que hace falta."""
        return sorted(set(re.findall(r'function (_dwMap\w+)\(', _read(WIDGETS)))
                      | {'_dwRenderMap'})

    def test_hay_funciones_de_mapa_que_mirar(self):
        assert len(self._funciones()) >= 6, self._funciones()

    def test_el_dibujante_no_nombra_a_quien_le_trae_los_puntos(self):
        for nombre in self._funciones():
            src = _strip_comments(_fn(_read(WIDGETS), nombre))
            assert 'dcim' not in src.lower(), f'{nombre} nombra al inventario'

    def test_y_las_palabras_que_usa_son_las_del_panel(self):
        """Un estado se dice igual en toda la aplicación. Con las claves de una sección, la
        tarjeta de otro paquete saldría hablando de armarios."""
        src = _fn(_read(WIDGETS), '_dwMapWord')
        claves = set(re.findall(r"'([a-z_0-9]+)'", src))
        assert claves == {'status_error', 'status_warning', 'status_ok', 'status_unwatched'}, \
            claves

    def test_la_clave_de_cada_estado_se_puede_buscar(self):
        """Escrita entera y no compuesta (`'status_' + state`): una clave construida así no la
        ve nadie —ni el guardián de palabras ni un `grep`— y así es como cuatro llegaron a la
        pantalla sin existir en ningún idioma."""
        src = _strip_comments(_fn(_read(WIDGETS), '_dwMapWord'))
        assert "'status_" in src
        assert "'status_' +" not in src and "+ state" not in src


class TestCambiarDeMapaPideRecargar:
    """La política de contenido viaja en la cabecera de CADA página: la que está abierta lleva
    la que había al abrirla. Así que al cambiar de proveedor el ajuste se guarda, el servidor ya
    sirve el nuevo, y el navegador sigue bloqueando sus teselas **en silencio**.

    Se veía como «he guardado y el mapa no carga hasta que pulso F5», sin nada que lo explicara.
    Ahora se dice y se ofrece el botón."""

    def _js(self, *partes):
        return _read(os.path.join(TPL, *partes))

    def test_lo_decide_el_servidor_y_no_una_lista_en_la_pantalla(self):
        """Quien sabe con qué política se sirvió esta página es él. Una regla escrita aquí sería
        una copia que se desvía el día que cambie la de allí — y desviarse aquí significa pedir
        una recarga que no hace falta, o no pedir la que sí."""
        src = _strip_comments(self._js('actions', '_save.html'))
        assert 'reload_required' in src
        assert '_askReload()' in src
        assert 'RELOAD_REQUIRED_FIELDS' not in src, 'vuelve a decidirlo la pantalla'

    def test_y_eso_no_es_pedir_un_reinicio(self):
        """El ajuste ya está en vigor en el servidor: lo que se quedó viejo es la página, y
        confundir las dos cosas manda a alguien a reiniciar un servicio para nada."""
        src = _strip_comments(_fn(self._js('core', '_polling.html'), '_askReload'))
        assert 'location.reload' in src
        assert 'restart' not in src.lower()


class TestNingunaClaveSeCompone:
    """Tercera vez que muerde. Una clave construida con un identificador —`'algo_' + id`— no la
    ve nadie: ni el guardián de palabras ni un `grep`. Salió a la pantalla «sin vigilar» con la
    palabra del inventario, salió «dcim_map_provider_ign_pnoa» en medio de una frase, y las dos
    veces la función que la componía parecía perfectamente razonable."""

    def test_el_cuadro_de_probar_el_mapa_pregunta_el_nombre(self):
        """El rótulo de un proveedor lo dice el catálogo, que es quien lo tiene."""
        src = _strip_comments(_read(os.path.join(TPL, 'cfg', '_maps.html')))
        assert "'dcim_map_provider_' +" not in src, 'vuelve a componer la clave del proveedor'
        assert 'saved_label_key' in src, 'no usa el nombre que le manda el servidor'

    def test_y_el_catalogo_lo_sabe_de_todos(self):
        import sys                                                   # noqa: PLC0415
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        from lib.maps import catalog as maps                         # noqa: PLC0415
        for pid, datos in maps.PROVIDERS.items():
            assert datos.get('label_key'), pid
            assert maps.label_key(pid) == datos['label_key'], pid


class TestUnaSolaProyeccion:

    def _plantillas(self):
        return glob.glob(os.path.join(TPL, '**', '*.html'), recursive=True)

    def test_la_aritmetica_de_mercator_esta_escrita_una_vez(self):
        """El corte en la latitud 85,05 es la huella de una proyección de Web Mercator: donde
        aparece, alguien está proyectando. Si aparece dos veces, hay dos."""
        con = [p for p in self._plantillas() if '85.05112878' in _read(p)]
        assert [os.path.basename(p) for p in con] == ['_geo.html'], con

    def test_y_el_mundo_se_mide_en_un_sitio(self):
        con = [p for p in self._plantillas()
               if re.search(r'256 \* Math\.pow\(2,', _read(p))]
        assert [os.path.basename(p) for p in con] == ['_geo.html'], con

    def test_el_mapa_de_la_seccion_usa_la_misma(self):
        """Es el que ya existía, y el que se puede quedar atrás sin que nadie lo note."""
        src = _read(os.path.join(TPL, 'dcim', '_sitemap.html'))
        assert 'ssGeoProject(' in src and 'ssGeoUnproject(' in src
        assert 'ssGeoTiles(' in src

    def test_y_la_tarjeta_del_panel_tambien(self):
        src = _read(WIDGETS)
        assert 'ssGeoProject(' in src and 'ssGeoTiles(' in src

    def test_el_cero_cero_no_es_una_coordenada(self):
        """Es un punto del golfo de Guinea donde no hay ningún datacenter, y es lo que deja un
        formulario cuyos dos campos se guardaron vacíos. Una chincheta ahí no dice «no lo sé»:
        dice una mentira concreta. Se decide en un sitio, y los dos mapas preguntan."""
        src = _strip_comments(_fn(_read(GEO), 'ssGeoHas'))
        assert '(lat || lon)' in src
        for p in (os.path.join(TPL, 'dcim', '_sitemap.html'), WIDGETS):
            assert 'ssGeoHas(' in _read(p), p


class TestLaTarjetaPideSusDatosDondeDijoQueLosPediria:

    def _widget(self):
        import sys                                                   # noqa: PLC0415
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        from lib.core.dcim.manifest import OVERVIEW_WIDGETS          # noqa: PLC0415
        return OVERVIEW_WIDGETS[0]

    def test_la_direccion_de_los_datos_lleva_su_identificador(self):
        """Una dirección que no corresponde con el identificador deja una tarjeta girando para
        siempre: la ruta contesta 404 y el dibujante se queda con la rueda puesta, que es un
        fallo que parece lentitud."""
        w = self._widget()
        assert w['view']['data_url'].endswith('/' + w['id'])

    def test_y_el_servidor_sabe_servirla(self):
        """Declarar el proveedor con un nombre que el descubridor no mira es una tarjeta que
        nunca recibe nada — y no da ningún error, porque un 404 se traga en silencio."""
        import sys                                                   # noqa: PLC0415
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        from lib.core.overview.discovery import (                    # noqa: PLC0415
            discover_widget_content)
        assert self._widget()['id'] in discover_widget_content()

    def test_y_se_pide_el_permiso_del_inventario(self):
        """Dónde están los datacenters de la casa no es una tarjeta pública del panel."""
        assert self._widget()['perms']['any'] == ['dcim_view']


class TestPulsarElMapaNoEsPulsarLaTarjeta:
    """Una tarjeta del panel de control lleva a su sección al pulsarla. Un mapa se maneja con el
    ratón, así que ahí una pulsación es el final de un arrastre o la segunda de un doble clic —
    y navegar a otra pestaña en medio de eso es la tarjeta quitándole el mapa de las manos a
    quien lo estaba moviendo.

    Por la lista de lo que NO navega, que es genérica: el mapa no se nombra en ningún sitio, se
    reconoce por el mismo atributo con el que se dibuja."""

    def test_lo_que_se_maneja_con_el_raton_no_navega(self):
        src = _fn(_read(os.path.join(TPL, 'overview', '_layout.html')), '_dwOnGridClick')
        assert '[data-dwmap]' in src, 'un arrastre sobre el mapa cambia de pestaña'

    def test_y_el_mapa_se_dibuja_con_ese_atributo(self):
        """Los dos lados de la misma frase: si el dibujo dejara de ponerlo, la lista de arriba
        seguiría diciendo la verdad y no protegería nada."""
        assert 'data-dwmap=' in _fn(_read(WIDGETS), '_dwRenderMap')


class TestPulsarSeDecideAlSoltar:
    """Y no en un `onclick` de la chincheta, porque no llega: el lienzo captura el puntero para
    poder arrastrar fuera del dibujo, y con la captura puesta el navegador dispara el `click` en
    el `<svg>`. La chincheta no lo ve pasar.

    Se escribió con `onclick` y así estuvo: la prueba que llamaba a la función pasaba, y en la
    pantalla pulsar un punto no hacía nada. Reportado desde la pantalla."""

    def test_la_chincheta_no_lleva_un_onclick(self):
        src = _fn(_read(WIDGETS), '_dwMapPin')
        assert 'onclick=' not in src, 'un manejador que la captura del puntero no deja llegar'

    def test_y_el_dibujo_deja_saber_de_quien_es_cada_punto(self):
        """Los dos lados de la misma frase: quien decide al soltar pregunta por `data-site`, y
        si el dibujo dejara de ponerlo no habría a qué sede ir."""
        assert 'data-site=' in _fn(_read(WIDGETS), '_dwMapPin')
        assert "closest('g[data-site]')" in _fn(_read(WIDGETS), '_dwMapDown')

    def test_una_pulsacion_que_viajo_no_es_una_pulsacion(self):
        """Con arrastrar y pulsar en el mismo botón, acabar en otra pantalla por haber movido el
        mapa es perder lo que se estaba mirando."""
        src = _strip_comments(_fn(_read(WIDGETS), '_dwMapUp'))
        assert 'press.moved' in src


class TestElZoomEsElDelPanelYNoUnoNuevo:
    """Dos formas de mover dos mapas del mismo panel son dos que aprender — y la segunda es la
    que no tiene los arreglos que la primera fue acumulando."""

    def test_el_mapa_del_panel_usa_el_lienzo_compartido(self):
        src = _read(WIDGETS)
        for fn in ('ssCanvasAttrs(', 'ssCanvasWheel(', 'ssCanvasPanStart(', 'ssCanvasFit('):
            assert fn in src, fn

    def test_y_dice_cuanto_se_puede_acercar_en_vez_de_conformarse(self):
        """El tope de fábrica del lienzo es el de un plano de sala. Desde media península, ocho
        veces no enseña una calle."""
        src = _strip_comments(_fn(_read(WIDGETS), '_dwRenderMap'))
        assert 'data-zoom-in=' in src
