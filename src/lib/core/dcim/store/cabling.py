#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_cable`` — a cable between two ends — and ``dc_link``, the same
question one level up: what joins two sites."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: De qué es un cable. No es decoración: un latiguillo de cobre y una fibra monomodo no se
#: cambian igual ni se piden igual, y en la caja de repuestos hay de uno y no del otro.
CABLE_KINDS = ('copper', 'fiber', 'dac', 'power', 'console', 'other')

CABLE_CATEGORIES = {
    'copper': ('cat5e', 'cat6', 'cat6a', 'cat7', 'cat8'),
    'fiber': ('om1', 'om2', 'om3', 'om4', 'om5', 'os1', 'os2'),
    # Con su prefijo: `passive` a secas ya es una palabra de esta sección —el flujo de aire
    # de un chasis— y el traductor de valores va por el valor, así que un DAC pasivo y un
    # chasis de refrigeración pasiva acabarían compartiendo palabra. Comparten letras y no
    # significado, que es la peor clase de colisión: no falla, traduce mal.
    'dac': ('dac-passive', 'dac-active'),
}

#: De qué COLOR es un latiguillo, con los que se compran. El color de un cable no es decoración:
#: es con lo que se encuentra en un mazo de treinta y con lo que se respeta el código de la casa
#: —amarillo lo que sale fuera, rojo lo que no se toca—, y elegirlo de una rueda de dieciséis
#: millones deja la instalación con nueve azules que no son el mismo azul.
#:
#: Aquí y no en la pantalla, como las categorías y como los colores de las ramas: una segunda
#: copia es la que se queda sin el color que se añada mañana. Y **abierto por abajo**: el que
#: quiera un color que no está lo escribe con la rueda de siempre, que sigue al lado.
#:
#: El nombre es una CLAVE y no un texto: se traduce donde se enseña. Un desplegable con «yellow»
#: en un panel en castellano es la mitad de una traducción.
CABLE_COLORS = (('black', '#111827'), ('white', '#f9fafb'), ('grey', '#6b7280'),
                ('blue', '#2563eb'), ('red', '#dc2626'), ('green', '#16a34a'),
                ('yellow', '#eab308'), ('orange', '#f97316'), ('purple', '#a855f7'),
                ('cyan', '#06b6d4'), ('pink', '#ec4899'), ('brown', '#92400e'))

#: De qué clase es un enlace entre sedes. Importa para la redundancia de verdad: dos VPN sobre
#: la misma línea de internet no son dos caminos, y el mapa tiene que poder decirlo.
LINK_KINDS = ('mpls', 'ipsec', 'sdwan', 'fiber', 'internet', 'other')

_CABLE = TableSpec(
    name='dc_cable',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        # Los dos extremos son ITEMS y no máquinas. Un panel de parcheo no contesta a nada y es
        # donde acaba la mitad de los cables de una sala: exigir una máquina haría inexpresable
        # justo el cable que se documenta a mano, porque nadie más lo va a saber.
        Column('a_item',   'TEXT', nullable=False),
        Column('a_port',   'TEXT', nullable=False, default="''"),
        Column('b_item',   'TEXT', nullable=False),
        Column('b_port',   'TEXT', nullable=False, default="''"),
        Column('kind',     'TEXT', nullable=False, default="'copper'"),
        # Lo que pone en la etiqueta, que es lo que alguien lee con una linterna a las tres de
        # la mañana. Se guarda aparte del uid porque la etiqueta se puede repetir, se puede
        # borrar y se puede equivocar — y aun así es el dato con el que trabaja quien está allí.
        Column('label',    'TEXT', nullable=False, default="''"),
        Column('color',    'TEXT', nullable=False, default="''"),
        Column('length_mm', 'INTEGER', nullable=False, default='0'),
        Column('description', 'TEXT', nullable=False, default="''"),
        # De qué CATEGORÍA es, que no es lo mismo que de qué está hecho: `kind` dice cobre o
        # fibra y esto dice Cat 6A o OM4. La diferencia decide si un enlace de 10 Gb va a
        # funcionar, y es lo que hay que mirar en la caja de repuestos antes de bajar al armario
        # — un latiguillo de Cat 5e y uno de Cat 6A son indistinguibles a un metro.
        #
        Column('category', 'TEXT', nullable=False, default="''"),
        # El número de INVENTARIO, que no es la etiqueta. `label` es lo que está rotulado en el
        # propio cable: se repite, se borra, se equivoca — y aun así es con lo que trabaja quien
        # está allí con una linterna. Esto lo pone la casa, es único y es con lo que se
        # estandariza: cuántos hay, cuáles se compraron juntos, cuál toca sustituir. Meter los
        # dos en una casilla obliga a elegir cuál de los dos se pierde.
        #
        # Las últimas, para que aparecer sobre una tabla llena sea un `ADD COLUMN`.
        Column('asset', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_cable_a', ('a_item',)),
             Index('idx_dc_cable_b', ('b_item',))),
)

_LINK = TableSpec(
    name='dc_link',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        # Los dos extremos son SEDES: un enlace une sitios, y eso es lo que hay que dibujar.
        Column('a_site',   'TEXT', nullable=False),
        Column('b_site',   'TEXT', nullable=False),
        # …y opcionalmente el equipo que lo termina en cada punta. Sin él no hay nada que
        # contrastar: un circuito no tiene estado, lo tiene el router que lo termina.
        Column('a_item',   'TEXT', nullable=False, default="''"),
        Column('b_item',   'TEXT', nullable=False, default="''"),
        Column('kind',     'TEXT', nullable=False, default="'ipsec'"),
        # Quién lo vende y con qué referencia. El `circuit_id` es lo único de esta tabla que no
        # se puede deducir de ninguna otra parte: es lo que hay que decir por teléfono a las
        # tres de la mañana, y sin él la avería empieza buscando un correo de hace dos años.
        Column('provider', 'TEXT', nullable=False, default="''"),
        Column('circuit_id', 'TEXT', nullable=False, default="''"),
        Column('bandwidth_mbps', 'INTEGER', nullable=False, default='0'),
        # Por dónde va físicamente, cuando alguien lo sabe. Dos operadores distintos por la
        # misma zanja no son dos caminos, y esa es la redundancia que se descubre el día que una
        # excavadora pasa por allí.
        Column('path',     'TEXT', nullable=False, default="''"),
        Column('label',    'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_link_a', ('a_site',)),
             Index('idx_dc_link_b', ('b_site',))),
)
