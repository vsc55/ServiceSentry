#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_site`` — a place with an address: the outermost box of the chain."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


_SITE = TableSpec(
    name='dc_site',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        Column('address',     'TEXT', nullable=False, default="''"),
        # Kept whether or not anything draws them: where a datacenter is, is a fact about it,
        # and the panel deliberately does not depend on a tile provider to be useful.
        Column('lat',         'REAL'),
        Column('lon',         'REAL'),
        Column('timezone',    'TEXT', nullable=False, default="''"),
        # WHO RUNS IT, which is not who owns what is inside. In a group the IT department
        # operates the site and the equipment belongs to the subsidiaries: both get asked, one
        # to bill and one to know who to call.
        Column('operator_uid', 'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        # Where it sits on the SITE MAP, which is not where it sits on the Earth. The map has
        # no tile provider on purpose — that would be a request to a third party from somebody
        # else's browser, and this panel is deployed where there is no way out — so the sites
        # are boxes somebody arranges. NULL means nobody has arranged this one, and then it is
        # placed from its coordinates: starting every site in a heap in one corner when the
        # latitude is right there throws away what somebody typed. Trailing, so an existing
        # database gets them by ADD COLUMN.
        Column('pos_x', 'REAL'),
        Column('pos_y', 'REAL'),
        # A QUIÉN SE LLAMA. Lo que se pregunta a las tres de la mañana delante de un mapa con un
        # punto rojo a cuatro horas de coche, y lo que ningún otro sitio de este panel contesta:
        # el operador dice qué SOCIEDAD lleva la sede, y una sociedad no abre una puerta. Dos
        # columnas y no una porque son dos cosas que se copian por separado —un nombre se lee y
        # un número se marca— y porque un teléfono suelto en un campo de texto libre no se puede
        # convertir en un enlace que llame.
        Column('contact', 'TEXT', nullable=False, default="''"),
        Column('phone', 'TEXT', nullable=False, default="''"),
        # Una foto del sitio. No es adorno: quien va a una sede por primera vez busca UNA puerta
        # en un polígono, y la diferencia entre una dirección y una foto de la fachada es no dar
        # dos vueltas a la manzana de noche. Se guarda como el plano de una sala —el nombre del
        # fichero, y el fichero en el almacén de imágenes— para que viaje en la copia de
        # seguridad por el mismo camino.
        Column('photo', 'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_site_name', ('name',)),),
)
