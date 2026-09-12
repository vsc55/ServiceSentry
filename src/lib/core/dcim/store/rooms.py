#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_room`` — a room inside a site, and how it is cooled."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: How a room is cooled, when somebody has said. `''` means nobody has — which is not the same
#: as `none`, and the difference matters when reading a room that runs hot.
COOLING = ('', 'none', 'room', 'cold_aisle', 'hot_aisle', 'in_row', 'rear_door', 'split')

#: Lo alto que es una sala cuando nadie lo ha dicho. Tres metros es lo normal en una sala
#: técnica; se usa para el techo y para las columnas, que van de suelo a techo por definición.
ROOM_HEIGHT_MM = 3000

_ROOM = TableSpec(
    name='dc_room',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('site_uid',    'TEXT', nullable=False),
        Column('name',        'TEXT', nullable=False, default="''"),
        # A floor plan somebody uploaded, by name in the media store — never a path. The MIB
        # catalogue's path traversal was exactly this shape.
        Column('plan',        'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
        # How it is cooled — one of `COOLING`. Empty means nobody has said, which is NOT the
        # same as `none`: a comms cupboard with no cooling at all is a fact worth recording, and
        # a room whose cooling nobody wrote down is a question. Trailing, so an existing
        # database gets it by ADD COLUMN.
        Column('cooling', 'TEXT', nullable=False, default="''"),
        # How wide the plan picture is IN THE ROOM — millimetres. One number and not two: the
        # height follows from the image's own proportions, and a stored height could disagree
        # with the picture and stretch it, which would put a rack where it is not. 0 means
        # nobody has scaled it, and then it is drawn to fit and says so.
        Column('plan_mm', 'INTEGER', nullable=False, default='0'),
        # Cuánto mide la sala, y cuánto mide su baldosa. Un plano sin las medidas de la sala se
        # puede dibujar y no se puede usar para lo único que sirve un plano: contestar si cabe
        # otra fila. 0 = nadie las ha dicho, y entonces el dibujo se encuadra a lo que hay.
        #
        # La baldosa es 600 en casi todas partes y no en todas — hay suelos de 500 y de 610 —,
        # así que es un dato de la sala y no una constante. Sirve para el imán del editor y para
        # nombrar posiciones («B7»), que es como se dan por teléfono.
        Column('width_mm', 'INTEGER', nullable=False, default='0'),
        Column('depth_mm', 'INTEGER', nullable=False, default='0'),
        Column('tile_mm',  'INTEGER', nullable=False, default='600'),
    ),
    indexes=(Index('idx_dc_room_site', ('site_uid',)),),
)
