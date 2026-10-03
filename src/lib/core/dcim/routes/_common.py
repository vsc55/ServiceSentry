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
