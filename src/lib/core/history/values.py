#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How ONE measured value is stored once there is no JSON blob per sample.

A JSON document carries its own types: ``true`` is not ``1``, ``10`` is not ``10.0``, ``[...]``
is not a string, and a field that is present and empty is not a field that is absent. A column
carries none of that. So every fact carries a one-letter mark saying what the value IS.

There are eight marks, and each one is here because a real installation produced it: of 21,092
values measured, **19,770 are numbers** (15,102 whole, 4,668 with decimals), **811 text**, **285
booleans**, **203 nulls** and **23 lists or dictionaries**. Without the mark, ``holds_vip: true``
comes back as ``1``, ``10.0`` comes back as ``10``, and Proxmox's ``node_ips`` does not come back
at all. None of those is an error anyone would see — they are a panel quietly showing something
slightly different from what was measured, which is the failure this domain keeps paying for.

Nothing here touches the database. This is the one place that decides what a value is, so the
store can stay about rows.
"""

from __future__ import annotations

import json
import math

#: Las marcas. Una letra, porque va en cada uno de los veintisiete millones de hechos que ocupan
#: treinta días de una instalación real.
#:
#: En minúscula y sin pares que sólo se diferencien por la caja: la intercalación por defecto de
#: MySQL **no distingue mayúsculas**, así que `'n'` y `'N'` serían la misma marca ahí y dos
#: distintas en SQLite.
FLOAT = 'n'     # un número con decimales
INT = 'i'       # un entero que cabe exacto en un REAL
BIGINT = 'g'    # un entero demasiado grande para caber exacto en un REAL
SPECIAL = 'f'   # NaN o infinito: un flotante que una columna REAL no devuelve igual
TEXT = 't'
BOOL = 'b'
NULL = 'z'      # el campo estaba, y valía nada. No es lo mismo que no estar.
JSON_ = 'j'     # una lista o un diccionario: lo que esta forma no sabe partir en columnas

KINDS = (FLOAT, INT, BIGINT, SPECIAL, TEXT, BOOL, NULL, JSON_)

#: Las marcas cuyo valor numérico vive en ``num`` y por tanto **cuentan en un promedio**.
#: `BIGINT` está dentro a propósito: guarda el número aproximado ahí y el exacto en `txt`.
NUMERIC_KINDS = (FLOAT, INT, BIGINT)

#: Hasta aquí un entero cabe **exacto** en un REAL de 64 bits.
#:
#: Por encima, ``float(v)`` redondea y devuelve otro número sin avisar. SNMP manda contadores de
#: 64 bits, así que no es teórico: una interfaz de 100 Gb/s saturada cruza los nueve petabytes
#: en poco más de una semana. Medido sobre la instalación real, el entero más grande que hay hoy
#: es 1,84·10¹⁴ —2⁴⁷, cuarenta y nueve veces de margen— pero ese margen es el de hoy.
EXACT_INT = 2 ** 53


def encode(value) -> tuple[str, float | None, str | None]:
    """``(kind, num, txt)`` — un valor repartido en las columnas de un hecho.

    Un entero que no cabe exacto va en las **dos** columnas: aproximado en ``num``, para que siga
    contando en un promedio o en un máximo, y exacto en ``txt``, que es lo que se devuelve. Así
    ninguna pregunta de flota se lo salta y ningún dígito se pierde.
    """
    # `bool` antes que `int`: en Python un booleano ES un entero, y preguntarlo al revés
    # convertiría `True` en 1 y lo devolvería como 1.
    if isinstance(value, bool):
        return BOOL, (1.0 if value else 0.0), None
    if value is None:
        return NULL, None, None
    if isinstance(value, int):
        if abs(value) > EXACT_INT:
            return BIGINT, float(value), str(value)
        return INT, float(value), None
    if isinstance(value, float):
        if not math.isfinite(value):
            return SPECIAL, None, repr(value)
        return FLOAT, value, None
    if isinstance(value, (list, dict)):
        return JSON_, None, json.dumps(value, ensure_ascii=False, sort_keys=True)
    return TEXT, None, str(value)


def decode(kind: str, num, txt):
    """El valor de vuelta, tal como lo escribió el módulo que lo midió."""
    if kind == BOOL:
        return bool(num)
    if kind == NULL:
        return None
    if kind == INT:
        return None if num is None else int(num)
    if kind == FLOAT:
        return None if num is None else float(num)
    if kind == BIGINT:
        try:
            return int(str(txt))
        except (TypeError, ValueError):
            return None if num is None else int(num)
    if kind == SPECIAL:
        try:
            return float(str(txt))
        except (TypeError, ValueError):
            return None
    if kind == JSON_:
        try:
            return json.loads(txt or 'null')
        except (TypeError, ValueError):
            return None
    return txt


def encode_sample(medidas: dict | None) -> list[tuple[str, str, float | None, str | None]]:
    """``[(campo, kind, num, txt), …]`` de una muestra entera, en orden estable."""
    return [(str(campo),) + encode(valor)
            for campo, valor in sorted((medidas or {}).items(), key=lambda kv: str(kv[0]))]


def decode_sample(hechos) -> dict:
    """``{campo: valor}`` a partir de ``[(campo, kind, num, txt), …]``."""
    return {str(campo): decode(kind, num, txt) for campo, kind, num, txt in hechos}
