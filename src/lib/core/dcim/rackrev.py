#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cómo estaba un armario, y qué le pasó: las dos preguntas con una sola foto.

Se piden dos cosas de un armario que lleva un año montado. **Qué pasó** —quién movió el switch,
cuándo se retiró la regleta, de dónde salió esa máquina que nadie recuerda haber puesto— y **cómo
estaba** en una fecha, que es la que se hace cuando algo dejó de funcionar y hay que comparar.

Parecen dos funciones y son una. Guardando una **foto del armario después de cada cambio**, la
segunda es la foto y la primera es la diferencia entre dos fotos consecutivas — y salen de la
misma tabla, sin dos mecanismos que mantener de acuerdo sobre qué cuenta como un cambio. Al
revés no funciona: de una lista de acontecimientos no se puede reconstruir un estado sin
reproducirlos todos, y basta que falte uno para que la reconstrucción mienta sin decirlo.

**Sobre `dc_rev`**, que es la tabla que ya guarda las versiones de un modelo del catálogo, de una
plantilla y del documento de conectores. Su `scope` nació para esto: una tabla por cada cosa que
quiere historial serían cuatro almacenes haciendo lo mismo. Y hereda su poda —las últimas
:data:`~lib.core.dcim.revisions.KEEP` de cada armario— que es lo que impide que un rack que se
toca a diario crezca para siempre.

**Lo que entra en la foto es dónde está cada cosa y qué es**, no todo lo que cuelga del armario.
El cableado y la alimentación tienen sus propias pantallas y su propia vida: meterlos aquí haría
que enchufar un latiguillo generase una versión del armario, y un historial donde nueve de cada
diez renglones son ruido es un historial que nadie abre.
"""

from __future__ import annotations

#: Lo que se guarda de cada equipo. Corto a propósito: la foto tiene que caber en una fila de la
#: tabla de versiones y lo que se le pregunta a un armario de hace seis meses es qué había, dónde
#: y con qué número de serie — no el fondo en milímetros de cada caja.
CAMPOS = ('uid', 'label', 'u_start', 'u_height', 'face', 'role', 'serial', 'asset',
          'host_uid', 'parent_uid', 'u_slots', 'u_slot', 'u_slot_span', 'u_split')

#: Y del armario. Su nombre y su altura son lo que cambia de sitio a las demás cosas.
CAMPOS_RACK = ('name', 'u_height', 'desc_units', 'width_mm', 'depth_mm', 'room_uid')

#: Cómo se llama esto en `dc_rev`.
SCOPE = 'rack'


def snapshot(rack: dict, items) -> dict:
    """La foto: el armario y lo que hay dentro, ordenado por U.

    **Ordenado**, y no en el orden en que la base los devolvió: dos fotos del mismo armario
    tienen que salir iguales cuando nada ha cambiado, y un orden que depende del identificador
    haría que reordenar la consulta se leyera como que alguien movió tres equipos.
    """
    fuera = {c: (rack or {}).get(c) for c in CAMPOS_RACK}
    fuera['items'] = sorted(
        [{c: (it or {}).get(c) for c in CAMPOS} for it in (items or ())],
        key=lambda x: (int(x.get('u_start') or 0), str(x.get('uid') or '')))
    return fuera


def _by_uid(foto: dict) -> dict:
    return {str(i.get('uid') or ''): i for i in ((foto or {}).get('items') or ())}


def _where(item: dict) -> str:
    """Dónde está algo, dicho como se lee: ``U4`` o ``U4–U6``, y ``encima`` si va montado."""
    if str((item or {}).get('parent_uid') or ''):
        return 'mounted'
    u = int((item or {}).get('u_start') or 0)
    alto = max(1, int((item or {}).get('u_height') or 1))
    return f'U{u}' if alto == 1 else f'U{u}–U{u + alto - 1}'


def compare(antes: dict, ahora: dict) -> list[dict]:
    """Qué cambió entre dos fotos: ``[{kind, uid, label, field, from, to}, …]``.

    Tres clases y ninguna más — llegó, se fue, cambió—, que es lo que se puede decir en un
    renglón. Un equipo que se mueve **no** es uno que se va y otro que llega: es el mismo, y
    contarlo como dos es lo que convierte «moví el switch una U» en dos líneas que no se
    entienden juntas. Por eso se casan por `uid` y no por posición.

    Lo del armario va aparte, con `uid` vacío: renombrarlo o crecerlo no es un equipo.
    """
    a, b = _by_uid(antes), _by_uid(ahora)
    fuera: list[dict] = []
    for campo in CAMPOS_RACK:
        viejo, nuevo = (antes or {}).get(campo), (ahora or {}).get(campo)
        if viejo != nuevo:
            fuera.append({'kind': 'rack', 'uid': '', 'label': '', 'field': campo,
                          'from': viejo, 'to': nuevo})
    for uid, it in b.items():
        if uid not in a:
            fuera.append({'kind': 'add', 'uid': uid,
                          'label': str(it.get('label') or ''),
                          'field': '', 'from': '', 'to': _where(it)})
    for uid, it in a.items():
        if uid not in b:
            fuera.append({'kind': 'drop', 'uid': uid,
                          'label': str(it.get('label') or ''),
                          'field': '', 'from': _where(it), 'to': ''})
    for uid, nuevo in b.items():
        viejo = a.get(uid)
        if not viejo:
            continue
        for campo in CAMPOS:
            if campo == 'uid' or viejo.get(campo) == nuevo.get(campo):
                continue
            fuera.append({'kind': 'edit', 'uid': uid,
                          'label': str(nuevo.get('label') or viejo.get('label') or ''),
                          'field': campo,
                          'from': viejo.get(campo), 'to': nuevo.get(campo)})
    return fuera


def same(a: dict, b: dict) -> bool:
    """Si dos fotos dicen lo mismo.

    Existe para no guardar una versión por cada escritura que no cambió nada: una petición que
    reenvía la ficha entera con un campo igual es lo normal —un formulario manda todo— y un
    historial con doce renglones idénticos no dice qué pasó, dice que alguien pulsó guardar.
    """
    return compare(a or {}, b or {}) == []
