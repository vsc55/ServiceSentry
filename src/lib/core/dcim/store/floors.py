#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_floor`` — una planta de una sede, con su plano de fondo.

Lo que faltaba entre la sede y la sala. Una sede se sitúa en un mapa por su dirección, y una sala
se dibuja por dentro con sus racks; pero dónde está cada sala DENTRO del edificio no se podía
decir, y en una sede de tres plantas «la sala de comunicaciones» son tres sitios. Una planta es
un plano —el que mandó el arquitecto— sobre el que se colocan las salas de esa planta.

No es un ámbito de propiedad: una planta es de su sede, y escribir en ella es escribir en la
sede. Ponerle dueño aparte sería permitir que una empresa editara la planta de un edificio que no
puede ni listar.
"""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec

_FLOOR = TableSpec(
    name='dc_floor',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('site_uid',    'TEXT', nullable=False),
        Column('name',        'TEXT', nullable=False, default="''"),
        # Qué planta es, contando desde la calle: 0 la baja, 1 la primera, -1 el sótano. Es
        # el orden en que se enseñan y el que se dice en voz alta; el nombre es lo que pone en
        # el ascensor, que no siempre coincide.
        Column('level',       'INTEGER', nullable=False, default='0'),
        # El plano de fondo, un nombre acuñado por el panel —nunca una ruta— como el de una
        # sala; y lo ANCHO que es de verdad lo que dibuja, en milímetros, que es lo que hace
        # que una sala de 6 m mida 6 m encima de él. `0` = sin decir: el plano se estira al
        # tamaño de lo que haya.
        Column('plan',        'TEXT', nullable=False, default="''"),
        Column('plan_mm',     'INTEGER', nullable=False, default='0'),
        # Dónde cae la esquina de arriba a la izquierda del plano en la planta, en milímetros:
        # negativo cuando el dibujo tiene margen antes de empezar el edificio. Lo pone la
        # calibración, igual que en una sala.
        Column('plan_x',      'REAL', nullable=False, default='0'),
        Column('plan_y',      'REAL', nullable=False, default='0'),
        # Hacia dónde apunta el norte en el plano: grados en el sentido del reloj desde arriba
        # del dibujo. NULL es «nadie lo ha dicho», que no es «el norte está arriba».
        Column('north_deg',   'REAL'),
        Column('description', 'TEXT', nullable=False, default="''"),
        # La «zona general» de la planta: una sala que ocupa la planta entera, en (0, 0) y sin
        # girar, donde va lo que se pone en la planta sin estar en ninguna sala —un rack en un
        # pasillo, un cuadro eléctrico junto a la escalera—. Una sala y no un «rack sin sala»:
        # todo lo que hay en el inventario cuelga de una sala —la empresa, el cableado, el 3D, el
        # alzado lo dan por hecho— y hacer opcional ese eslabón era cambiarlo todo. Vacío hasta
        # que se pone algo suelto por primera vez: una planta sin nada suelto no tiene por qué
        # tener una sala más en el árbol.
        Column('area_uid',    'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_floor_site', ('site_uid',)),),
)
