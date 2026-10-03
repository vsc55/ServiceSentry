#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_feature`` — what a room HAS that is not a rack: a door, a column,
a CRAC unit. Drawn on the floor plan, and the reason a plan looks like the
room instead of like a grid."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: Lo que puede haber en una sala aparte de los racks, con lo que mide de fábrica —milímetros—
#: y en qué capa se dibuja. Cerrado a propósito: un plano donde cada quien inventa su tipo deja
#: de poder decirse en voz alta («la columna de la fila B») y deja de poder contarse.
#:
#: `layer` no es estética. Un pasillo confinado se pinta DEBAJO de los racks porque es el suelo
#: entre ellos, y una bandeja portacables ENCIMA porque va por el aire: dibujarlas en el orden
#: equivocado tapa lo que se venía a mirar.
#: `h` es lo ALTO, y `base` a qué altura empieza. Una sala en planta no dice nada de lo alto que
#: es nada, y en cuanto se levanta el dibujo la diferencia entre una bandeja a 2,7 m y una mesa
#: de 0,75 es toda la sala. `base` solo lo usa lo que va colgado: una bandeja no está en el
#: suelo, y dibujarla ahí la pone donde estorba en vez de donde va.
FEATURE_KINDS = {
    'aisle':     {'w': 4800, 'd': 1200, 'h': 2200, 'layer': 'floor'},   # pasillo confinado
    'zone':      {'w': 2000, 'd': 2000, 'h': 20,   'layer': 'floor'},   # zona libre / reserva
    'column':    {'w': 500,  'd': 500,  'h': 3000, 'layer': 'room'},    # del suelo al techo
    'wall':      {'w': 4000, 'd': 100,  'h': 2700, 'layer': 'room'},    # mampara o tabique
    'door':      {'w': 1000, 'd': 120,  'h': 2100, 'layer': 'room'},
    'panel':     {'w': 900,  'd': 400,  'h': 2000, 'layer': 'room'},    # cuadro eléctrico
    'ups':       {'w': 1200, 'd': 900,  'h': 1900, 'layer': 'room'},
    'crac':      {'w': 600,  'd': 1000, 'h': 2000, 'layer': 'room'},    # climatizador
    'bench':     {'w': 1600, 'd': 800,  'h': 750,  'layer': 'room'},    # mesa de trabajo
    'extinguisher': {'w': 300, 'd': 300, 'h': 900, 'layer': 'room'},
    'tray':      {'w': 6000, 'd': 300,  'h': 140,  'base': 2720, 'layer': 'air'},
    'label':     {'w': 1600, 'd': 400,  'h': 10,   'layer': 'air'},     # una nota sobre el plano
}

#: Las capas, de abajo arriba. El orden ES el dato: quien dibuje recorre esto y no inventa.
FEATURE_LAYERS = ('floor', 'room', 'air')

_FEATURE = TableSpec(
    name='dc_feature',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        Column('room_uid', 'TEXT', nullable=False),
        # Uno de `FEATURE_KINDS`. Se valida al escribir: un tipo inventado es una caja que el
        # dibujo no sabe pintar y que ninguna leyenda explica.
        Column('kind',     'TEXT', nullable=False, default="''"),
        Column('label',    'TEXT', nullable=False, default="''"),
        # Milímetros y grados, igual que un rack — que es lo que permite que las dos cosas se
        # dibujen sobre el mismo plano sin que nadie convierta nada.
        Column('pos_x',    'REAL', nullable=False, default='0'),
        Column('pos_y',    'REAL', nullable=False, default='0'),
        Column('width_mm', 'INTEGER', nullable=False, default='600'),
        Column('depth_mm', 'INTEGER', nullable=False, default='600'),
        Column('rotation', 'INTEGER', nullable=False, default='0'),
        # Lo alto que es, y a qué altura del suelo empieza, en milímetros. VACÍOS —`NULL`— son
        # «los de su tipo» (`FEATURE_KINDS`), que es lo que eran todas las piezas antes de que
        # existieran: una mesa, 750; una bandeja, colgada a 2720. Vacíos y no cero porque cero es
        # una medida: una bandeja puesta en el suelo está a cero, y con cero como «sin decir» no
        # habría forma de ponerla ahí. Se pidieron desde la vista de frente, estirando una mesa
        # hacia arriba: no había dónde guardar que ESA mesa es más alta.
        Column('height_mm', 'INTEGER'),
        Column('base_mm', 'INTEGER'),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_feature_room', ('room_uid',)),),
)
