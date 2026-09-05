#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Que cada conector tenga una cara, y que la cara que nombra exista.

Un `<use href="#cx-loquesea">` que apunta a un símbolo que no está **no da ningún error**: deja
un hueco donde los de al lado tienen dibujo, y eso se lee como que a ese conector le falta algo.
El navegador no protesta, el servidor tampoco, y la única forma de enterarse es mirar la pantalla
justo en la fila que se rompió.

Son dos ficheros que tienen que decir lo mismo —el documento nombra formas y el `<svg>` las
dibuja— y nada los ata salvo esto. Un dibujo que sobra tampoco es gratis: son bytes en cada
página y un símbolo que nadie sabe si hace falta.
"""

from __future__ import annotations

import json
import os
import re
import sys

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

DOC = os.path.join(SRC, 'lib', 'core', 'dcim', 'data', 'connectors.json')
SPRITE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'dcim',
                      '_conn_shapes.html')
PANE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'dcim', '_pane.html')


def _conectores() -> list:
    with open(DOC, encoding='utf-8') as fh:
        return json.load(fh).get('connectors') or []


def _dibujadas() -> set:
    with open(SPRITE, encoding='utf-8') as fh:
        return set(re.findall(r'symbol id="cx-([a-z0-9-]+)"', fh.read()))


class TestCadaConectorTieneCara:

    def test_todos_nombran_una_forma(self):
        """Sin `shape` el conector sale sin dibujo mientras los de al lado lo tienen, que se lee
        como que a ese le falta algo — y lo que falta es una línea del documento."""
        sin = [c['id'] for c in _conectores() if not str(c.get('shape') or '').strip()]
        assert not sin, f'conectores sin forma: {sin}'

    def test_la_forma_que_nombran_esta_dibujada(self):
        """El fallo que esto existe para cazar: un `<use>` a un símbolo que no está no da ningún
        error, deja un hueco."""
        hay = _dibujadas()
        faltan = sorted({str(c.get('shape')) for c in _conectores()} - hay)
        assert not faltan, f'formas nombradas y no dibujadas: {faltan}'

    def test_no_sobran_dibujos(self):
        """Un símbolo que nadie usa son bytes en cada página y una duda: nadie sabe si hace falta
        o si se dejó de usar por un error."""
        usa = {str(c.get('shape')) for c in _conectores()}
        sobran = sorted(_dibujadas() - usa)
        assert not sobran, f'formas dibujadas y sin usar: {sobran}'

    def test_las_que_mas_se_confunden_no_comparten_cara(self):
        """Una C13 y una C19 se distinguen en un carácter y son dos cosas —diez amperios y
        veinte—: si además compartieran dibujo, el dibujo no serviría para lo único que se le
        pide. Lo mismo con la entrada y la salida de cada pareja."""
        por_id = {c['id']: c.get('shape') for c in _conectores()}
        for a, b in (('iec-60320-c13', 'iec-60320-c19'),
                     ('iec-60320-c14', 'iec-60320-c20'),
                     ('iec-60320-c13', 'iec-60320-c14'),
                     ('usb-a', 'usb-c'),
                     ('displayport', 'hdmi'),
                     ('lc', 'sc')):
            assert por_id[a] != por_id[b], f'{a} y {b} se dibujan igual'


class TestElSpriteLlegaALaPagina:

    def test_se_incrusta_en_la_seccion(self):
        """`<use>` contra otro documento no lo soportan todos los navegadores: un icono que sale
        en Firefox y no en Chrome es peor que no tenerlo. Así que va dentro de la página."""
        with open(PANE, encoding='utf-8') as fh:
            assert 'partials/dcim/_conn_shapes.html' in fh.read()

    def test_los_dibujos_no_traen_color_propio(self):
        """En `currentColor` y sin relleno, o el tema oscuro enseña líneas negras sobre negro.
        El único relleno permitido es el que dice `currentColor` a la cara."""
        with open(SPRITE, encoding='utf-8') as fh:
            texto = fh.read()
        malos = [f for f in re.findall(r'fill="([^"]+)"', texto)
                 if f not in ('none', 'currentColor')]
        assert not malos, f'rellenos con color propio: {malos}'
        assert 'stroke="#' not in texto and 'fill="#' not in texto
