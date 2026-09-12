#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The power chain: ``dc_source`` (where it comes from), ``dc_pdu`` (the strips)
and ``dc_feed`` (what is plugged into what).

Three tables in one file because they are one question — *if branch A goes,
what turns off* — and nobody reads one of them alone."""

from __future__ import annotations

from lib.db.schema import Column, Index, TableSpec


#: Las ramas de alimentación. Dos y una tercera para lo que no cuelga de ninguna: un switch de
#: consola enchufado a la pared no está «en la rama A», está sin redundancia, y decir que sí lo
#: está es peor que no decir nada.
FEEDS = ('a', 'b', 'none')

#: Qué puede haber aguas arriba de una regleta. Un cuadro reparte; un SAI sostiene; una acometida
#: es donde acaba la responsabilidad de esta casa y empieza la de la compañía.
SOURCE_KINDS = ('mains', 'panel', 'ups', 'generator')

_SOURCE = TableSpec(
    name='dc_source',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        # Vive en una sede, no en una sala: un cuadro general alimenta varias salas, y atarlo a
        # una obligaría a inventar una copia por sala o a mentir sobre dónde está.
        Column('site_uid', 'TEXT', nullable=False, default="''"),
        Column('name',     'TEXT', nullable=False, default="''"),
        Column('kind',     'TEXT', nullable=False, default="'panel'"),
        # Quién lo alimenta a él. Vacío = es el principio de la cadena, que es lo que es una
        # acometida.
        Column('upstream_uid', 'TEXT', nullable=False, default="''"),
        # **Si ahora mismo se le está saltando.** No es una propiedad del cobre sino del
        # interruptor: la instalación «Cuadro → SAI → Cuadro → PDU» y la instalación «Cuadro →
        # PDU» del bypass son la MISMA, con el SAI dentro o fuera. Modelarlas como dos cadenas
        # obligaría a mantener dos verdades sobre el mismo cobre.
        #
        # Lo lleva el nodo que se salta —el SAI— aunque el interruptor esté físicamente en el
        # cuadro, que es lo normal; `bypass_at` dice dónde está para que la etiqueta cuadre con
        # lo que hay en la pared.
        Column('bypass',    'INTEGER', nullable=False, default='0'),
        Column('bypass_at', 'TEXT', nullable=False, default="''"),
        # Lo que aguanta y lo que sostiene. Los minutos son de la batería: sin ellos un SAI es
        # un nombre, y con ellos es «tengo ocho minutos para apagar cuarenta máquinas».
        Column('capacity_w',   'INTEGER', nullable=False, default='0'),
        Column('autonomy_min', 'INTEGER', nullable=False, default='0'),
        # Y si contesta. Un SAI gestionado dice si está en batería AHORA, que es la mitad
        # medida de todo esto.
        Column('host_uid', 'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_source_site', ('site_uid',)),),
)

#: El color de cada rama cuando la regleta no dice otro. Azul y rojo porque es como se etiqueta
#: en casi todas partes —y sobre todo porque son distinguibles de un vistazo desde la puerta de
#: la sala, que es desde donde se mira un armario cuando algo va mal—.
#:
#: Aquí y no en la hoja de estilos: el color de una rama es un dato del sitio, viaja a la
#: pantalla con el resto y quien exporte un plano se lo lleva. Una regleta puede llevar el suyo
#: —hay salas con tres ramas y con colores propios de la casa— y entonces manda el de la
#: regleta.
FEED_COLORS = {'a': '#2f6fed', 'b': '#d64545', 'none': '#6c757d'}

#: Y de qué categoría, que depende de de qué está hecho: las de cobre no valen para una fibra.
#: Servido con la respuesta y no escrito en la pantalla, como los colores de las ramas: una
#: segunda copia es la que se queda sin la categoría que se añada mañana.
#:
#: Abierto por abajo: lo que no esté en la lista se puede escribir igual. Una instalación con
#: cable de un fabricante que llama a lo suyo de otra manera no puede quedarse sin poder
#: apuntarlo, y una lista cerrada obliga a mentir o a dejarlo en blanco.
#: Y de qué categoría es un cable de CORRIENTE, que es el par de conectores que lleva: un C13
#: a C14 va de un equipo a una regleta y un C19 a C20 alimenta lo que pide dieciséis amperios.
#: Es lo que hay que mirar en la caja antes de bajar al armario, igual que la categoría de un
#: latiguillo de datos — y por eso vive al lado y se sirve igual.
#:
#: Abierta por abajo como la otra: una instalación con tomas de otro país no puede quedarse sin
#: poder apuntarlo.
FEED_CATEGORIES = ('c13-c14', 'c19-c20', 'c13-c20', 'c13-schuko', 'c19-schuko', 'iec-lock')

_PDU = TableSpec(
    name='dc_pdu',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        Column('rack_uid', 'TEXT', nullable=False),
        Column('name',     'TEXT', nullable=False, default="''"),
        # De qué rama cuelga. Es lo que decide qué se apaga cuando se cae un SAI, y por eso es
        # una columna y no una etiqueta suelta en el nombre.
        Column('feed',     'TEXT', nullable=False, default="'a'"),
        # Cuántas tomas tiene. De aquí sale «cuántas quedan», que es la pregunta que se hace
        # delante del armario con un equipo nuevo en las manos.
        Column('outlets',  'INTEGER', nullable=False, default='0'),
        # Lo que aguanta, en vatios. El límite del que hay que quedarse lejos, no el objetivo.
        Column('capacity_w', 'INTEGER', nullable=False, default='0'),
        # Una PDU gestionada ES un host: contesta por SNMP y dice cuántos amperios está dando
        # AHORA. Cuando lo es tenemos las dos mitades —lo declarado y lo medido— y el desacuerdo
        # entre ellas es la razón de que este panel exista.
        Column('host_uid', 'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
        # De qué color se pinta. Vacío = el de su rama, que es lo normal. Existe porque hay
        # salas con tres alimentaciones y salas donde el color de cada rama ya está decidido
        # desde antes de que llegara este panel, y discutir con la etiqueta que hay pegada en la
        # regleta de verdad es una discusión que el panel pierde.
        Column('color',    'TEXT', nullable=False, default="''"),
        # De qué cuadro o SAI cuelga. Vacío = nadie lo ha dicho, y entonces la cadena aguas
        # arriba de esta regleta es una pregunta sin respuesta — que es distinto de que no
        # tenga: media sala técnica cuelga de un cuadro que nadie ha documentado.
        Column('source_uid', 'TEXT', nullable=False, default="''"),
        # Y qué equipo del armario ES, cuando ocupa uno. Vacío es lo normal: la mayoría de las
        # regletas son verticales, van atornilladas al lateral y no ocupan U — por eso una
        # regleta puede existir sin equipo y por eso esto no es la misma tabla.
        #
        # Pero muchas sí ocupan, y entonces son UNA cosa descrita dos veces: una fila que dice
        # dónde está y otra que dice cuántas tomas tiene. Sin este enlace, el panel pedía
        # declararla dos veces y luego la contaba entre los equipos «sin enchufar» — pidiéndole
        # un enchufe a la regleta.
        #
        # Última columna: una que falta sólo se puede añadir con ADD COLUMN si va al final, que
        # es como una base que ya existe recibe ésta sin migración.
        Column('item_uid', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_pdu_rack', ('rack_uid',)),),
)

_POWER = TableSpec(
    name='dc_feed',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        # Un CABLE: este equipo come de esta regleta. Una fila por cable y no una columna en el
        # equipo, porque un equipo con una sola fila es justo el hallazgo — dos fuentes y solo
        # una enchufada, o las dos colgando de la misma rama.
        Column('item_uid', 'TEXT', nullable=False),
        Column('pdu_uid',  'TEXT', nullable=False),
        # En qué toma. 0 = «en esa regleta, no sé en cuál»: es lo que alguien sabe cuando mira
        # la foto de un armario, y obligarle a inventarse un número sería peor dato que ninguno.
        Column('outlet',   'INTEGER', nullable=False, default='0'),
        # Lo que ALGUIEN DIJO que consume por este cable. La placa de un servidor dice el máximo
        # que puede pedir, que no es lo que pide; se guarda lo escrito y se compara con lo que
        # mida la regleta, sin corregir ninguno de los dos.
        Column('watts_said', 'INTEGER', nullable=False, default='0'),
        Column('label',    'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
        # **Un cable de corriente es un cable.** Esta fila decía de qué toma cuelga y cuántos
        # vatios se declararon, y nada más — como si el latiguillo no existiera. Y existe: se
        # compra, se guarda en una caja, se rompe y hay que sustituirlo, y la pregunta de la
        # caja de repuestos es la misma que en datos: qué hay que llevarse.
        #
        # Las cuatro que ya tiene su hermano de datos, con los mismos nombres: dos tablas que
        # guardan lo mismo con nombres distintos son dos pantallas que se escriben dos veces.
        Column('asset',    'TEXT', nullable=False, default="''"),
        Column('category', 'TEXT', nullable=False, default="''"),
        Column('length_mm', 'INTEGER', nullable=False, default='0'),
        Column('description', 'TEXT', nullable=False, default="''"),
        # De qué color es la funda, como su hermano de datos y por lo mismo: es con lo que se
        # encuentra en un mazo de treinta detrás de un armario. La última, para que aparecer
        # sobre una tabla llena sea un `ADD COLUMN`.
        Column('color',    'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_feed_item', ('item_uid',)),
             Index('idx_dc_feed_pdu', ('pdu_uid',))),
)
