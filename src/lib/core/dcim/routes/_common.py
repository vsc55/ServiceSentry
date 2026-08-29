#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que usan varias áreas y no depende de ninguna: dos funciones y un tope.

Aparte del contexto porque no necesitan `app` ni `wa`: son cálculo puro, y meterlas en algo
que hay que construir obligaría a construirlo para usarlas.
"""

from __future__ import annotations


def _num(v) -> float:
    """Un número de un fichero que escribió cualquiera, o 0.

    Un plano importado viene de fuera: puede traer `null`, un texto, una lista. Que
    reviente la importación entera por una coordenada mal escrita convierte un fichero
    casi bueno en ninguno, y dejar pasar el texto guarda una posición que ningún dibujo
    sabe pintar."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _without(data: dict, keys) -> dict:
    """*data* without the columns only this module may set.

    A generic writer that accepts every column is right until one column stops being a
    fact somebody types and becomes a name the panel minted. Then it has to be taken off
    the payload, and here rather than in each route: the point of writing the CRUD once
    is that the rule is written once too."""
    drop = set(keys or ())
    return {k: v for k, v in (data or {}).items() if k not in drop}


#: Cuántos identificadores se admiten en una petición de exportación. Un catálogo entero no se
#: lleva así —para eso está volver a importar la biblioteca— y el tope evita que una URL
#: escrita a mano pida ocho mil filas de una vez.
_EXPORT_MAX = 500
