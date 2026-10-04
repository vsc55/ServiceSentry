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
containment chain at all: a device with no rack, a VM, a VIP — all of them belong to somebody.

**A rack holds ITEMS, and some items are devices** — never the reverse. A patch panel takes 1U and
is not a device; a blanking plate is nothing; a blade chassis takes 7U and contains eight things
that are; a switched-off server occupies its U whether or not anything monitors it. So
``dc_item.device_uid`` is optional and ``devices`` is not touched: either side survives the other
being deleted, which is the point of not putting ``rack_uid`` on the device record.

**The face is part of the position.** A 1U device fills U 12 front *and* rear; a patch panel may
fill only the rear; two half-depth devices share one U from opposite sides. Without it the
elevation of a real rack is wrong within a week, and "is this U free" has no answer.

**Las declaraciones viven una por fichero** (``sites.py``, ``rooms.py``, ``racks.py``,
``items.py``, ``power.py``, ``cabling.py``, ``parts.py``, ``features.py``), y aquí se queda lo
que las cruza: la clase, el resolutor de solapes y las búsquedas. Doce tablas y ochocientas
líneas de declaración en un fichero eran doce dominios distintos con un solo índice; separadas,
cada una se lee entera de una vez. La clase no se parte por lo que dice su propio docstring: las
preguntas que importan cruzan las tablas.

Y lo que este paquete exporta es lo de siempre — `SCHEMAS`, `FACES`, `PART_KINDS`,
`clean_port_list`, `like_clause`… — porque cuarenta importaciones de fuera lo nombran así.
"""

from __future__ import annotations

from lib.core.dcim import assets as dcim_assets
from lib.core.dcim.revisions import RevisionStore
from lib.core.orgs.store import OrgsStore
from lib.db import BaseConnector
# El apaño de cinco métodos por tabla, que vivía aquí y ya no: lo mismo hace falta para las
# empresas, que son del core. `rank` se reexporta a propósito — `lib.core.dcim.builds` lo
# importa de este módulo, que es de donde salió.
from lib.db.rows import Rows, rank              # noqa: F401
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

from .cabling import (CABLE_CATEGORIES, CABLE_COLORS, CABLE_KINDS, LINK_KINDS,
                      _CABLE, _LINK)
from .features import (FEATURE_KINDS, FEATURE_LAYERS, SHELVED_KINDS, SHELVES_MAX, _FEATURE,
                       _SHELF_ITEM)
from .floors import _FLOOR
from .items import FACES, ITEM_ROLES, PLACEMENTS, ROLES_MUDOS, _ITEM
from .parts import (PART_KINDS, PORT_FAMILIES, PORT_LIST_MAX, PORT_SIGNALS_MAX,
                    WATTS_MAX, _PART, clean_port_list)
from .power import (FEED_CATEGORIES, FEED_COLORS, FEEDS, SOURCE_KINDS, _PDU, _POWER,
                    _SOURCE)
from .racks import SIDES, _RACK, _ROW
from .rooms import COOLING, ROOM_HEIGHT_MM, _ROOM
from .sites import _SITE

# `dc_org` y `dc_owner` estaban aqui y ya no: las empresas son del core
# (`lib.core.orgs`), porque la misma sociedad que paga el armario tiene usuarios en el
# directorio y licencias en Microsoft 365. Lo que queda de ellas en este fichero es el atajo
# de `DcimStore`, que sigue contestando `store.orgs` y `store.owners_map()` para no cambiar
# cuarenta llamadas que estan bien escritas.

# ── What a thing can be, for the ownership table and for the item's face ─────────────────
#: The scopes ownership can be declared on HERE: the four containment levels. `device` used to be
#: in this tuple and is not any more — a machine on a desk belongs to somebody without this
#: domain being involved, so `lib.core.devices` declares it, which is the whole point of the
#: scopes being declared instead of listed.
OWNER_SCOPES = ('site', 'room', 'rack', 'item')

SCHEMAS = (_SITE, _FLOOR, _ROOM, _RACK, _ITEM, _FEATURE, _PDU, _POWER, _CABLE,
           _LINK, _ROW, _SOURCE, _PART, _SHELF_ITEM)

#: Lo que este paquete ofrece hacia fuera. Escrito y no deducido: casi todo se importa aquí
#: sólo para volver a exportarlo, y sin esta lista cualquier herramienta lo llamaría muerto.
__all__ = ['DcimStore', 'SCHEMAS', 'OWNER_SCOPES', 'FACES', 'ITEM_ROLES', 'ROLES_MUDOS',
           'PLACEMENTS', 'PART_KINDS', 'SIDES', 'COOLING', 'ROOM_HEIGHT_MM',
           'FEATURE_KINDS', 'FEATURE_LAYERS', 'SHELVED_KINDS', 'SHELVES_MAX', 'FEEDS', 'SOURCE_KINDS', 'FEED_COLORS',
           'FEED_CATEGORIES', 'CABLE_KINDS', 'CABLE_CATEGORIES', 'CABLE_COLORS',
           'LINK_KINDS', 'PORT_FAMILIES', 'PORT_LIST_MAX', 'PORT_SIGNALS_MAX',
           'WATTS_MAX', 'clean_port_list', 'like_esc', 'like_clause', 'Rows', 'rank']

#: El carácter con el que se escapa un `%` o un `_` dentro de una búsqueda. Una barra invertida
#: es lo que entienden los tres motores con `ESCAPE`, y hace falta: sin ella, teclear `_` en el
#: buscador encuentra cualquier cosa y teclear `%` las encuentra todas — un buscador que ignora
#: lo que se le pide es peor que uno que no encuentra nada, porque contesta.
LIKE_ESC = '\\'

def like_esc(texto: str) -> str:
    """Un texto tecleado, listo para ir DENTRO de un patrón de `LIKE`.

    Aparte de `like_clause` porque no todo lo que se busca se busca por el medio: un número de
    inventario se busca por el principio —`INV-%`— y escapar en dos sitios es tener un sitio
    donde no se escapa.
    """
    t = str(texto or '')
    return (t.replace(LIKE_ESC, LIKE_ESC * 2)
             .replace('%', LIKE_ESC + '%').replace('_', LIKE_ESC + '_'))

def like_clause(cols, texto: str) -> tuple:
    """``(sql, params)`` para «alguna de estas columnas contiene esto», o ``('', ())``.

    En la BASE y no en memoria. Traer la tabla entera para filtrarla en Python construye un
    diccionario por fila de toda la instalación y tira casi todos: el motor sabe hacer esto sin
    materializar nada, y es literalmente para lo que está.

    `LOWER(...)` en los dos lados y dicho aquí, no dejado al motor: MySQL no distingue mayúsculas
    por defecto, SQLite sí y PostgreSQL depende del idioma del sistema. Un buscador que encuentra
    «SW01» escribiendo `sw` en una instalación y no en otra es el mismo panel comportándose de
    dos maneras según dónde esté instalado.

    **Sin índice que valga**, y se dice: un `%texto%` no puede usar un índice de texto en ningún
    motor — el índice ordena por el principio y esto busca por el medio. Lo que se gana es no
    construir la instalación entera en memoria, que es otra cosa y es la que importaba.
    """
    t = str(texto or '').strip().lower()
    if not t or not cols:
        return '', ()
    # Los comodines del propio `LIKE`, escapados: son caracteres que alguien puede teclear.
    patron = f'%{like_esc(t)}%'
    trozos = [f"LOWER({c}) LIKE ? ESCAPE '{LIKE_ESC}'" for c in cols]
    return '(' + ' OR '.join(trozos) + ')', tuple([patron] * len(cols))

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


class DcimStore:
    """The physical inventory: the containment chain, and who owns what.

    One store over six tables rather than six stores, because the questions that matter cross
    them — "what is in this rack", "is this U free", "whose is this" — and a caller holding six
    stores would be the one joining them.
    """

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        # Las empresas y lo que se dijo de cada cosa, que ya no son de este paquete. Se traen
        # aqui porque casi toda pantalla de inventario pregunta las dos cosas a la vez —donde
        # esta algo y de quien es— y hacer que cada una sostenga dos almacenes seria repartir
        # el trabajo de juntarlos entre cuarenta sitios.
        self._orgs = OrgsStore(db)
        self.orgs = self._orgs.orgs
        self.owners = self._orgs.owners
        self.sites = Rows(db, _SITE)
        self.floors = Rows(db, _FLOOR)
        self.rooms = Rows(db, _ROOM)
        self.racks = Rows(db, _RACK)
        self.items = Rows(db, _ITEM)
        self.features = Rows(db, _FEATURE)
        self.shelf_items = Rows(db, _SHELF_ITEM)
        self.pdus = Rows(db, _PDU)
        self.feeds = Rows(db, _POWER)
        self.cables = Rows(db, _CABLE)
        self.links = Rows(db, _LINK)
        self.rows = Rows(db, _ROW)
        self.sources = Rows(db, _SOURCE)
        self.parts = Rows(db, _PART)
        # Las versiones de un armario: cómo estaba y qué le pasó. Sobre la misma tabla que ya
        # guarda las de un modelo del catálogo y las de una plantilla — su `scope` nació para
        # esto, y una tabla por cada cosa con historial serían cuatro almacenes iguales.
        self.revs = RevisionStore(db)
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

    # ── El número de inventario, que es único entre TODO lo inventariado ──────
    #
    # Aquí y no en cada pantalla que escribe: un número es único entre todas estas tablas —
    # INV-45 es INV-45 tanto si es un servidor como si es un latiguillo— y esta es la única
    # pieza que las tiene todas delante. La regla de qué significa `INV-?` vive en
    # `lib.core.dcim.assets`, que no sabe qué es una base de datos; lo de aquí es ir a
    # buscarle los números que ya están dados.

    def asset_parts(self) -> list:
        """Los almacenes que llevan número de inventario, **descubiertos**.

        Preguntándole a cada tabla si tiene la columna, en vez de una lista escrita a mano: una
        lista hay que acordarse de tocarla el día que una tabla más lo lleve, y no acordarse no
        da ningún error — da un número repetido, meses después, cuando dos fichas dicen ser la
        misma cosa.
        """
        return [p for p in vars(self).values()
                if isinstance(p, Rows) and p.has(dcim_assets.ASSET_COL)]

    def colors_used(self, limit: int = 0) -> list:
        """Los colores que ya están puestos, **de todas las tablas que llevan uno**.

        Un latiguillo rojo y un cable de corriente rojo son el mismo rojo, y lo que se quiere al
        declarar el siguiente es el color que usa esta casa — no el que usa esta tabla. Contando
        por separado, el rojo de veinte cables de datos y el de veinte de corriente saldrían como
        dos colores de veinte en vez de uno de cuarenta.

        Descubiertas como las del número de inventario, preguntándole a cada tabla si tiene la
        columna: una lista escrita a mano es la que se queda sin la tabla que la lleve mañana.
        """
        cuenta: dict = {}
        for part in vars(self).values():
            if isinstance(part, Rows):
                for valor, n in part.counts('color').items():
                    cuenta[valor] = cuenta.get(valor, 0) + n
        return rank(cuenta, limit)

    def asset_owner(self, value, skip: str = '') -> str:
        """El uid de lo que YA lleva este número, o ``''``.

        *skip* es la propia fila cuando se está editando: guardar una ficha sin tocarle el
        número no puede fallar por chocar consigo misma.

        Vacío no es un duplicado. Un número en blanco es «nadie lo ha dicho», y de eso puede
        haber cuarenta.
        """
        v = dcim_assets.norm(value)
        if not v:
            return ''
        col = dcim_assets.ASSET_COL
        for part in self.asset_parts():
            for row in part.list(f'LOWER({col}) = ?', (v,)):
                uid = str(row.get('uid') or '')
                if uid and uid != str(skip or ''):
                    return uid
        return ''

    def assets_like(self, before: str, after: str) -> list:
        """Los números ya dados que empiezan y acaban así, de todas las tablas.

        Acotado en la BASE y por el principio: `INV-%` sí puede usar un índice —lo que no puede
        es un `%texto%`— y lo que se trae son los de esa numeración y no el inventario entero.
        """
        col = dcim_assets.ASSET_COL
        patron = f'{like_esc(before)}%{like_esc(after)}'.lower()
        sql = f"LOWER({col}) LIKE ? ESCAPE '{LIKE_ESC}'"
        fuera = []
        for part in self.asset_parts():
            fuera += [str(r.get(col) or '') for r in part.list(sql, (patron,))]
        return fuera

    def mint_asset(self, value, skip: str = '') -> tuple:
        """``(el número que se guarda, la clave del error)``.

        Las dos preguntas de golpe porque son la misma escritura: resolver `INV-?` contra lo que
        hay y comprobar que lo que sale no lo lleva ya otro. Separarlas dejaría un hueco entre
        las dos por el que cabe justo el caso que esto viene a impedir.

        **No es atómico, y se dice.** Dos escrituras simultáneas al milisegundo pueden minar el
        mismo número: entre leer los que hay y escribir el nuevo no hay ningún cerrojo, y no lo
        hay porque la unicidad cruza cuatro tablas y ninguna restricción de la base abarca eso —
        y una columna `UNIQUE` por tabla chocaría con los cuarenta que están en blanco, que son
        legítimos. Lo que sí cierra es el caso real, que no es la simultaneidad: es que dos
        personas numeren el mismo armario esta tarde y ninguna mire la lista.
        """
        malo = dcim_assets.bad(value)
        if malo:
            return str(value or '').strip(), malo
        trozo = dcim_assets.asks(value)
        if trozo:
            value, _ = dcim_assets.resolve(value, self.assets_like(trozo[0], trozo[2]))
        else:
            value = str(value or '').strip()
        if value and self.asset_owner(value, skip):
            return value, 'dcim_asset_taken'
        return value, ''

    # ── The containment chain, read downwards ─────────────────────────────────

    def rooms_of(self, site_uid: str) -> list[dict]:
        return self.rooms.list('site_uid = ?', (str(site_uid or ''),))

    def floors_of(self, site_uid: str) -> list[dict]:
        """Las plantas de una sede, de abajo arriba: como se recorre un edificio."""
        rows = self.floors.list('site_uid = ?', (str(site_uid or ''),))
        return sorted(rows, key=lambda f: (int(f.get('level') or 0), str(f.get('name') or '')))

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

    def shelf_items_of(self, feature_uid: str) -> list[dict]:
        """Lo que hay en un armario, por estantería y por nombre."""
        rows = self.shelf_items.list('feature_uid = ?', (str(feature_uid or ''),))
        return sorted(rows, key=lambda r: (int(r.get('shelf') or 0),
                                           str(r.get('label') or '').lower()))

    def delete_feature(self, uid: str) -> None:
        """Quitar una pieza con lo que guarda: el material de un armario borrado no tiene
        dónde estar, y dejarlo sería una lista de cosas en un sitio que ya no existe."""
        for row in self.shelf_items_of(uid):
            self.shelf_items.delete(row['uid'])
        self.features.delete(uid)

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

    def item_of_device(self, device_uid: str) -> dict | None:
        rows = self.items.list('device_uid = ?', (str(device_uid or ''),))
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

        Lo montado en otro elemento **no ocupa**: ese U lo paga quien lo lleva. Y lo que no va
        atornillado a los mástiles tampoco: no tiene U que ocupar.
        """
        rack = self.racks.get(rack_uid) or {}
        height = int(rack.get('u_height') or 0)
        taken = {'front': {}, 'rear': {}, 'height': height,
                 'slots': {'front': {}, 'rear': {}}}
        for item in self.items_of(rack_uid):
            if str(item.get('parent_uid') or ''):
                continue                        # va montado: su U ya lo paga otro
            # Y lo que no va atornillado a los mástiles no ocupa ninguno: un SAI en el suelo al
            # lado del armario está en el armario para todo lo demás —se alimenta, se cablea,
            # hay que ir a mirarlo— y no le quita el sitio a nada.
            if str(item.get('placement') or 'u') != 'u':
                continue
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
        return self._orgs.said_of(scope, uid)

    def owners_map(self) -> dict:
        """Every declared ownership, as ``{(scope, uid): org_uid}``.

        One read for the whole picture, because the resolver runs per node and a query per node
        is the shape that makes a room of forty racks take a second to draw.
        """
        return self._orgs.said()

    def set_owner(self, scope: str, uid: str, org_uid: str, *, actor: str = '') -> bool:
        return self._orgs.set_owner(scope, uid, org_uid, actor=actor)

    def forget_scope(self, scope: str, uid: str) -> None:
        self._orgs.forget_scope(scope, uid)
