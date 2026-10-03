#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_item`` — what occupies U in a rack. Some items are devices; most are not."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: Which side of the rack an item occupies. `full` is the common case (a server fills its U
#: from both sides); the other two are what makes a real elevation possible.
FACES = ('full', 'front', 'rear')

#: Qué clase de dispositivo es. Cerrado, porque de aquí cuelgan decisiones y no solo un icono: lo que
#: **no contesta por naturaleza** deja de contarse como «sin vigilar», que es la diferencia entre
#: una pantalla que avisa y una que se ignora.
#:
#: `blank` es una tapa ciega: ocupa U a propósito, para que el aire no se cuele por el hueco. Es
#: inventario de verdad — sale en los pedidos — y es lo que más se olvida al documentar.
ITEM_ROLES = ('server', 'switch', 'router', 'firewall', 'storage', 'patch_panel',
              'fiber_panel', 'ups', 'pdu', 'shelf', 'kvm', 'console', 'blank', 'other')

#: Los que no contestan porque no tienen a qué: no es que estén sin vigilar, es que no hay nada
#: que vigilar. Contarlos entre los desatendidos llena la pantalla de deberes imposibles.
ROLES_MUDOS = ('patch_panel', 'fiber_panel', 'shelf', 'blank')

#: **Cómo está puesto algo en un armario.** Casi todo se atornilla a los mástiles y ocupa un
#: número de U; el resto no, y hasta ahora no cabía en el modelo — un SAI en el suelo al lado, un
#: cuadro en la pared, una regleta atornillada al lateral. Todo eso ocupa sitio, se alimenta, se
#: cablea y hay que ir a mirarlo, y lo único que no tiene es U.
#:
#: **Una sola decisión y no cinco casos particulares.** La regleta del lateral ya existía como
#: regleta y no como equipo, que es un caso particular con nombre propio; en cuanto hay un
#: segundo —el SAI— la pregunta de verdad se ve: qué significa estar en un armario sin ocupar U.
#: Se contesta una vez y valen los cinco.
#:
#: `u` es lo de siempre y es el valor por defecto: todo lo escrito antes de esta columna se
#: atornilló a los mástiles, que es lo que de verdad hizo.
PLACEMENTS = ('u', 'side', 'near')

_ITEM = TableSpec(
    name='dc_item',
    columns=(
        Column('uid',       'TEXT', primary_key=True),
        Column('rack_uid',  'TEXT', nullable=False),
        # The lowest U it occupies, in the rack's own numbering, and how many it takes.
        Column('u_start',   'INTEGER', nullable=False, default='1'),
        Column('u_height',  'INTEGER', nullable=False, default='1'),
        Column('face',      'TEXT', nullable=False, default="'full'"),
        # The registry's device, when there is one. Optional on purpose: most of what fills a
        # rack answers to nothing.
        Column('device_uid',  'TEXT', nullable=False, default="''"),
        # The catalogue model, when one was matched.
        Column('type_uid',  'TEXT', nullable=False, default="''"),
        # What is written on the front of it, which is what somebody reads with a torch.
        Column('label',     'TEXT', nullable=False, default="''"),
        Column('serial',    'TEXT', nullable=False, default="''"),
        Column('asset',     'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('depth_mm',  'INTEGER', nullable=False, default='0'),
        # Qué CLASE de dispositivo es — uno de `ITEM_ROLES`. Vacío = nadie lo ha dicho, que es
        # distinto de `other`: lo primero es una pregunta y lo segundo una respuesta.
        #
        # De aquí cuelga que un panel de parcheo deje de contarse como «sin vigilar»: no es que
        # nadie lo mire, es que no hay nada que mirar. Contarlos entre los desatendidos llena la
        # pantalla de deberes imposibles y enseña a ignorarla.
        Column('role',      'TEXT', nullable=False, default="''"),
        # De qué PLANTILLA nació (`dc_build`), que no es lo mismo que lo que lleva hoy. Las
        # piezas se copian al crearlo y desde ese momento son suyas; esto solo recuerda de dónde
        # salió, y es lo que contesta «cuáles son los veinte del estándar de 2024» aunque a tres
        # les hayan cambiado los discos.
        Column('build_uid', 'TEXT', nullable=False, default="''"),
        # Lo que solo tiene ESTA caja y ningún modelo ni plantilla puede saber. Como texto ISO
        # (`2026-08-28`) y no como fecha nativa: son tres motores con tres tipos de fecha, y lo
        # único que se hace con esto es ordenarlo y compararlo, que en ISO es lo mismo.
        Column('purchased_at', 'TEXT', nullable=False, default="''"),
        Column('warranty_until', 'TEXT', nullable=False, default="''"),
        Column('supplier', 'TEXT', nullable=False, default="''"),
        # En cuántas partes se divide el U que ocupa, y cuál de ellas toma. `1/1` es lo de
        # siempre —el U entero— y es lo que recibe todo lo que ya estaba, así que esta columna
        # llega por `ADD COLUMN` y no cambia ni una fila.
        #
        # Un número y no un enum de «arriba / abajo / izquierda / derecha»: en cuántas se parte
        # lo decide quien monta. Dos para un patch panel de 0,5 U, ocho para la bandeja de
        # Raspberry. Y sirve para las dos formas de partir un U —a lo alto y a lo ancho— porque
        # a la rejilla le da igual: lo que necesita saber es qué trozo está ocupado.
        Column('u_slots',    'INTEGER', nullable=False, default='1'),
        Column('u_slot',     'INTEGER', nullable=False, default='1'),
        Column('u_slot_span', 'INTEGER', nullable=False, default='1'),
        # Por dónde se parte ese U: `width` (uno al lado del otro, dos mini PC o una bandeja de
        # ocho Raspberry) o `height` (uno encima del otro, dos patch panel de 0,5 U). A la
        # rejilla le da igual —lo que comprueba es si el trozo está libre— pero al DIBUJO no:
        # existe para parecerse a lo que se ve al abrir el armario.
        Column('u_split',    'TEXT', nullable=False, default="'width'"),
        # Montado EN otro elemento: los mini PC sobre una bandeja, la tarjeta en un chasis. El
        # que lo lleva ocupa el U; el montado no, porque ese U ya está pagado.
        Column('parent_uid', 'TEXT', nullable=False, default="''"),
        # **Cómo está puesto**: uno de `PLACEMENTS`. `u` —lo de siempre— se atornilla a los
        # mástiles y ocupa `u_start`..`u_height`; `side` está dentro del armario sin ocupar U
        # (la regleta del lateral, la bandeja de fibra colgada) y `near`, al lado (el SAI en el
        # suelo, el cuadro en la pared).
        #
        # Lo que no ocupa U sigue estando EN el armario para todo lo demás: se alimenta, se
        # cablea, tiene estado y hay que ir a mirarlo. Lo único que no hace es quitarle el sitio
        # a nada — y por eso no entra en la ocupación ni en el alzado.
        #
        # La última, para que aparecer sobre una tabla llena sea un `ADD COLUMN`.
        Column('placement', 'TEXT', nullable=False, default="'u'"),
        # How deep this thing is. Not in the catalogue: devicetype-library says whether a model
        # is full depth and never how many millimetres, so this is somebody's tape measure or
        # the vendor's sheet — and without it the rack can still say what it HAS, which is what
        # a person standing in front of it with a box wants to know.
        #
        # Last, because a missing column can only be added by ADD COLUMN when it is trailing,
        # which is how an existing database gets this one without a migration.
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_item_rack', ('rack_uid',)),
             Index('idx_dc_item_device', ('device_uid',)),
             Index('idx_dc_item_parent', ('parent_uid',)),
             Index('idx_dc_item_build', ('build_uid',))),
)
