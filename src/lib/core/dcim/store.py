#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where the equipment is, and whose it is — the tables and the reads over them.

Six tables, and the shape of them is the whole design (see ``docs/explica-dcim.md`` §2):

* **``dc_site`` → ``dc_room`` → ``dc_rack`` → ``dc_item``** is *containment*, and it is strictly
  nested: everything is somewhere, and somewhere is exactly one place.
* **``dc_org`` + ``dc_owner``** is *ownership*, and it is not a container at all. A holding's IT
  department shares a datacenter, a room and a rack between the group's companies; one cabinet
  holds 2U of one, 4U of another and a switch of the department's own. Ownership is therefore an
  attribute said at whatever level somebody knows it, inherited downwards, most specific wins.

**Why ``dc_owner`` is a table and not a column in five places.** The rule — say it where you
like, it inherits, the innermost wins — is ONE rule, and written as an ``org_uid`` column on
five tables it is five implementations of it and five places to get it wrong. As a table there
is one resolver (:mod:`lib.core.dcim.owners`). It also admits scopes that are not in the
containment chain at all: a host with no rack, a VM, a VIP — all of them belong to somebody.

**A rack holds ITEMS, and some items are hosts** — never the reverse. A patch panel takes 1U and
is not a host; a blanking plate is nothing; a blade chassis takes 7U and contains eight things
that are; a switched-off server occupies its U whether or not anything monitors it. So
``dc_item.host_uid`` is optional and ``hosts`` is not touched: either side survives the other
being deleted, which is the point of not putting ``rack_uid`` on the host record.

**The face is part of the position.** A 1U device fills U 12 front *and* rear; a patch panel may
fill only the rear; two half-depth devices share one U from opposite sides. Without it the
elevation of a real rack is wrong within a week, and "is this U free" has no answer.
"""

from __future__ import annotations

from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

# ── What a thing can be, for the ownership table and for the item's face ─────────────────
#: The scopes ownership can be declared on. The four containment levels, plus `host` for the
#: things that are somebody's and are in no rack — a VM, a VIP, a machine on a desk.
OWNER_SCOPES = ('site', 'room', 'rack', 'item', 'host')

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

#: De qué puede ser un componente. `accessory` es el cargador del mini-PC, el latiguillo corto que
#: vive con él, el kit de raíles — cosas que no son elegantes y son exactamente las que faltan
#: cuando alguien las necesita.
PART_KINDS = ('disk', 'ssd', 'memory', 'cpu', 'nic', 'hba', 'gpu', 'psu', 'fan',
              'transceiver', 'battery', 'module', 'accessory', 'other')

#: The sides of a rack somebody can reach. Stored as the FACT — which sides are reachable — and
#: not as a kind of cabinet: two identical racks, one in the middle of an aisle and one bolted to
#: a wall, are not worked on the same way, and the difference is where it stands rather than what
#: it is. The screen offers the usual arrangements as shortcuts that fill this in.
SIDES = ('front', 'rear', 'left', 'right')

#: How a room is cooled, when somebody has said. `''` means nobody has — which is not the same
#: as `none`, and the difference matters when reading a room that runs hot.
COOLING = ('', 'none', 'room', 'cold_aisle', 'hot_aisle', 'in_row', 'rear_door', 'split')

_ORG = TableSpec(
    name='dc_org',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        # A short form for badges and elevations, where the full legal name of a company does
        # not fit in a box 200 pixels wide.
        Column('short',       'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_org_name', ('name',)),),
)

_OWNER = TableSpec(
    name='dc_owner',
    columns=(
        # One row per ownership somebody DECLARED. Everything else is inherited, and inherited
        # ownership is never written down — the day somebody re-parents a rack, a stored copy
        # of what it used to inherit is a lie that outlives the move.
        Column('scope',   'TEXT', nullable=False),      # one of OWNER_SCOPES
        Column('uid',     'TEXT', nullable=False),      # the thing that belongs to somebody
        Column('org_uid', 'TEXT', nullable=False),
        Column('set_at',  'TEXT', nullable=False, default="''"),
        Column('set_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_owner_scope', ('scope', 'uid'), unique=True),
             Index('idx_dc_owner_org', ('org_uid',))),
)

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
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
        # Where it sits on the SITE MAP, which is not where it sits on the Earth. The map has
        # no tile provider on purpose — that would be a request to a third party from somebody
        # else's browser, and this panel is deployed where there is no way out — so the sites
        # are boxes somebody arranges. NULL means nobody has arranged this one, and then it is
        # placed from its coordinates: starting every site in a heap in one corner when the
        # latitude is right there throws away what somebody typed. Trailing, so an existing
        # database gets them by ADD COLUMN.
        Column('pos_x', 'REAL'),
        Column('pos_y', 'REAL'),
    ),
    indexes=(Index('idx_dc_site_name', ('name',)),),
)

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

#: Lo alto que es una sala cuando nadie lo ha dicho. Tres metros es lo normal en una sala
#: técnica; se usa para el techo y para las columnas, que van de suelo a techo por definición.
ROOM_HEIGHT_MM = 3000

#: Las capas, de abajo arriba. El orden ES el dato: quien dibuje recorre esto y no inventa.
FEATURE_LAYERS = ('floor', 'room', 'air')

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
    ),
    indexes=(Index('idx_dc_feed_item', ('item_uid',)),
             Index('idx_dc_feed_pdu', ('pdu_uid',))),
)

#: De qué es un cable. No es decoración: un latiguillo de cobre y una fibra monomodo no se
#: cambian igual ni se piden igual, y en la caja de repuestos hay de uno y no del otro.
CABLE_KINDS = ('copper', 'fiber', 'dac', 'power', 'console', 'other')

#: De qué clase es un enlace entre sedes. Importa para la redundancia de verdad: dos VPN sobre
#: la misma línea de internet no son dos caminos, y el mapa tiene que poder decirlo.
LINK_KINDS = ('mpls', 'ipsec', 'sdwan', 'fiber', 'internet', 'other')

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
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_cable_a', ('a_item',)),
             Index('idx_dc_cable_b', ('b_item',))),
)

_PART = TableSpec(
    name='dc_part',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        Column('item_uid', 'TEXT', nullable=False),
        Column('kind',     'TEXT', nullable=False, default="'other'"),
        # Cómo se llama en la máquina: «bahía 3», «DIMM A1», «PSU 2». Es lo que hay que decirle
        # a quien está delante con un destornillador, y no siempre coincide con nada del modelo.
        Column('slot',     'TEXT', nullable=False, default="''"),
        Column('model',    'TEXT', nullable=False, default="''"),
        Column('serial',   'TEXT', nullable=False, default="''"),
        # El tamaño como TEXTO: «4 TB», «32 GB», «10 GbE», «750 W». Guardarlo en bytes obligaría
        # a decidir si un disco de 4 TB son 4·10¹² o 4·2⁴⁰ —y las dos respuestas están en algún
        # albarán— y a convertir para enseñar lo que alguien ya escribió bien.
        Column('size',     'TEXT', nullable=False, default="''"),
        # Cuántos iguales. Seis discos idénticos son una fila con un seis, no seis filas: nadie
        # apunta el número de serie de cada uno, y obligar a ello es garantizar que no se apunte
        # ninguno.
        Column('qty',      'INTEGER', nullable=False, default='1'),
        Column('description', 'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
        # De qué modelo del catálogo es, cuando alguien lo dijo. Opcional a propósito: el disco
        # que salió del cajón no está en ningún catálogo y sigue siendo un disco. Lo que da es
        # poder preguntar «cuántos KSM32RD8/32 hay puestos» sin depender de que las once formas
        # de escribir el mismo modelo coincidan.
        #
        # La última, para que aparecer sobre una tabla llena sea un `ADD COLUMN`.
        Column('type_uid', 'TEXT', nullable=False, default="''"),
        # La MARCA, aparte del modelo. «Samsung PM9A3» en una sola casilla son once formas de
        # escribir lo mismo que no se pueden contar juntas — y contar juntas es la única
        # pregunta que se le hace a esto: cuántos de estos tengo y en qué máquinas.
        #
        # Como texto y no como `brand_uid`, igual que `dc_type.manufacturer`: es lo que se dijo
        # de esta pieza, y sigue siendo cierto si alguien retira la ficha de la marca. El
        # vínculo bueno lo tiene el modelo del catálogo, que es a quien apunta `type_uid`.
        Column('brand', 'TEXT', nullable=False, default="''"),
        # Cuántas piezas trae una unidad de lo que se compró. Estampada como lo demás: una
        # máquina que dice llevar dos kits sigue diciendo cuántos módulos son aunque alguien
        # borre el modelo del catálogo.
        Column('kit_qty', 'INTEGER', nullable=False, default='1'),
        # Dentro de la caja o colgando de ella. Se estampa desde la plantilla como lo demás: el
        # adaptador de red que el estándar dice que lleva sigue siendo externo en la máquina que
        # sale de él, y el día de la mudanza eso es lo que hay que acordarse de meter en la caja.
        Column('mount',   'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_part_item', ('item_uid',)),),
)

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
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_feature_room', ('room_uid',)),),
)

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
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_rack_room', ('room_uid',)),),
)

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
        Column('host_uid',  'TEXT', nullable=False, default="''"),
        # The catalogue model, when one was matched.
        Column('type_uid',  'TEXT', nullable=False, default="''"),
        # What is written on the front of it, which is what somebody reads with a torch.
        Column('label',     'TEXT', nullable=False, default="''"),
        Column('serial',    'TEXT', nullable=False, default="''"),
        Column('asset',     'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
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
    ),
    indexes=(Index('idx_dc_item_rack', ('rack_uid',)),
             Index('idx_dc_item_host', ('host_uid',)),
             Index('idx_dc_item_parent', ('parent_uid',)),
             Index('idx_dc_item_build', ('build_uid',))),
)

SCHEMAS = (_ORG, _OWNER, _SITE, _ROOM, _RACK, _ITEM, _FEATURE, _PDU, _POWER, _CABLE,
           _LINK, _ROW, _SOURCE, _PART)


#: Las familias de puerto que se nombran. Las mismas nueve del catálogo y del documento de
#: conectores: una escrita a mano que no esté aquí sería una lista que ninguna pantalla dibuja.
PORT_FAMILIES = ('interfaces', 'power-ports', 'power-outlets', 'console-ports',
                 'console-server-ports', 'front-ports', 'rear-ports', 'module-bays',
                 'device-bays')

#: Cuántas bocas se nombran como mucho por familia. Un chasis de verdad no llega; el tope está
#: para que nadie meta cien mil entradas en una columna. Lo que se pierde es detalle, nunca el
#: recuento — que se cuenta aparte y no tiene tope.
PORT_LIST_MAX = 512

#: El tope de vatios de una toma. Un rack entero no llega; está para que un cero de más no
#: convierta una suma de consumos en una cifra que nadie mira dos veces.
WATTS_MAX = 100000

#: Y cuántas señales caben en un puerto. Un USB-C lleva datos, vídeo y corriente a la vez; ocho
#: es más de lo que existe y sigue siendo una lista que se lee de un vistazo.
PORT_SIGNALS_MAX = 8


def clean_port_list(value) -> dict:
    """``{familia: [{'name', 'type', 'gen', 'signals'}, …]}`` — lo que se guarda, y nada más.

    **En la puerta y no en la pantalla**: lo que llega es un JSON del navegador, y guardarlo tal
    cual es guardar lo que mande quien sepa escribir una petición. Lo que no se reconoce se cae
    aquí, donde se puede decir por qué, y no tres pantallas más allá donde solo se ve un hueco.

    Sin nombre no hay entrada: el nombre es lo que se guarda y lo que cruza con el componente que
    va en ese hueco. Una lista de guiones no dice nada que el recuento no diga mejor.

    El orden se respeta —`gi10` va detrás de `gi9` en el equipo y delante alfabéticamente— y los
    campos vacíos no se escriben: un `gen: ''` es una generación que alguien tendría que
    interpretar, y no hay nada que interpretar.
    """
    fuera: dict = {}
    if not isinstance(value, dict):
        return fuera
    for fam in PORT_FAMILIES:
        filas = value.get(fam)
        if not isinstance(filas, list) or not filas:
            continue
        lista = []
        for x in filas:
            if not isinstance(x, dict):
                continue
            nombre = str(x.get('name') or '').strip()[:120]
            if not nombre:
                continue
            uno = {'name': nombre, 'type': str(x.get('type') or '').strip()[:60]}
            gen = str(x.get('gen') or '').strip()[:60]
            if gen:
                uno['gen'] = gen
            # Abiertas a propósito: una señal que no esté en el vocabulario se conserva y se
            # enseña tal cual, que es lo que deja ampliar el documento sin tocar el panel.
            senales = []
            for sig in (x.get('signals') or ()):
                sig = str(sig or '').strip()[:40]
                if sig and sig not in senales:
                    senales.append(sig)
            if senales:
                uno['signals'] = senales[:PORT_SIGNALS_MAX]
            # El voltaje como texto —lo que pone en la etiqueta es `100-240 V`, un rango— y los
            # vatios como número, que son los que se suman para saber cuánto pide un armario.
            volt = str(x.get('volts') or '').strip()[:24]
            if volt:
                uno['volts'] = volt
            try:
                vat = int(float(x.get('watts') or 0))
            except (TypeError, ValueError):
                vat = 0
            if 0 < vat <= WATTS_MAX:
                uno['watts'] = vat
            lista.append(uno)
            if len(lista) >= PORT_LIST_MAX:
                break
        if lista:
            fuera[fam] = lista
    return fuera


def _slot_of(item) -> tuple:
    """En qué trozo del U está esto: ``(desde, hasta, de_cuántos)``, en enteros.

    Lo de siempre —el U entero— es ``(0, 1, 1)``, y es lo que sale de una fila que no diga nada:
    todo lo que se escribió antes de que un U pudiera partirse ocupa el U entero, que es lo que
    de verdad ocupaba.

    En enteros y no en fracciones decimales porque `1/3` no existe en coma flotante, y dos cosas
    que *casi* encajan es exactamente el dibujo que no puede existir.
    """
    d = item if isinstance(item, dict) else {}
    try:
        de = max(1, int(d.get('u_slots') or 1))
        cual = int(d.get('u_slot') or 1)
        cuantos = max(1, int(d.get('u_slot_span') or 1))
    except (TypeError, ValueError):
        return (0, 1, 1)
    # Uno fuera de rango ocupa el U entero: es lo seguro. Decir que un trozo que no existe está
    # libre dejaría meter algo encima de lo que hay.
    if cual < 1 or cual > de or cual - 1 + cuantos > de:
        return (0, 1, 1)
    return (cual - 1, cual - 1 + cuantos, de)


def _overlap(a: tuple, b: tuple) -> bool:
    """Si dos trozos de un mismo U se pisan. Multiplicando en cruz, sin dividir nunca."""
    (a0, a1, an), (b0, b1, bn) = a, b
    return a0 * bn < b1 * an and b0 * an < a1 * bn


class Rows(BaseStore):
    """One table's worth of ordinary bookkeeping.

    Six tables that differ in their columns and not at all in what is done to them: list, get,
    create, update, delete. Written out six times that is five copies of "how a row becomes a
    dict" — and the copy somebody forgets to update is the one that silently drops a column.

    Public rather than private because :mod:`lib.core.dcim.builds` keeps its two tables the same
    way. Two more copies of the same five methods, in another file, would be the exact thing
    this class exists to stop — and one behind a leading underscore is a copy waiting to happen.
    """

    def __init__(self, db: BaseConnector, spec: TableSpec) -> None:
        super().__init__(db)
        self._spec = spec
        self._TABLE = spec.name
        self._cols = tuple(c.name for c in spec.columns)

    def bootstrap(self) -> None:
        self._db.reconcile_table(self._spec)

    def _row(self, row) -> dict:
        return {name: row[i] for i, name in enumerate(self._cols)}

    def list(self, where: str = '', params: tuple = ()) -> list[dict]:
        sql = f'SELECT {", ".join(self._cols)} FROM {self._sql_table}'
        if where:
            sql += f' WHERE {where}'
        return [self._row(r) for r in (self._db.fetchall(sql, params) or ())]

    def get(self, uid: str) -> dict | None:
        rows = self.list('uid = ?', (str(uid or ''),))
        return rows[0] if rows else None

    def create(self, data: dict, *, actor: str = '') -> str:
        uid = str(data.get('uid') or new_uid())
        values = dict(data)
        values.update({'uid': uid, 'created_at': BaseStore._now(), 'updated_at': BaseStore._now(),
                       'updated_by': str(actor or '')})
        cols = [c for c in self._cols if c in values]
        self._db.execute(
            f'INSERT INTO {self._sql_table} ({", ".join(cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})',
            tuple(values[c] for c in cols))
        self._db.commit()
        self._stamp()
        return uid

    def update(self, uid: str, data: dict, *, actor: str = '') -> bool:
        values = {k: v for k, v in (data or {}).items()
                  if k in self._cols and k not in ('uid', 'created_at')}
        if not values:
            return False
        values['updated_at'] = BaseStore._now()
        values['updated_by'] = str(actor or '')
        cols = list(values)
        self._db.execute(
            f'UPDATE {self._sql_table} SET {", ".join(f"{c} = ?" for c in cols)} WHERE uid = ?',
            tuple(values[c] for c in cols) + (str(uid or ''),))
        self._db.commit()
        self._stamp()
        return True

    def delete(self, uid: str) -> bool:
        self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (str(uid or ''),))
        self._db.commit()
        self._stamp()
        return True

    def _stamp(self) -> None:
        try:
            self.stamp()
        except Exception:                       # pylint: disable=broad-except
            pass                                # freshness is a hint, never a write barrier


class DcimStore:
    """The physical inventory: the containment chain, and who owns what.

    One store over six tables rather than six stores, because the questions that matter cross
    them — "what is in this rack", "is this U free", "whose is this" — and a caller holding six
    stores would be the one joining them.
    """

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self.orgs = Rows(db, _ORG)
        self.owners = Rows(db, _OWNER)
        self.sites = Rows(db, _SITE)
        self.rooms = Rows(db, _ROOM)
        self.racks = Rows(db, _RACK)
        self.items = Rows(db, _ITEM)
        self.features = Rows(db, _FEATURE)
        self.pdus = Rows(db, _PDU)
        self.feeds = Rows(db, _POWER)
        self.cables = Rows(db, _CABLE)
        self.links = Rows(db, _LINK)
        self.rows = Rows(db, _ROW)
        self.sources = Rows(db, _SOURCE)
        self.parts = Rows(db, _PART)
        self._bootstrap()

    def _bootstrap(self) -> None:
        """Reconciliar TODAS las tablas de este store, sin nombrar ninguna.

        Nombrarlas era una lista que había que acordarse de tocar, y no acordarse no daba ningún
        error al arrancar: daba un «no such table» la primera vez que alguien usara lo nuevo, que
        puede ser semanas después y en la instalación de otro. Una declaración que hay que
        repetir en dos sitios es media declaración.
        """
        for part in vars(self).values():
            if isinstance(part, Rows):
                part.bootstrap()

    # ── The containment chain, read downwards ─────────────────────────────────

    def rooms_of(self, site_uid: str) -> list[dict]:
        return self.rooms.list('site_uid = ?', (str(site_uid or ''),))

    def racks_of(self, room_uid: str) -> list[dict]:
        return self.racks.list('room_uid = ?', (str(room_uid or ''),))

    def parts_of(self, item_uids) -> list[dict]:
        """Los componentes de estos equipos. Varios de golpe porque un armario se mira entero.

        Ordenados por clase y hueco: quien abre esto busca «los discos» o «la bahía 3», y una
        lista en el orden en que se tecleó obliga a leerla toda.
        """
        uids = [str(u) for u in (item_uids or ()) if u]
        if not uids:
            return []
        marcas = ', '.join('?' for _ in uids)
        filas = self.parts.list(f'item_uid IN ({marcas})', tuple(uids))
        return sorted(filas, key=lambda p: (str(p.get('kind') or ''), str(p.get('slot') or '')))

    def sources_of(self, site_uid: str = '') -> list[dict]:
        """Las fuentes de una sede, o todas. Por nombre, que es como se las llama."""
        filas = (self.sources.list('site_uid = ?', (str(site_uid),))
                 if site_uid else self.sources.list())
        return sorted(filas, key=lambda f: str(f.get('name') or ''))

    def rows_of(self, room_uid: str) -> list[dict]:
        """Las filas de una sala, por nombre — que es como se las llama."""
        filas = self.rows.list('room_uid = ?', (str(room_uid or ''),))
        return sorted(filas, key=lambda f: str(f.get('name') or ''))

    def links_of(self, site_uids=None) -> list[dict]:
        """Los enlaces entre sedes. Sin filtro, todos: el mapa los quiere todos a la vez.

        Con filtro, los que tocan a alguna de esas sedes **por cualquiera de sus dos puntas** —
        un enlace es de las dos, y preguntar por una sola haría que la mitad no apareciese en la
        mitad de las pantallas.
        """
        if site_uids is None:
            return self.links.list()
        uids = [str(u) for u in site_uids if u]
        if not uids:
            return []
        marcas = ', '.join('?' for _ in uids)
        return self.links.list(f'a_site IN ({marcas}) OR b_site IN ({marcas})',
                               tuple(uids) * 2)

    def cables_of(self, item_uids) -> list[dict]:
        """Los cables que tocan a alguno de estos equipos, por cualquiera de sus dos extremos.

        Por los dos: un cable que sale de este armario y acaba en otro es del armario de todas
        formas —hay que documentarlo desde donde se ve—, y preguntar solo por un extremo haría
        que la mitad de los cables no apareciesen en la mitad de las pantallas.
        """
        uids = [str(u) for u in (item_uids or ()) if u]
        if not uids:
            return []
        marcas = ', '.join('?' for _ in uids)
        return self.cables.list(f'a_item IN ({marcas}) OR b_item IN ({marcas})',
                                tuple(uids) * 2)

    def pdus_of(self, rack_uid: str) -> list[dict]:
        """Las regletas de un armario, la rama A antes que la B."""
        rows = self.pdus.list('rack_uid = ?', (str(rack_uid or ''),))
        return sorted(rows, key=lambda p: (str(p.get('feed') or 'z'), str(p.get('name') or '')))

    def feeds_of(self, pdu_uids) -> list[dict]:
        """Los cables que cuelgan de estas regletas.

        Por regleta y no por equipo porque la pregunta que se hace es siempre del armario para
        abajo: qué come de aquí. Preguntar por equipo devuelve lo mismo al revés y obliga a
        recorrer el armario dos veces.
        """
        uids = [str(u) for u in (pdu_uids or ()) if u]
        if not uids:
            return []
        marcas = ', '.join('?' for _ in uids)
        return self.feeds.list(f'pdu_uid IN ({marcas})', tuple(uids))

    def features_of(self, room_uid: str) -> list[dict]:
        """Lo que hay en la sala que no es un rack, en el orden en que se dibuja.

        Ordenado aquí y no en el navegador: el orden de las capas es una propiedad del modelo
        —un pasillo va debajo y una bandeja por el aire— y dejarlo a quien pinte significa que
        la próxima pantalla que dibuje una sala lo tenga que volver a acertar.
        """
        rows = self.features.list('room_uid = ?', (str(room_uid or ''),))
        def _peso(row):
            kind = FEATURE_KINDS.get(str(row.get('kind') or ''))
            capa = (kind or {}).get('layer', 'room')
            return FEATURE_LAYERS.index(capa) if capa in FEATURE_LAYERS else 1
        return sorted(rows, key=_peso)

    def items_of(self, rack_uid: str) -> list[dict]:
        return self.items.list('rack_uid = ?', (str(rack_uid or ''),))

    def items_of_build(self, build_uid: str) -> list[dict]:
        """Los equipos que salieron de una plantilla.

        Es lo que convierte un estándar de compra en algo que se puede mantener: sin saber a
        cuántas máquinas afecta, una plantilla es una nota en un documento — que es de donde se
        viene. También es lo que hace que borrarla pueda avisar en vez de callarse.
        """
        if not str(build_uid or ''):
            return []
        return self.items.list('build_uid = ?', (str(build_uid),))

    def item_of_host(self, host_uid: str) -> dict | None:
        rows = self.items.list('host_uid = ?', (str(host_uid or ''),))
        return rows[0] if rows else None

    # ── …and upwards, which is what ownership and "where do I walk" both need ──

    def chain_of(self, scope: str, uid: str) -> list[tuple]:
        """``[(scope, uid), …]`` from *uid* up to its site, innermost first.

        Every read that has to answer "whose is this" or "where is this" walks the same chain,
        so it is built once here. A broken link — a rack whose room was deleted — ends the walk
        instead of raising: an orphan is a real state of the data and the answer for it is
        "nobody knows", not a 500.
        """
        out: list[tuple] = []
        scope, uid = str(scope or ''), str(uid or '')
        seen = set()
        while scope and uid and (scope, uid) not in seen:
            out.append((scope, uid))
            seen.add((scope, uid))
            if scope == 'item':
                row = self.items.get(uid)
                scope, uid = 'rack', str((row or {}).get('rack_uid') or '')
            elif scope == 'rack':
                row = self.racks.get(uid)
                scope, uid = 'room', str((row or {}).get('room_uid') or '')
            elif scope == 'room':
                row = self.rooms.get(uid)
                scope, uid = 'site', str((row or {}).get('site_uid') or '')
            else:
                break
        return out

    # ── What is free, which is half the reason any of this exists ─────────────

    def occupancy(self, rack_uid: str) -> dict:
        """Which U of a rack are taken, per face, and by which item.

        Returns ``{'front': {u: item_uid}, 'rear': {…}, 'height': N, 'slots': {face: {u: […]}}}``.
        A `full` item occupies both faces; that is what `full` MEANS, and it is why "is U 12
        free" cannot be answered without knowing which side is being asked about.

        `slots` es lo que hace falta desde que dos cosas caben en un U: por cada U ocupado, qué
        **trozos** lo están, como `(desde, hasta, de_cuantos, uid)`. El mapa de arriba se queda
        —dice quién manda en ese U, que es lo que dibuja el alzado y lo que cuenta un resumen—
        pero ya no alcanza para decidir si cabe otro.

        Lo montado en otro elemento **no ocupa**: ese U lo paga quien lo lleva.
        """
        rack = self.racks.get(rack_uid) or {}
        height = int(rack.get('u_height') or 0)
        taken = {'front': {}, 'rear': {}, 'height': height,
                 'slots': {'front': {}, 'rear': {}}}
        for item in self.items_of(rack_uid):
            if str(item.get('parent_uid') or ''):
                continue                        # va montado: su U ya lo paga otro
            faces = ('front', 'rear') if str(item.get('face') or 'full') == 'full' \
                else (str(item.get('face')),)
            start = int(item.get('u_start') or 1)
            trozo = _slot_of(item)
            for u in range(start, start + max(1, int(item.get('u_height') or 1))):
                for face in faces:
                    if face not in taken['slots']:
                        continue
                    taken['slots'][face].setdefault(u, []).append(trozo + (item['uid'],))
                    # Quién manda en ese U: el que lo ocupa entero si lo hay, y si no el
                    # primero. Un U medio ocupado tiene dueño para dibujarlo y sitio para otro.
                    if u not in taken[face] or trozo == (0, 1, 1):
                        taken[face][u] = item['uid']
        return taken

    def children_of(self, uid: str) -> list[dict]:
        """Lo que va montado en este elemento. Vacío si no lleva nada.

        Una consulta y no un recorrido de la lista del rack: de esto cuelga poder negarse a
        retirar una bandeja con tres máquinas encima, y eso tiene que poder preguntarse sin
        haber leído el rack entero.
        """
        return self.items.list('parent_uid = ?', (str(uid or ''),))

    def fits(self, rack_uid: str, u_start: int, u_height: int, face: str,
             *, ignore: str = '', slot=None) -> bool:
        """Whether an item of that size fits there — including inside the rack at all.

        Two devices in one U is not a data error the way a missing column is: it is a drawing
        that shows a cabinet that cannot exist, and every count taken off it is then wrong. The
        cheapest place to refuse it is here, before it is written.

        Dos cosas en un U **sí** pueden ser verdad desde que un U se parte: el patch panel de
        medio U, los dos mini PC del kit, la bandeja de ocho Raspberry. Lo que no puede es que
        se solapen los trozos, y eso es lo que se comprueba — con enteros, porque un tercio no
        existe en coma flotante y dos cosas que casi encajan es justo el dibujo imposible.

        *ignore* is the item being moved, which must not collide with where it currently is.
        """
        rack = self.racks.get(rack_uid)
        if not rack:
            return False
        height = int(rack.get('u_height') or 0)
        u_start, u_height = int(u_start or 0), max(1, int(u_height or 1))
        if u_start < 1 or u_start + u_height - 1 > height:
            return False
        face = str(face or 'full')
        if face not in FACES:
            return False
        mio = _slot_of(slot if slot is not None else {})
        faces = ('front', 'rear') if face == 'full' else (face,)
        taken = self.occupancy(rack_uid)
        for u in range(u_start, u_start + u_height):
            for f in faces:
                for otro in (taken['slots'].get(f, {}).get(u) or ()):
                    if str(otro[3]) == str(ignore or ''):
                        continue
                    if _overlap(mio, otro[:3]):
                        return False
        return True

    # ── Ownership: what was SAID. The inheritance is in owners.py ─────────────

    def owner_said(self, scope: str, uid: str) -> str:
        rows = self.owners.list('scope = ? AND uid = ?', (str(scope or ''), str(uid or '')))
        return str(rows[0]['org_uid']) if rows else ''

    def owners_map(self) -> dict:
        """Every declared ownership, as ``{(scope, uid): org_uid}``.

        One read for the whole picture, because the resolver runs per node and a query per node
        is the shape that makes a room of forty racks take a second to draw.
        """
        return {(str(r['scope']), str(r['uid'])): str(r['org_uid'])
                for r in self.owners.list()}

    def set_owner(self, scope: str, uid: str, org_uid: str, *, actor: str = '') -> bool:
        """Say who owns something — or, with an empty *org_uid*, stop saying.

        Clearing is not "owned by nobody": it is back to inheriting, which is a different state
        and the one somebody wants when a rack stops being an exception.
        """
        scope, uid = str(scope or ''), str(uid or '')
        if scope not in OWNER_SCOPES or not uid:
            return False
        self._db.execute('DELETE FROM dc_owner WHERE scope = ? AND uid = ?', (scope, uid))
        if str(org_uid or ''):
            self._db.execute(
                'INSERT INTO dc_owner (scope, uid, org_uid, set_at, set_by) '
                'VALUES (?, ?, ?, ?, ?)',
                (scope, uid, str(org_uid), BaseStore._now(), str(actor or '')))
        self._db.commit()
        self.owners._stamp()                    # noqa: SLF001  (its own table's stamp)
        return True

    def forget_scope(self, scope: str, uid: str) -> None:
        """Drop the ownership rows of something being deleted.

        Not a foreign key: the ownership table deliberately spans scopes that live in different
        tables — and one of them, `host`, is not this domain's table at all.
        """
        self._db.execute('DELETE FROM dc_owner WHERE scope = ? AND uid = ?',
                         (str(scope or ''), str(uid or '')))
        self._db.commit()
