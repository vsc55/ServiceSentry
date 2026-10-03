#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo mínimo para dibujar un armario sin pedirle nada a nadie.

La biblioteca de NetBox son ocho mil modelos y una conexión a internet. Es lo correcto para quien
tiene equipos de marca y quiere sus fotos y sus puertos exactos. No sirve para el caso de la
primera tarde: alguien acaba de instalar el panel, tiene un armario delante, y necesita colocar un
switch, un panel de parcheo y una bandeja para ver el dibujo salir. Ahí no hace falta la ficha del
fabricante — hace falta **una caja de 1U que se llame algo**. Y hace falta poder decir con qué
sale una máquina sin dar de alta antes «Windows 11 Pro» a mano.

Y hay salas sin salida a internet donde eso es lo único que va a haber nunca.

**Está en un JSON, no en el código** (`data/basics.json`). Son datos: los tamaños de armario que
se fabrican, las formas que se repiten en cualquier sala, las plataformas que todo el mundo
teclea. Añadir «Ubuntu 28.04 LTS» o el armario de 45U no puede ser publicar una versión, y quien
sabe qué falta casi nunca es quien toca el código. Este módulo solo lo lee y rellena lo que se
repite —`Genérico`, el slug, el árbol— para que el fichero diga lo que distingue a cada uno y no
diez veces lo mismo.

**Escritos aquí y no copiados de la biblioteca.** Copiar catorce ficheros CC0 sería empezar a
mantener el catálogo de otro dentro de este repositorio: el día que corrijan un fondo, la copia
se queda con el valor viejo y nadie se entera. Estos son genéricos —"switch 1U de 24 puertos"— y
no dicen ser ningún modelo concreto, que es justo lo que se necesita para dibujar.

Nada aquí tiene imagen. Un genérico con foto sería la foto de un dispositivo que no es ese.

Las plataformas traen **las fechas que el fabricante publica**, y solo esas. Donde no hay una
sola fecha —el canal anual de Windows marca una por versión, y DSM una por modelo y no por
versión— no se pone ninguna y la fila dice por qué: una fecha que se inventa el panel es una
fecha que alguien va a creerse.

Y sus textos **hablan los dos idiomas**: donde hace falta traducir, el fichero pone
``{"es_ES": …, "en_EN": …}`` en vez de una cadena. Se elige idioma al sembrar y no al pintar,
porque lo que sale de aquí se **copia** a una fila que sobrevive a la sesión que la escribió.
"""

from __future__ import annotations

import json
import os
import re

from lib.i18n import DEFAULT_LANG

#: La etiqueta con la que entran. Propia, para que reimportar la biblioteca no se los lleve por
#: delante ni al revés: son dos orígenes y `replace` trabaja por origen.
SOURCE = 'core'

#: El fichero. Al lado del de perfiles y por la misma razón: es dato, se revisa en un commit y lo
#: reemplaza cada actualización.
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'basics.json')

#: Cómo se llama el fabricante de todo lo de aquí. No es una marca: es la ausencia de una, dicha
#: con una palabra para que la rejilla de marcas no tenga un hueco sin nombre.
MAKER = 'Genérico'

_CACHE: dict | None = None
#: Cómo estaba el fichero cuando se leyó: `(mtime, tamaño)`.
_SEEN: tuple = ()


def _doc() -> dict:
    """El fichero, releído **cuando cambia**.

    En memoria mientras no cambie, porque se lee entero por importación y son cuarenta filas.
    Pero releído cuando sí: este fichero se edita para añadir una plataforma o un armario, que
    es justo para lo que se sacó del código, y guardarlo para siempre en memoria convertiría
    «editar un JSON» en «editar un JSON y reiniciar el panel» — con la trampa de que lo segundo
    no está escrito en ninguna parte y quien edite creerá que no funcionó.

    Por fecha y tamaño y no por contenido: es un `stat` por importación contra leer y analizar
    el fichero cada vez. Dos ediciones en el mismo segundo que dejen el fichero del mismo tamaño
    se confundirían, y eso es un fichero que se escribe a mano.

    Uno roto **no tumba la sección**: salen cero básicos y el botón no trae nada, que es una
    pantalla más pobre y no una pantalla que no abre. Con el catálogo entero detrás, romper la
    lista de genéricos no puede impedir mirar un modelo.
    """
    global _CACHE, _SEEN                        # noqa: PLW0603
    try:
        st = os.stat(FILE)
        firma = (st.st_mtime, st.st_size)
    except OSError:
        firma = ()
    if _CACHE is None or firma != _SEEN:
        try:
            with open(FILE, encoding='utf-8') as fh:
                _CACHE = json.load(fh)
        except Exception:                       # pylint: disable=broad-except
            _CACHE = {}
        if not isinstance(_CACHE, dict):
            _CACHE = {}
        _SEEN = firma
    return _CACHE


def _text(v, lang: str = '') -> str:
    """Un texto del fichero, en el idioma que se pida.

    Puede venir como cadena —lo que no hace falta traducir, un nombre propio— o como
    ``{'es_ES': …, 'en_EN': …}``. Lo de aquí se **copia** a una fila de la base de datos y
    sobrevive a la sesión que la escribió, así que no se puede traducir al pintarlo: hay que
    elegir un idioma al sembrar, y el que corresponde es el de quien pulsó el botón.

    Sin ese idioma se cae al de por defecto, y sin él al primero que haya. Un texto es peor en
    otro idioma y mucho peor si no está.
    """
    if isinstance(v, dict):
        for clave in (str(lang or ''), DEFAULT_LANG):
            if v.get(clave):
                return str(v[clave])
        for valor in v.values():
            if valor:
                return str(valor)
        return ''
    return str(v or '')


#: Lo que no vale en un slug. Todo lo que no sea letra, número o guion: un `(` en un slug es un
#: carácter que hay que escapar en cada sitio por el que pase, y lo que se quiere de un slug es
#: justo no tener que pensar en eso.
_NO_SLUG = re.compile(r'[^a-z0-9]+')


def _slug(prefijo: str, model: str) -> str:
    return prefijo + _NO_SLUG.sub('-', str(model).lower()).strip('-')


def _rack(d: dict, lang: str = '') -> dict:
    """Un armario genérico, con las medidas que de verdad tienen los de ese tamaño.

    Las medidas no son inventadas: son las de los tamaños que se fabrican, y sirven para lo que
    un plano de sala pregunta —si cabe donde se quiere poner— sin obligar a buscar la ficha del
    que uno tenga.
    """
    model = _text(d.get('model'), lang)
    # El slug, del nombre en el idioma de por defecto y no del traducido: es la identidad de la
    # fila, y una que cambia con el idioma de quien pulsó el botón no es una identidad.
    return {'manufacturer': MAKER, 'model': model,
            'slug': _slug('generic-rack-', _text(d.get('model'), DEFAULT_LANG)),
            'u_tenths': int(round(float(d.get('u') or 0) * 10)),
            'full_depth': 1, 'is_powered': 0,
            'ports': {}, '_tree': 'rack-types',
            'extra': {'form_factor': '4-post-cabinet', 'width': 19, 'starting_unit': 1,
                      'outer_width': d.get('width'), 'outer_depth': d.get('depth'),
                      'outer_height': d.get('height'), 'outer_unit': 'mm'}}


def _dev(d: dict, lang: str = '') -> dict:
    """Un dispositivo genérico.

    Los puertos son lo que hace que la pantalla acierte su papel: tomas sin interfaces es una
    regleta, puertos por las dos caras y sin alimentación es un panel de parcheo, bahías de
    dispositivo es un chasis. El rol no se guarda —el catálogo no tiene esa columna, y con razón:
    lo decide quien coloca— pero SÍ se deduce, y por eso los genéricos traen sus puertos. Una
    caja sin ellos saldría sin sugerencia y habría que elegirle el papel a mano cada vez.

    Y donde la regla no puede acertar, la fila lo dice: un router y un cortafuegos tienen las
    mismas señales que un servidor pequeño —cuatro interfaces y corriente—, pero estos son
    NUESTROS y aquí sí se sabe lo que son.
    """
    model = _text(d.get('model'), lang)
    row = {'manufacturer': MAKER, 'model': model,
           'slug': _slug('generic-', _text(d.get('model'), DEFAULT_LANG)),
           'u_tenths': int(round(float(d.get('u') or 0) * 10)),
           'full_depth': 0 if d.get('full_depth') is False else 1,
           'part_number': '', 'airflow': '', 'subdevice': '',
           'is_powered': 0 if d.get('powered') is False else 1,
           'ports': d.get('ports') or {}, '_tree': 'device-types'}
    if d.get('kind'):
        row['kind'] = str(d['kind'])
    return row


def _mod(d: dict, lang: str = '') -> dict:
    """Un módulo genérico: lo que se mete en una bahía y lo que hay que reponer."""
    row = {'manufacturer': MAKER, 'model': _text(d.get('model'), lang),
           'slug': str(d.get('slug')
                       or _slug('generic-', _text(d.get('model'), DEFAULT_LANG))),
           'u_tenths': 0, 'ports': {}, '_tree': 'module-types', 'is_powered': 0}
    if d.get('kind'):
        row['kind'] = str(d['kind'])
    return row


def rows(lang: str = ''):
    """Los básicos del catálogo, listos para `CatalogStore.replace`.

    Una función y no una constante: quien los importe recibe copias suyas, y `replace` escribe
    sobre lo que le pasan —añade `uid`, `source`, la fecha— así que devolver siempre la misma
    lista sería dejar que la primera importación ensuciara la segunda.
    """
    doc = _doc()
    return ([_rack(r, lang) for r in (doc.get('racks') or ())]
            + [_dev(r, lang) for r in (doc.get('devices') or ())]
            + [_mod(r, lang) for r in (doc.get('modules') or ())])


def platforms(lang: str = ''):
    """Las plataformas básicas, listas para dar de alta. Copias, por lo mismo que `rows`.

    Con la marca donde la hay: Windows es de Microsoft y Ubuntu de Canonical; Debian no es de
    nadie que salga en una factura, y obligar a rellenarlo sería obligar a inventárselo.

    Y con **edición**, que no es un adorno: una `Enterprise LTSC` y una `Pro` no se actualizan
    igual ni se acaban el mismo día, así que son dos plataformas y no una con un matiz.
    """
    fuera = []
    for p in (_doc().get('platforms') or ()):
        if not p.get('name'):
            continue
        fila = dict(p)
        # La nota se copia a la ficha y sobrevive a la sesión: se elige idioma aquí, no al
        # pintarla. El nombre no se traduce — «Windows 11 Pro» se llama igual en los dos.
        fila['notes'] = _text(p.get('notes'), lang)
        fuera.append(fila)
    return fuera


def count() -> int:
    """Cuántos MODELOS son. Las plataformas no cuentan aquí: van a otra tabla y por otro
    camino —se añaden, no reemplazan— y sumarlas haría que este número dejara de ser lo que
    `dc_type` tiene de esta fuente, que es lo único que se compara contra él."""
    return len(rows())


def platform_count() -> int:
    """Cuántas plataformas trae."""
    return len(platforms())
