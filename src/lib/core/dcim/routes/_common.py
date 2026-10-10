#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que usan varias áreas y no depende de ninguna: dos funciones y un tope.

Aparte del contexto porque no necesitan `app` ni `wa`: son cálculo puro, y meterlas en algo
que hay que construir obligaría a construirlo para usarlas.
"""

from __future__ import annotations

import math


def _num(v) -> float:
    """Un número de un fichero que escribió cualquiera, o 0.

    Un plano importado viene de fuera: puede traer `null`, un texto, una lista. Que
    reviente la importación entera por una coordenada mal escrita convierte un fichero
    casi bueno en ninguno, y dejar pasar el texto guarda una posición que ningún dibujo
    sabe pintar.

    Non-finite values (`nan`, `inf`) are 0 too: `float()` accepts them, and the `int()` every
    caller then applies raises on both — a 500 from a number that was never a number."""
    try:
        out = float(v)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


#: Columns no request may write: the row's identity and its audit stamp. `Rows.create` honours a
#: `uid` in the payload, so a create that passed the request through let the CLIENT choose the
#: identifier — and choosing an existing one was a 500 from the primary key.
SERVER_COLS = ('uid', 'created_at', 'created_by', 'updated_at', 'updated_by',
               # El estado de demostración de un equipo lo escribe solo la demo: por una
               # petición, cualquiera podría pintar de rojo un equipo de verdad.
               'demo_state', 'demo_reason')


def _fresh(data) -> dict:
    """*data* without :data:`SERVER_COLS` — what a create may take from a request."""
    return {k: v for k, v in (data or {}).items() if k not in SERVER_COLS}


#: The largest magnitude a numeric column accepts from a request. Far above any real
#: measurement in millimetres, and far below what the engines' INTEGER can hold.
_NUM_MAX = 10 ** 9


def numbers_bad(spec, data: dict, bounds=None) -> str:
    """Coerce the numeric columns of *spec* present in *data*, in place; ``''`` or the field.

    A generic writer that stores whatever arrives put ``u_height: "abc"`` into an INTEGER
    column — SQLite takes it — and every read that did ``int()`` on it was a 500 from then on.
    So each INTEGER/REAL column the request names is checked here: a finite number, inside
    *bounds* (``{col: (lo, hi)}``; otherwise ``±_NUM_MAX``), stored as ``int`` or ``float``.

    Empty means "not said": the column's default, or ``None`` where the column admits it —
    which is what an empty number box always amounted to.

    Returns the name of the first bad column, so the answer can say which one.
    """
    bounds = bounds or {}
    for col in spec.columns:
        if col.name not in data or col.type not in ('INTEGER', 'REAL'):
            continue
        v = data[col.name]
        if v is None or (isinstance(v, str) and not v.strip()):
            if col.default is None and col.nullable:
                data[col.name] = None
                continue
            v = col.default if col.default is not None else 0
        if isinstance(v, (list, dict)):
            return col.name
        try:
            f = float(v)
        except (TypeError, ValueError):
            return col.name
        if not math.isfinite(f):
            return col.name
        lo, hi = bounds.get(col.name, (-_NUM_MAX, _NUM_MAX))
        if f < lo or f > hi:
            return col.name
        data[col.name] = int(f) if col.type == 'INTEGER' else f
    return ''


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


#: Cuántas filas se piden de una vez al recorrer una tabla buscando las que este lector puede
#: ver. Doscientas son un viaje a la base que cabe en la memoria de cualquiera; una es un viaje
#: por fila, y la tabla entera es lo que se estaba haciendo.
SCAN_CHUNK = 200

#: Cuántos trozos como mucho. Es un **presupuesto**, no un límite del resultado: sin él, una
#: instalación donde este lector no ve casi nada recorrería cien mil filas para devolver cero, y
#: con él se para y lo dice. Cinco mil filas miradas es de sobra para llenar una página, y si no
#: las llena es que hay que afinar la búsqueda — que es lo que se responde.
SCAN_ROUNDS = 25


def scan_pages(leer, cabe, want: int, offset: int = 0) -> dict:
    """``{rows, next_offset, capped}`` — las primeras *want* filas que pasen *cabe*.

    *leer* es ``(limit, offset) -> filas`` y *cabe* es el filtro que la base **no puede** hacer:
    quién puede ver qué depende de una cadena de pertenencia que no está en una columna, y
    escribirla en SQL sería tener la regla en dos sitios.

    Todo lo demás —el texto, el rol, la clase— va en el `WHERE` de *leer*: filtrar en Python lo
    que el motor sabe filtrar construye un diccionario por fila de toda la instalación para tirar
    casi todos. En una sala pequeña no se nota, que es lo que hace que se escriba así.

    **Un trozo se termina siempre.** Parar a mitad y seguir en el siguiente trozo dejaría fuera
    para siempre las filas que quedaban detrás en ése: el próximo salto empieza donde acabó el
    trozo, no donde se paró de mirar. Por eso puede devolver alguna fila de más, y es preferible
    a devolver menos sin saberlo.

    `capped` es «se acabó el presupuesto», no «hay más»: son dos cosas distintas y sólo una es
    un problema de quien mira. `next_offset` dice por dónde seguir — sin él, «las siguientes»
    tendría que volver a contar desde el principio y repetiría las que ya salieron.
    """
    fuera: list = []
    leidos = int(offset or 0)
    rondas = 0
    hay_mas = True
    while len(fuera) < want and rondas < SCAN_ROUNDS:
        filas = leer(SCAN_CHUNK, leidos) or []
        rondas += 1
        leidos += len(filas)
        for f in filas:
            if cabe(f):
                fuera.append(f)
        if len(filas) < SCAN_CHUNK:
            hay_mas = False
            break
    return {'rows': fuera, 'next_offset': leidos,
            # Recortada sólo si se dejó de mirar teniendo más por mirar.
            'capped': hay_mas and (len(fuera) >= want or rondas >= SCAN_ROUNDS)}
