#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las palabras del panel viven en los ficheros de idioma. **Todas.**

La regla ya estaba escrita —en `constants.py`, encima de `home_pages()`—: una página del CORE
apunta a una clave del catálogo del core, y una de un MÓDULO trae sus propios textos, porque
ningún texto del core puede nombrar un módulo. Lo que no había era quien la comprobara, y una
regla que sólo está escrita en un comentario se rompe copiando la línea de al lado: las vistas
de la sección de inventario llevaban ``label_i18n`` con el castellano y el inglés dentro del
`.py`, que es la convención de los módulos usada donde no toca.

Lo que eso cuesta no es estilo. Un texto dentro de un `.py` está **fuera del alcance de los
ficheros de idioma**: no se puede traducir a un tercer idioma sin tocar código, no sale en
ninguna revisión de traducciones, y el día que alguien cambie la palabra en `es_ES.py` la
pantalla seguirá diciendo la vieja sin que nada falle.

Dos guardas, una por cada forma de colarlo:

* un mapa ``{'es_ES': '…', 'en_EN': '…'}`` escrito a mano en el código del panel;
* una cadena con acentos castellanos fuera de comentarios y docstrings — si el panel está bien
  traducido, un acento en una cadena de código es texto que se le escapó a i18n.

Los MÓDULOS quedan fuera a propósito: `watchfuls/<m>/lang/` es su catálogo, y traer sus textos
consigo es justo lo que les permite viajar solos.
"""

from __future__ import annotations

import ast
import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
LIB = os.path.join(SRC, 'lib')
TPL = os.path.join(LIB, 'web_admin', 'templates')

#: Un mapa de idiomas escrito a mano. `'es_ES': '` con la comilla pegada es el mapa; sin ella
#: son las mil comparaciones legítimas contra el código de un idioma.
_MAPA = re.compile(r"""['"](?:es_ES|en_EN)['"]\s*:\s*['"][^'"]""")

#: Lo que delata al castellano en una cadena. El inglés no se puede distinguir de un
#: identificador, así que esta guarda encuentra la mitad de los casos — que es la mitad que de
#: verdad ocurre en un panel que se escribe en castellano.
_ACENTO = re.compile(r'[áéíóúÁÉÍÓÚñÑ¿¡«»]')

#: Lo que NO es una etiqueta aunque lo parezca, con su razón. Una lista de excepciones es una
#: deuda, así que cada una lleva escrito por qué no se traduce.
_PERDONADAS = {
    # Se ESCRIBE en filas de la base (`dc_brand`, `dc_type`) como el fabricante de lo básico que
    # trae el panel, y de ahí sale en una ficha como parte de un nombre: «Genérico Regleta 8».
    # Traducirlo cambiaría lo que ya está guardado según quién mire, que es lo contrario de un
    # dato. Si algún día se traduce, lo que se traduce es cómo se PINTA, no lo que se guarda.
    ('lib/core/dcim/basics.py', 'Genérico'),
}


def _ficheros(raiz, ext):
    for aqui, _dirs, ficheros in os.walk(raiz):
        if '__pycache__' in aqui:
            continue
        for f in sorted(ficheros):
            if f.endswith(ext):
                yield os.path.join(aqui, f)


def _rel(ruta):
    return os.path.relpath(ruta, SRC).replace(os.sep, '/')


def _sin_comentarios(s: str) -> str:
    """La plantilla sin nada de lo que no se pinta."""
    s = re.sub(r'\{#.*?#\}', '', s, flags=re.S)          # comentario de Jinja
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S)          # comentario de HTML
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)           # bloque de JS o CSS
    s = re.sub(r'^\s*//.*$', '', s, flags=re.M)           # línea de JS entera
    return re.sub(r'\s//[^\n\'"`]*$', '', s, flags=re.M)  # comentario al final de la línea


class TestNingunaPalabraDelPanelVivEnElCodigo:

    def test_el_core_no_escribe_mapas_de_idiomas(self):
        """`{'es_ES': 'Inventario', 'en_EN': 'Inventory'}` es la convención de un MÓDULO, que
        trae sus textos porque ningún texto del core puede nombrarlo. En el core, eso es un par
        de traducciones fuera del catálogo — y la que se quede vieja no lo va a decir nadie."""
        malos = []
        for ruta in _ficheros(LIB, '.py'):
            rel = _rel(ruta)
            if rel.startswith('lib/i18n/'):
                continue                     # el catálogo, que de eso vive
            try:
                arbol = ast.parse(io.open(ruta, encoding='utf-8').read())
            except SyntaxError:
                continue
            # Por el ÁRBOL y no por líneas: el formato de un perfil SNMP se explica en un
            # docstring con un mapa de ejemplo dentro, y una guarda que lea texto plano no
            # distingue lo que se ejecuta de lo que se cuenta.
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Dict):
                    continue
                for k, v in zip(nodo.keys, nodo.values):
                    if (isinstance(k, ast.Constant) and k.value in ('es_ES', 'en_EN')
                            and isinstance(v, ast.Constant) and isinstance(v.value, str)
                            and v.value):
                        malos.append(f'{rel}:{nodo.lineno}: {k.value} = {v.value[:40]!r}')
        assert not malos, 'texto traducido a mano dentro del código:\n' + '\n'.join(malos)

    def test_ni_deja_castellano_suelto_en_una_cadena(self):
        """Un acento en una cadena de código es, casi siempre, una palabra que tenía que estar
        en `es_ES.py`. Fuera de docstrings y comentarios: ahí es donde se explica, y esta base se
        explica en castellano a propósito."""
        malos = []
        for ruta in _ficheros(LIB, '.py'):
            rel = _rel(ruta)
            if rel.startswith('lib/i18n/'):
                continue
            try:
                arbol = ast.parse(io.open(ruta, encoding='utf-8').read())
            except SyntaxError:              # un fichero que ni se compila es otro problema
                continue
            docs = set()
            for nodo in ast.walk(arbol):
                if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    if ast.get_docstring(nodo, clean=False) is not None:
                        docs.add(id(nodo.body[0].value))
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
                    continue
                if id(nodo) in docs or not _ACENTO.search(nodo.value):
                    continue
                if (rel, nodo.value) in _PERDONADAS:
                    continue
                malos.append(f'{rel}:{nodo.lineno}: {nodo.value[:70]!r}')
        assert not malos, 'castellano escrito en el código:\n' + '\n'.join(malos)

    def test_ni_las_plantillas_pintan_palabras_sueltas(self):
        """Todo lo que se pinta pasa por `t()` o `tf()`. Un acento fuera de un comentario es una
        palabra que no pasó — y que en inglés se va a quedar en castellano."""
        malos = []
        for ruta in _ficheros(TPL, '.html'):
            texto = _sin_comentarios(io.open(ruta, encoding='utf-8-sig').read())
            for n, linea in enumerate(texto.splitlines(), 1):
                if _ACENTO.search(linea):
                    malos.append(f'{_rel(ruta)}:{n}: {linea.strip()[:90]}')
        assert not malos, 'palabras escritas en una plantilla:\n' + '\n'.join(malos)

    def test_y_la_guarda_mira_donde_hay_algo_que_mirar(self):
        """Guardar la guarda: con los `.py` o las plantillas mal contados, las tres de arriba
        pasarían sin haber abierto un fichero."""
        assert len(list(_ficheros(LIB, '.py'))) > 200
        assert len(list(_ficheros(TPL, '.html'))) > 100
        assert _MAPA.search("{'es_ES': 'Inventario'}")
        assert not _MAPA.search("if lang == 'es_ES':")
        assert _ACENTO.search('Catálogo') and not _ACENTO.search('Catalogue')
