#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Una tarjeta que crece al señalarla tiene que seguir cabiendo en la pantalla.

El panel de control agranda un poco la tarjeta bajo el cursor. Con un `scale` en tanto por
ciento eso es un crecimiento **que depende de lo ancha que sea la tarjeta**: una de tres
columnas gana doce píxeles y una que ocupa la rejilla entera gana sesenta, treinta de ellos por
cada lado y fuera de la ventana — donde no hay desplazamiento lateral con el que ir a buscarlos.

Ya se supo de las tarjetas de módulo, que son anchas, y se arregló **sólo para ellas**: se
añadió una segunda regla con crecimiento fijo y la del núcleo se quedó como estaba. El día que
una tarjeta del núcleo también fue ancha —el mapa de sedes— volvió el mismo fallo, reportado
otra vez desde la pantalla. Así que lo que se comprueba aquí no es que el mapa esté arreglado:
es que **no queda ninguna regla que crezca por tanto por ciento**, que es la forma de que no
vuelva con la siguiente tarjeta ancha.

Y la otra mitad: **lo que se maneja no crece**. Una tabla se ordena y se desplaza; un mapa se
arrastra y se acerca. Una tarjeta que crece bajo el cursor de quien iba a agarrarla es la
tarjeta quitándole de las manos lo que estaba a punto de coger.
"""

import os
import re

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')
LAYOUT = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'overview',
                      '_layout.html')


def _reglas(css: str) -> list:
    """Las reglas del panel de control que transforman algo al señalarlo: `(selector, cuerpo)`."""
    sin = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    fuera = []
    for sel, cuerpo in re.findall(r'([^{}]+)\{([^{}]*)\}', sin):
        sel = ' '.join(sel.split())
        if 'dashboard-grid' in sel and ':hover' in sel and 'transform' in cuerpo:
            fuera.append((sel, cuerpo))
    return fuera


class TestElCrecimientoEsDePixelesYNoDeTantoPorCiento:
    """Lo uno cabe siempre; lo otro cabe hasta que alguien pone una tarjeta ancha."""

    def test_ninguna_regla_crece_por_tanto_por_ciento(self):
        """La guarda de verdad. Arreglar el mapa habría sido añadir una tercera regla, y la
        cuarta tarjeta ancha se habría vuelto a salir."""
        for sel, cuerpo in _reglas(_read(CSS)):
            for escala in re.findall(r'transform:\s*scale\(([^)]*)\)', cuerpo):
                if 'scale(.95)' in cuerpo.replace(' ', '') and 'not(:hover)' in sel:
                    continue                      # las vecinas ENCOGEN, y encoger siempre cabe
                assert '--dw-pop' in escala, (sel, escala)

    def test_y_hay_una_sola_regla_que_hace_crecer(self):
        """Dos reglas son dos ideas de cuánto crece una tarjeta, y la que se olvide de
        actualizar es la que se sale de la pantalla."""
        crecen = [sel for sel, cuerpo in _reglas(_read(CSS)) if '--dw-pop' in cuerpo]
        assert len(crecen) == 1, crecen

    def test_el_crecimiento_esta_acotado_y_busca_el_lado_con_sitio(self):
        js = _strip_comments(_fn(_read(LAYOUT), '_dwOnGridHover'))
        assert 'Math.min(1.04' in js, 'sin tope, una tarjeta estrecha daría un salto'
        assert 'clientWidth' in js and 'transformOrigin' in js


class TestLoQueSeManejaNoCrece:
    """Una tabla se ordena, un mapa se arrastra. Que la tarjeta crezca bajo el cursor de quien
    iba a agarrarla es quitarle de las manos lo que estaba a punto de coger."""

    def test_ni_una_tabla_ni_un_mapa(self):
        for sel, _ in _reglas(_read(CSS)):
            assert ':not(:has(table))' in sel.replace(' ', ''), sel
            assert ':not(:has([data-dwmap]))' in sel.replace(' ', ''), sel

    def test_y_quien_calcula_el_crecimiento_deja_fuera_a_los_mismos(self):
        """Los dos lados de la misma frase. Si el guion midiera una tarjeta que la hoja de
        estilo no hace crecer —o al revés— habría una que crece con el valor de reserva, que es
        el que no mira dónde hay sitio."""
        js = _strip_comments(_fn(_read(LAYOUT), '_dwOnGridHover'))
        assert "'table'" in js and 'data-dwmap' in js, js

    def test_pero_alcanza_a_todas_las_demas(self):
        """Y no sólo a las de módulo, que es lo que dejaba a las del núcleo con el tanto por
        ciento."""
        js = _strip_comments(_fn(_read(LAYOUT), '_dwOnGridHover'))
        assert "closest('.dw-module')" not in js, 'vuelve a mirar sólo las de módulo'
        assert "closest('.dw" in js
