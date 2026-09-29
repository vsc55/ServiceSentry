#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_rack`` and ``dc_row`` — the cabinets, and the rows they stand in."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: The sides of a rack somebody can reach. Stored as the FACT — which sides are reachable — and
#: not as a kind of cabinet: two identical racks, one in the middle of an aisle and one bolted to
#: a wall, are not worked on the same way, and the difference is where it stands rather than what
#: it is. The screen offers the usual arrangements as shortcuts that fill this in.
SIDES = ('front', 'rear', 'left', 'right')

_RACK = TableSpec(
    name='dc_rack',
    columns=(
        Column('uid',       'TEXT', primary_key=True),
        Column('room_uid',  'TEXT', nullable=False),
        Column('name',      'TEXT', nullable=False, default="''"),
        Column('u_height',  'INTEGER', nullable=False, default='42'),
        # Millimetres, because that is how racks are sold and how a floor plan is drawn.
        Column('width_mm',  'INTEGER', nullable=False, default='600'),
        Column('depth_mm',  'INTEGER', nullable=False, default='1000'),
        # Where it stands on the room's plan, and which way it faces. Held here rather than in
        # a browser's arrangement store: where a rack IS, is a fact about the room, and the
        # next person to open the plan needs the same answer.
        Column('pos_x',     'REAL', nullable=False, default='0'),
        Column('pos_y',     'REAL', nullable=False, default='0'),
        Column('rotation',  'INTEGER', nullable=False, default='0'),
        # Some racks are numbered from the bottom and some from the top, and getting it wrong
        # sends somebody to the other end of a cabinet at three in the morning.
        Column('desc_units', 'INTEGER', nullable=False, default='0'),
        # ── The posts, which are what decides whether a server fits ──────────────────
        #
        # Not the cabinet's depth: the distance BETWEEN the posts is where a server's rails
        # bolt on, and what is left behind the rear post is where its cables go. A 1000 mm
        # cabinet with the posts badly placed takes less than an 800 mm one with them right.
        #
        # Three separate measurements and no arithmetic tying them to `depth_mm`: what somebody
        # measured with a tape and what the sum says are two different things, and forcing the
        # second discards the first. Where they disagree the panel says so — the same rule as
        # everywhere else here.
        Column('rail_front_mm', 'INTEGER', nullable=False, default='0'),   # door → front post
        Column('rail_depth_mm', 'INTEGER', nullable=False, default='0'),   # post → post
        Column('rail_rear_mm',  'INTEGER', nullable=False, default='0'),   # rear post → back
        # Which sides can be reached, comma-separated in the order of `SIDES`. A wall-mounted
        # cabinet has no rear; one pushed against a wall loses a flank. It decides whether the
        # equipment in it can be cabled and serviced at all, and it is the reason a rear-face
        # item in a rack with no rear access is worth pointing at.
        Column('access', 'TEXT', nullable=False, default="'front,rear,left,right'"),
        # A qué fila pertenece, si alguien lo ha dicho. Vacío = suelto, que es un estado
        # real: el armario de comunicaciones de un rincón no está en ninguna fila.
        Column('row_uid', 'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        # Un armario también se compra. Lo llevaban el equipo, el cable de datos y el de
        # corriente, y el mueble que los sostiene no — que es el que sale por más dinero en el
        # albarán y el que la aseguradora pregunta primero. La última, para que aparecer sobre
        # una tabla llena sea un `ADD COLUMN`.
        Column('asset', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_rack_room', ('room_uid',)),),
)

_ROW = TableSpec(
    name='dc_row',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        Column('room_uid', 'TEXT', nullable=False),
        # Cómo la llama la gente: «la fila B». Es lo que se dice por teléfono, igual que la
        # posición de baldosa, y por eso es lo primero.
        Column('name',     'TEXT', nullable=False, default="''"),
        # A qué pasillo da cada cara. NO se deduce de la orientación de los racks: dos filas
        # enfrentadas comparten pasillo frío y eso es una decisión de diseño de la sala, no una
        # consecuencia de hacia dónde mira una caja. De aquí sale si el aire caliente de una
        # fila entra en la aspiración de la de enfrente, que es la pregunta de verdad.
        Column('front_aisle', 'TEXT', nullable=False, default="''"),
        Column('rear_aisle',  'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_row_room', ('room_uid',)),),
)
