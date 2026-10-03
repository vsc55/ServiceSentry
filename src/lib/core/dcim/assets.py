#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El número de inventario: qué lo hace único y cómo se pide el siguiente.

Un número de inventario **no es la etiqueta**. La etiqueta es lo que está rotulado en la caja
—se repite, se borra, se equivoca— y aun así es con lo que trabaja quien está delante con una
linterna. El de inventario lo pone la casa, es único, y es con lo que se cuenta: cuántos hay,
cuáles se compraron juntos, cuál toca sustituir.

De eso salen las dos reglas de este módulo, y las dos son la misma:

**Uno.** Es único **entre todo lo inventariado**, no dentro de su tabla. INV-45 es INV-45 tanto
si es un servidor como si es un latiguillo: en el albarán, en la hoja de la aseguradora y en la
caja de repuestos hay una lista, no cuatro. Comprobarlo por tabla dejaría dos cosas distintas
con el mismo número y ningún error el día que se escribe.

**Dos.** Nadie debería teclear el siguiente. Quien numera un armario entero escribe cuarenta
veces un número que ya está decidido, y la vez que se equivoca no lo dice nadie: el duplicado
aparece meses después, cuando dos fichas dicen ser la misma cosa. Escribiendo ``INV-?`` lo pone
el panel — y lo pone **al guardar y en el servidor**, que es lo único que sirve: dos personas
numerando a la vez desde dos pantallas verían las dos el mismo «siguiente».

El ancho se pide con los propios interrogantes: ``INV-?`` da ``INV-46`` y ``INV-???`` da
``INV-046``. Las dos son el número 46 — el relleno es cómo se escribe, no qué es— y por eso una
instalación que empezó sin ceros y siguió con ellos no reinicia la cuenta.

**El siguiente es el mayor más uno, nunca un hueco.** Si el 20 se dio de baja, el 20 no vuelve:
su etiqueta sigue en un cajón y el historial sigue nombrándolo. Reciclar un número convierte dos
cosas en una a los ojos de cualquiera que mire un papel viejo, que es justo lo que un número de
inventario existe para evitar.
"""

from __future__ import annotations

import re

#: El comodín. Uno o más, en un solo grupo: `INV-?` es «el siguiente» y `INV-???` es lo mismo
#: escrito a tres cifras.
ASK = '?'

#: La columna. Una sola en todas las tablas que llevan número, y dicha aquí: dos nombres para el
#: mismo dato son dos pantallas que lo escriben distinto y una búsqueda que encuentra la mitad.
ASSET_COL = 'asset'

_ASKS = re.compile(r'\?+')


def norm(value) -> str:
    """El texto con el que se COMPARA, que no es el que se guarda.

    Sin espacios a los lados y en minúsculas: `inv-45` e `INV-45` son el mismo número para
    cualquiera que los lea, y admitir los dos es tener el duplicado que esto viene a impedir.
    Se guarda lo tecleado — corregirle a alguien las mayúsculas de su propia numeración es
    decidir por él cómo se escribe su almacén.
    """
    return str(value or '').strip().lower()


def asks(text) -> tuple | None:
    """``(antes, ancho, después)`` si este texto pide un número, o ``None``.

    ``None`` es la respuesta normal: casi todo lo que se teclea aquí es un número ya decidido,
    y el comodín es lo excepcional. Devolver la pieza partida y no un booleano deja que quien
    llama componga el resultado sin volver a buscar dónde estaban los interrogantes.
    """
    t = str(text or '').strip()
    trozos = _ASKS.findall(t)
    if len(trozos) != 1:
        return None
    i = t.index(trozos[0])
    return t[:i], len(trozos[0]), t[i + len(trozos[0]):]


def bad(text) -> str:
    """La clave del error si el patrón no se puede resolver, o ``''``.

    Dos grupos de interrogantes no son un patrón ambiguo: son dos patrones. `INV-?-?` puede
    querer decir cualquier cosa y elegir por quien lo escribió guardaría un número que no pidió
    — y como el resultado parece razonable, no se descubre.
    """
    t = str(text or '').strip()
    if ASK not in t:
        return ''
    return '' if asks(t) else 'dcim_asset_ask_many'


def numbers(values, before: str, after: str):
    """Los números que ya se han dado con esta forma, de una lista de textos.

    Sin mirar el relleno: `INV-045` y `INV-45` son el 45, y contarlos como dos numeraciones
    distintas haría que cambiar de ancho un día empezara otra vez por el uno.
    """
    b, a = norm(before), norm(after)
    for v in values or ():
        t = norm(v)
        if not t.startswith(b) or not t.endswith(a) or len(t) <= len(b) + len(a):
            continue
        medio = t[len(b):len(t) - len(a)] if a else t[len(b):]
        if medio.isdigit():
            yield int(medio)


def render(before: str, n: int, width: int, after: str) -> str:
    """El número, escrito. El relleno es un mínimo y no un tope: pasar de `INV-99` a `INV-100`
    con dos interrogantes escribe las tres cifras, porque la alternativa es no poder numerar el
    ciento uno."""
    return f'{before}{max(1, int(n)):0{max(1, int(width))}d}{after}'


def resolve(text, taken) -> tuple:
    """``(lo que se guarda, la clave del error)``.

    *taken* son los números **ya usados con esta misma forma**, para poder decir cuál es el
    siguiente. Quien llama los saca de la base; aquí no se sabe qué es una base.

    Un texto sin comodín se devuelve tal cual: esto resuelve el patrón, y decidir si además se
    repite es la otra pregunta —la de la unicidad— que se hace contra todo lo inventariado y no
    solo contra los de esta forma.
    """
    malo = bad(text)
    if malo:
        return str(text or '').strip(), malo
    trozo = asks(text)
    if not trozo:
        return str(text or '').strip(), ''
    before, width, after = trozo
    ya = list(numbers(taken, before, after))
    return render(before, (max(ya) + 1) if ya else 1, width, after), ''
