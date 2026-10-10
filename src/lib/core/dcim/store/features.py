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
#: `front`: la pieza tiene un lado de DELANTE —por donde se abre un armario o un cuadro, por
#: donde se sienta uno a una mesa—, y el dibujo lo marca. Es el lado de `pos_y`, el de arriba
#: antes de girar, el mismo que el de un rack: girarla es cambiar hacia dónde mira.
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
    'panel':     {'w': 900,  'd': 400,  'h': 2000, 'layer': 'room', 'front': True},  # cuadro eléctrico
    'ups':       {'w': 1200, 'd': 900,  'h': 1900, 'layer': 'room', 'front': True},
    'crac':      {'w': 600,  'd': 1000, 'h': 2000, 'layer': 'room', 'front': True},  # climatizador
    'bench':     {'w': 1600, 'd': 800,  'h': 750,  'layer': 'room', 'front': True},  # mesa de trabajo
    'cabinet':   {'w': 1000, 'd': 500,  'h': 2000, 'layer': 'room', 'front': True},  # armario: repuestos, material
    'extinguisher': {'w': 300, 'd': 300, 'h': 900, 'layer': 'room'},
    'tray':      {'w': 6000, 'd': 300,  'h': 140,  'base': 2720, 'layer': 'air'},
    # El control de accesos. Un torno —trípode o de pasillo—, con su delante, que es el lado por
    # el que se entra. Y lo que va en una pared: un lector de tarjetas, o la puerta de enlace a la
    # que se conectan las cerraduras (el IQ de Salto KS), a la altura a la que se cuelga.
    'turnstile': {'w': 1000, 'd': 1600, 'h': 1000, 'layer': 'room', 'front': True},
    'reader':    {'w': 200,  'd': 80,   'h': 200,  'base': 1300, 'layer': 'room'},
    # La seguridad del edificio, que también se dibuja y se cuenta: dónde está la boca de
    # incendio más cercana es una pregunta de plano, no de inventario. Casi todo va en una
    # PARED, a la altura a la que se cuelga, con su delante hacia la sala; el detector, en el
    # techo.
    'hose_reel':  {'w': 700, 'd': 250, 'h': 700, 'base': 900,  'layer': 'room', 'front': True},  # BIE
    'fire_alarm': {'w': 120, 'd': 60,  'h': 120, 'base': 1400, 'layer': 'room', 'front': True},  # pulsador
    'emergency_light': {'w': 350, 'd': 80, 'h': 120, 'base': 2200, 'layer': 'room', 'front': True},
    'smoke_detector':  {'w': 120, 'd': 120, 'h': 60, 'base': 2940, 'layer': 'air'},
    'first_aid':  {'w': 400, 'd': 150, 'h': 500, 'base': 1200, 'layer': 'room', 'front': True},  # botiquín
    'aed':        {'w': 450, 'd': 200, 'h': 450, 'base': 1200, 'layer': 'room', 'front': True},  # desfibrilador
    'label':     {'w': 1600, 'd': 400,  'h': 10,   'layer': 'air'},     # una nota sobre el plano
}

#: Qué cerradura lleva una pieza del control de accesos. Un cilindro electrónico (el Neo de
#: Salto) o un escudo en una puerta; una cerradura de taquilla (XS4 Locker) en un armario; un
#: lector en un torno o en una pared. Cerrado por lo mismo que los tipos de pieza: es lo que se
#: cuenta y lo que se pregunta —«¿qué puertas tienen cilindro?»—.
LOCK_KINDS = ('cylinder', 'escutcheon', 'locker', 'reader')
#: Las piezas que pueden llevar control de accesos: las que se cierran o se cruzan, y el lector
#: o la puerta de enlace en sí.
ACCESS_KINDS = ('door', 'cabinet', 'turnstile', 'reader')

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
        # Cuántas estanterías tiene, si es un armario: 1, 2, 5. VACÍO en lo que no es un
        # armario —una puerta no tiene baldas—, y uno en un armario que no lo dice.
        Column('shelves', 'INTEGER'),
        # El control de accesos, en las piezas que lo llevan (`ACCESS_KINDS`): qué cerradura es
        # (`LOCK_KINDS`), qué modelo y con qué número de serie, y a qué puerta de enlace se
        # conecta —`hub_uid`, otra pieza de la sede, de tipo `reader`—, que es lo que deja
        # preguntar qué puertas cuelgan de un IQ. Vacíos en todo lo demás.
        Column('lock',     'TEXT', nullable=False, default="''"),
        # Su modelo del CATÁLOGO, como el de un equipo (`dc_item.type_uid`): de ahí salen su
        # marca y su foto, y por él se cuenta «cuántos Neo hay». `model` se queda como texto
        # para lo que no está en el catálogo, y se rellena con el del catálogo al elegirlo.
        Column('type_uid', 'TEXT', nullable=False, default="''"),
        Column('model',    'TEXT', nullable=False, default="''"),
        Column('serial',   'TEXT', nullable=False, default="''"),
        Column('hub_uid',  'TEXT', nullable=False, default="''"),
        # Y su estado, como el de un equipo: el del dispositivo vigilado al que se vincula, y si
        # no tiene, el de la demo (`demo_state`, que solo escribe `main.py dcim demo`). El mismo
        # `item_state` lo lee para las dos cosas.
        Column('device_uid', 'TEXT', nullable=False, default="''"),
        Column('demo_state', 'TEXT', nullable=False, default="''"),
        Column('demo_reason', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_feature_room', ('room_uid',)),),
)

#: Las piezas que guardan cosas, por estanterías. Solo el armario: es lo que se pidió, y el
#: resto de piezas de una sala no tiene dónde poner nada.
SHELVED_KINDS = ('cabinet',)
#: Las estanterías que puede tener un armario. Un número que nadie confundirá con un armario.
SHELVES_MAX = 50

#: Lo que hay en cada estantería de un armario: material suelto —un rollo de cable, cajas de
#: tornillos, un switch de repuesto sin montar— con su cantidad. No es inventario de equipos:
#: lo que tiene número de serie y se monta va a un rack; esto es lo que se busca en un armario.
_SHELF_ITEM = TableSpec(
    name='dc_shelf_item',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('feature_uid', 'TEXT', nullable=False),
        # Qué estantería, contando desde ARRIBA: la primera es la de arriba, que es como se
        # cuenta delante de un armario abierto.
        Column('shelf',       'INTEGER', nullable=False, default='1'),
        Column('label',       'TEXT', nullable=False, default="''"),
        Column('qty',         'INTEGER', nullable=False, default='1'),
        Column('notes',       'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_shelf_item_feature', ('feature_uid',)),),
)
