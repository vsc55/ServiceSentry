#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_feature`` — what a room HAS that is not a rack: a door, a column,
a CRAC unit. Drawn on the floor plan, and the reason a plan looks like the
room instead of like a grid."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: Lo que puede haber en una sala aparte de los racks, con lo que mide de fábrica —milímetros—,
#: en qué capa se dibuja y cómo se ve. Sale del catálogo del editor de planos
#: (`lib.core.plan2d.kinds`), donde el inventario dice qué objetos base usa y cuáles son solo
#: suyos (`lib.core.dcim.plankinds`): una puerta mide lo mismo y se dibuja igual en cualquier plano.
#: Los que se crean desde la pantalla los añade `plankinds.feature_kinds(wa)` a lo que se acepta.
#:
#: `front`: la pieza tiene un lado de DELANTE —por donde se abre un armario o un cuadro, por
#: donde se sienta uno a una mesa—, y el dibujo lo marca. `layer` no es estética: un pasillo
#: confinado se pinta DEBAJO de los racks y una bandeja ENCIMA. `h` es lo ALTO, y `base` a qué
#: altura empieza: una bandeja no está en el suelo.
from lib.core.dcim.plankinds import FEATURE_KINDS  # noqa: E402,F401

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
        # El grupo con el que se mueve en el plano de la sala, o ''. Un pasillo y los racks que lo
        # cierran se arrastran juntos; un id compartido y no una tabla de grupos, porque un grupo
        # no es más que lo que tiene dentro.
        Column('group_uid', 'TEXT', nullable=False, default="''"),
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
