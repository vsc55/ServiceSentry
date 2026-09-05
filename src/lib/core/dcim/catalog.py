#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The catalogue of equipment models, and where it comes from.

An elevation needs to know that a PowerConnect 2848 is 1U and full depth. Nobody is going to
type that for four hundred devices, and it is not knowledge about *this* installation — it is a
fact about equipment in general, which somebody has already written down: the
`netbox-community/devicetype-library <https://github.com/netbox-community/devicetype-library>`_
is several thousand YAML files under CC0-1.0 (public domain, verified 2026-08-26), one per
model, with exactly the fields a rack drawing and a power calculation need.

**It is imported, never packaged.** The repository is large, changes on its own schedule, and
vendoring it would make every release of this panel a release of somebody else's catalogue. So
it arrives the way the MIB library does: on demand, from a directory or a zip, into a table.
That also answers the isolated install — no outbound connection is required, somebody uploads
the zip.

**A subset is kept, not the file.** Storing each YAML whole would be storing another project's
schema, and every reader here would then have to know it. What is kept is the five required
fields (`manufacturer`, `model`, `slug`, `u_height`, `is_full_depth`) plus what is actually
drawn or counted.

**And ports are counted, not listed.** A 48-port switch lists 48 interfaces; five thousand
models listed that way is a table of a million rows that no screen reads. What an elevation and
a capacity figure want is "48 × 1000base-t, 4 × 10gbase-x-sfpp", so that is what is stored. The
day a screen needs to name an individual port, it will need the ports of ONE model, and that is
a re-read of one file rather than a table nobody could keep.

**PyYAML is optional.** It is not a dependency of the panel — the importer is the only thing in
the tree that wants it — so its absence disables this one feature with a sentence that says so,
the same way LDAP, SAML and the Teams bot behave. It is declared in ``requirements.txt`` under
the other optional ones.
"""

from __future__ import annotations

import io
import os
import re
import zipfile

from lib.core.dcim import media
from lib.core.dcim.brands import BrandStore, slug_of as brand_slug
from lib.core.dcim.revisions import RevisionStore
from lib.providers import github as gh
from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.core.dcim.store import PORT_LIST_MAX as _PORT_LIST_MAX, clean_port_list
from lib.db.store_base import BaseStore

try:                                            # pragma: no cover - presence is the test
    import yaml as _yaml
except ImportError:                             # pragma: no cover
    _yaml = None

#: What a caller is told when the parser is not installed. A feature that fails silently
#: because a library is missing is a feature nobody can report.
NO_PARSER = 'dcim_catalog_no_yaml'

#: The fields kept out of each file, and nothing else — see the module docstring.
_KEEP = ('manufacturer', 'model', 'slug', 'part_number', 'airflow', 'subdevice_role',
         'description', 'front_image', 'rear_image')

#: Lo que se copia de un modelo de componente a una pieza — de una plantilla o de una máquina.
#: En un sitio porque lo usan dos rutas, y dos copias de esta lista serían dos formas de que una
#: pieza saliera con menos datos que la otra según por dónde entrara.
PART_FROM_TYPE = (('brand', 'manufacturer'), ('model', 'model'), ('size', 'size'),
                  ('kit_qty', 'kit_qty'))

SCHEMA = TableSpec(
    name='dc_type',
    columns=(
        Column('uid',          'TEXT', primary_key=True),
        Column('manufacturer', 'TEXT', nullable=False, default="''"),
        Column('model',        'TEXT', nullable=False, default="''"),
        Column('slug',         'TEXT', nullable=False, default="''"),
        # The five that make an elevation possible. `u_height` is stored as tenths, because a
        # handful of models are 0.5U and an integer column would round them into each other.
        Column('u_tenths',     'INTEGER', nullable=False, default='10'),
        Column('full_depth',   'INTEGER', nullable=False, default='1'),
        Column('part_number',  'TEXT', nullable=False, default="''"),
        Column('airflow',      'TEXT', nullable=False, default="''"),
        # `parent` / `child`: a blade chassis and the blades that go in it. Kept because an
        # elevation that draws a chassis as eight separate 1U servers is wrong about the rack.
        Column('subdevice',    'TEXT', nullable=False, default="''"),
        Column('is_powered',   'INTEGER', nullable=False, default='1'),
        Column('front_image',  'TEXT', nullable=False, default="''"),
        Column('rear_image',   'TEXT', nullable=False, default="''"),
        # Counts by kind, as JSON: {"interfaces": {"1000base-t": 48}, "power-ports": {…}}
        Column('ports',        'TEXT', nullable=False, default="'{}'"),
        # And what each one is CALLED, in the order the device has them:
        # {"interfaces": [{"name": "gi1", "type": "1000base-t"}, …]}. Counting answers "is this
        # switch big enough"; naming answers "which socket am I looking at" — `gi1` is what the
        # device's own configuration says and what goes on the patch lead's label. Both, because
        # they are two questions and the library has carried the answer to the second all along.
        Column('port_list',    'TEXT', nullable=False, default="'{}'"),
        # Which import this row came from, so a re-import can replace its own and leave
        # anything somebody typed by hand alone.
        Column('source',       'TEXT', nullable=False, default="''"),
        Column('imported_at',  'TEXT', nullable=False, default="''"),
        # What a device's own answer has to look like to be matched to this row — see `key()`.
        Column('match_key',    'TEXT', nullable=False, default="''"),
        # Si es un dispositivo entero o un MÓDULO —una tarjeta de línea, un transceptor—. Son la
        # misma forma con dos significados, y mezclarlos haría que un transceptor apareciera
        # como algo que ocupa U en un alzado. Vacío = de antes de la distinción, y entonces es
        # un dispositivo: es lo único que la biblioteca traía cuando se escribió.
        Column('tree', 'TEXT', nullable=False, default="'device-types'"),
        # Lo que solo tiene una forma: de un ARMARIO, sus medidas exteriores, el fondo de
        # montaje y el peso que aguanta. En una columna de JSON y no en ocho columnas nuevas,
        # porque son datos de ciento cuarenta filas de ocho mil y ocho columnas vacías las
        # pagarían todas. La última declarada, para que aparecer sobre una tabla llena sea un
        # `ADD COLUMN` y no una reconstrucción.
        Column('extra', 'TEXT', nullable=False, default="'{}'"),
        # Qué clase de cosa es, deducido al importar. Lo que este dominio no escribe como un
        # hecho es el PAPEL DE UN DISPOSITIVO COLOCADO —`dc_item.role`, que decide quien lo coloca—
        # y esto es otra cosa: una clasificación del modelo del catálogo. Guardarla es lo que
        # permite filtrar ocho mil quinientas filas por «switch» sin traérselas todas.
        Column('kind', 'TEXT', nullable=False, default="''"),
        # Si la clase la decidió UNA PERSONA. Sin esta marca no hay forma de distinguir lo que
        # se dedujo de lo que alguien corrigió, y al reimportar la biblioteca habría que elegir
        # entre perder todas las correcciones o no actualizar nunca lo deducido.
        Column('kind_set', 'INTEGER', nullable=False, default='0'),
        # La línea que explica qué es cuando el nombre no lo dice —«APC NetShelter SX, 42U,
        # 1991H x 600W x 1070D mm»— y la que hace que buscar «rack 42U» encuentre algo. La
        # traen los tres esquemas de la biblioteca y no se guardaba.
        Column('description', 'TEXT', nullable=False, default="''"),
        # El FABRICANTE, ahora que es una fila y no una cadena repetida ocho mil quinientas
        # veces (`dc_maker`). La columna de texto se queda: es lo que dijo el fichero de origen,
        # y es lo que sigue siendo cierto si alguien borra la ficha del fabricante — un modelo
        # no deja de ser de Dell porque nadie quiera guardar el teléfono de Dell.
        #
        # La última declarada, para que aparecer sobre una tabla llena sea un `ADD COLUMN`.
        Column('brand_uid', 'TEXT', nullable=False, default="''"),
        # El TAMAÑO, que solo tienen los componentes: «32 GB», «1.92 TB», «750 W». Una columna
        # y no una clave dentro de `extra` —donde están las medidas de un armario— porque no es
        # lo mismo: aquello son ocho campos de ciento cuarenta filas, y esto es **el campo que
        # se lee en cada renglón** de lo que más se va a teclear a mano. Dentro de un JSON no se
        # ordena, no se busca y no se enseña sin desenvolverlo.
        #
        # Como texto, por lo mismo que en `dc_part`: en bytes habría que decidir si 4 TB son
        # 4·10¹² o 4·2⁴⁰ —las dos respuestas están en algún albarán— y convertir para enseñar lo
        # que alguien ya escribió bien.
        Column('size', 'TEXT', nullable=False, default="''"),
        # La página del producto: la hoja de características, el firmware, el manual. No la trae
        # ninguna biblioteca —la de NetBox no la publica— y es lo primero que se busca cuando hay
        # que saber si una tarjeta entra en un chasis. La marca tiene la suya, comercial y de
        # soporte; esta es la de ESTE modelo, que es otra cosa.
        Column('url', 'TEXT', nullable=False, default="''"),
        # Cuándo se tocó por última vez, quién, y por qué versión va. El historial las tiene una
        # a una; esto es el resumen que quiere una ficha —cuándo y cuántas— sin abrirlo. Columnas
        # y no una consulta al historial porque la lista enseña doscientas filas, y contar
        # versiones de doscientas fichas para pintar dos casillas sería pagar el resumen a precio
        # del detalle.
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
        Column('rev', 'INTEGER', nullable=False, default='1'),
        # Cuántas piezas trae UNA de estas. Un kit de dos módulos se compra como uno y se monta
        # como dos; una caja de cincuenta tornillos, igual. La pregunta del inventario —«cuántos
        # DIMM de 16 GB tengo»— quiere la segunda cifra y la del pedido quiere la primera, y con
        # una sola casilla hay que elegir cuál se contesta mal.
        #
        # Columna y no atributo del documento porque el panel **multiplica por ella**, y lo que
        # se multiplica no puede depender de que nadie renombre una clave en un JSON.
        Column('kit_qty', 'INTEGER', nullable=False, default='1'),
        # Por dónde come. `is_powered` dice SI come y no dice cómo, y la diferencia entre una
        # fuente dentro y un alimentador externo decide si hace falta una toma en la regleta o
        # enchufe en la pared — y si al mover el equipo hay que acordarse de llevarse algo que no
        # está atornillado.
        #
        # `none` no es un valor de aquí: eso lo dice `is_powered` en cero, y tenerlo en dos sitios
        # serían dos respuestas a la misma pregunta.
        Column('power_type', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_type_match', ('match_key',)),
             Index('idx_dc_type_maker', ('manufacturer',)),
             Index('idx_dc_type_brand_uid', ('brand_uid',))),
)

_WORD = re.compile(r'[^a-z0-9]+')


def key(maker: str, model: str) -> str:
    """The string a model is looked up by.

    Matching on what a device says about itself is a **proposal**, never an answer: sysDescr is
    free text and "PowerConnect 2848" arrives with a dozen spellings. Normalising to lowercase
    alphanumerics collapses the spellings that differ only in punctuation, which is most of
    them, and leaves the rest to a person — a wrongly matched model puts a 2U device in a U
    that has not got the room, and no wrong drawing is better than no drawing.
    """
    return _WORD.sub('', f'{maker or ""}{model or ""}'.lower())


def parse(text: str) -> dict | None:
    """One device-type YAML, as the subset this panel keeps. ``None`` if it is not one.

    Anything without the required fields is skipped rather than stored half-empty: the library
    also holds module types and other shapes, and a row with no height is a row an elevation
    cannot draw and a search will still return.
    """
    if _yaml is None:
        raise RuntimeError(NO_PARSER)
    try:
        doc = _yaml.safe_load(text)
    except Exception:                           # pylint: disable=broad-except
        return None                             # a broken file is one file, not a failed import
    if not isinstance(doc, dict):
        return None
    maker = str(doc.get('manufacturer') or '').strip()
    model = str(doc.get('model') or '').strip()
    if not maker or not model:
        return None
    try:
        u_tenths = int(round(float(doc.get('u_height', 1)) * 10))
    except (TypeError, ValueError):
        return None
    row = {k: str(doc.get(k) or '').strip() for k in _KEEP}
    row.update({
        'u_tenths': max(0, u_tenths),
        'full_depth': 1 if doc.get('is_full_depth', True) else 0,
        'subdevice': str(doc.get('subdevice_role') or '').strip(),
        'is_powered': 0 if doc.get('is_powered') is False else 1,
        'ports': _ports(doc),
        # Y cómo se llama cada una. Al cablear no se pregunta cuántas bocas hay, se pregunta
        # cómo se llama ESTA: `gi1` es lo que sale en la configuración del equipo y en la
        # etiqueta del latiguillo. La biblioteca lo trae y se estaba tirando al contar.
        'port_list': _port_list(doc),
        # Y qué significan las tomas que acaba de contar: una `dc-terminal` es un alimentador
        # fuera de la caja, y eso decide si al mudar el equipo hay que acordarse de llevárselo.
        'power_type': _power_type(doc),
        'match_key': key(maker, model),
    })
    row.pop('subdevice_role', None)
    row['extra'] = _extra(doc)
    return row


#: Lo que se guarda de un armario y de nada más. Sus medidas exteriores dicen si cabe donde se
#: quiere ponerlo, y el peso máximo si aguanta lo que se le va a meter — dos preguntas que se
#: hacen ANTES de comprar y que el catálogo puede contestar.
_RACK_FIELDS = ('form_factor', 'width', 'starting_unit', 'desc_units',
                'outer_width', 'outer_height', 'outer_depth', 'outer_unit',
                'mounting_depth', 'weight', 'max_weight', 'weight_unit')


def _extra(doc: dict) -> dict:
    """Lo que una forma tiene y las otras no.

    Hoy son las medidas de un armario. Va como un diccionario y no como columnas porque el día
    que la biblioteca añada un campo, añadirlo aquí no es migrar una tabla de ocho mil filas —
    y porque ciento cuarenta armarios no justifican ocho columnas que las otras ocho mil filas
    tendrían vacías.
    """
    out = {}
    for campo in _RACK_FIELDS:
        v = doc.get(campo)
        if v is None or v == '':
            continue
        out[campo] = v if isinstance(v, (int, float, bool)) else str(v).strip()
    return out


#: Cómo llega la corriente a un equipo. Vacío = nadie lo ha dicho, que es distinto de las tres.
POWER_TYPES = ('internal', 'external', 'poe')

#: Las clases que se saben deducir. Las de dispositivo son las mismas que un item puede tener
#: —para que la sugerencia al colocar valga tal cual— más las tres que solo existen en el
#: catálogo: un armario, y los módulos que no son un dispositivo entero.
KINDS = ('server', 'switch', 'router', 'firewall', 'storage', 'patch_panel', 'fiber_panel',
         'ups', 'pdu', 'shelf', 'kvm', 'console', 'blank',
         'rack', 'transceiver', 'psu', 'nic', 'module', 'other')

#: El cuarto árbol, y el único que no viene de ninguna biblioteca: los **modelos de componente**
#: —memoria, discos, CPU, tarjetas—. Ninguna pública los trae: los `module-types` de NetBox son
#: tarjetas de línea y transceptores, cosas que van en una bahía, y un DIMM no va en una bahía.
#: Así que se escriben una vez y se reutilizan siempre, que es para lo que sirve un catálogo
#: propio.
#:
#: Aquí y no en una tabla nueva porque es la misma forma —fabricante, modelo, part number,
#: descripción, imagen— y esta pantalla ya sabe agrupar por fabricante, buscar, filtrar, clonar,
#: editar y borrar. Otra tabla sería otra pantalla haciendo las mismas nueve cosas.
COMPONENT_TREE = 'component-types'


def kinds_for(tree: str) -> tuple:
    """El vocabulario de clases que se aplica a un árbol. **El árbol decide cuál**.

    Un DIMM no es «switch, servidor u otro»: las clases de :data:`KINDS` son las de las cosas que
    ocupan U, y ofrecer una de ellas para un componente acabaría ofreciendo el componente en un
    alzado. Las de un componente son las mismas que puede tener una pieza puesta en un equipo
    (``dc_part.kind``) — a propósito, porque de un modelo de componente sale una pieza.

    Y un ARMARIO no tiene ninguna: las clases de :data:`KINDS` son las de las cosas que van
    DENTRO de un armario, y ofrecérselas a un armario deja escribir «armario que es un panel de
    parcheo». Eso no es un dato raro, es un dato imposible — y el que lo escribe no está
    describiendo su armario: se ha equivocado de rama y esa casilla es lo único que se lo podía
    decir. Un armario ya declara su forma en `form_factor`, que es lo que aquí sería la clase.
    """
    from lib.core.dcim.store import PART_KINDS     # noqa: PLC0415  (mismo paquete)
    arbol = str(tree or '')
    if arbol == COMPONENT_TREE:
        return PART_KINDS
    return () if arbol == 'rack-types' else KINDS


#: Lo que dice el nombre de un componente, cuando nadie ha dicho la clase. Un componente no
#: declara puertos —una memoria no tiene ninguno— así que el nombre es la única señal que queda.
#: Estrecha a propósito, como la de los módulos: acertar seis de cada diez y no inventarse los
#: otros cuatro es mejor que una lista larga que falla de formas que nadie previó.
_COMPONENT_WORDS = (
    ('memory', ('dimm', 'ddr3', 'ddr4', 'ddr5', 'sodimm', 'rdimm', 'udimm')),
    ('ssd', ('ssd', 'nvme', 'm.2')),
    ('disk', ('hdd', 'hard drive', 'sas ', 'sata ')),
    ('cpu', ('xeon', 'epyc', 'core i', 'ryzen', 'cpu ')),
    ('gpu', ('geforce', 'radeon', 'quadro', 'tesla', 'gpu')),
    ('hba', ('raid', 'perc', 'megaraid', 'hba', 'smart array')),
    ('nic', ('nic', 'ethernet', 'network adapter')),
    ('transceiver', ('sfp', 'qsfp', 'xfp', 'gbic', 'transceiver')),
    ('psu', ('psu', 'power supply', 'powersupply')),
    ('battery', ('battery', 'bateria')),
    ('fan', ('fan ', 'ventilador')),
)

#: Lo que dice el NOMBRE de un módulo cuando sus puertos no dicen nada. Un módulo suele no
#: declarar ninguno —una fuente es una fuente y no tiene puertos que contar— así que la única
#: señal que queda es cómo se llama. Es una heurística y se sabe: por eso solo se aplica a los
#: módulos, donde la alternativa es no decir nada en absoluto.
_MODULE_WORDS = (
    ('transceiver', ('sfp', 'qsfp', 'xfp', 'gbic', 'transceiver', 'optic')),
    ('psu', ('psu', 'power supply', 'powersupply', '-ps', 'pwr')),
    ('nic', ('nic', 'ethernet card', 'network card', 'hba', 'adapter')),
)


def kind_of(row: dict) -> str:
    """Qué clase de cosa es este modelo. Nunca vacío: `other` es «no encaja», y es una respuesta.

    Un armario es un armario y un módulo es un módulo — eso lo dice el árbol del que vino, sin
    adivinar nada. Para un dispositivo se mira lo que trae: tomas de corriente y ninguna interfaz
    reparte corriente; puertos por delante y por detrás sin alimentación es un panel (no lo
    alimenta nadie porque no lo necesita); bahías de dispositivo es un chasis.

    Las señales son pocas y fuertes a propósito. Una lista larga de reglas acierta más casos y
    falla de formas que nadie puede prever, y lo que sale de aquí se enseña como si se supiera.
    """
    arbol = str(row.get('_tree') or row.get('tree') or 'device-types')
    if arbol == 'rack-types':
        return 'rack'
    if arbol == COMPONENT_TREE:
        # Aquí no hay puertos que mirar: una memoria no declara ninguno. Lo que la fila diga
        # manda —viene de un formulario con su desplegable, así que casi siempre lo dirá— y si
        # no dice nada, el nombre; y si el nombre tampoco, `other`, que es una respuesta.
        from lib.core.dcim.store import PART_KINDS  # noqa: PLC0415
        dicha = str(row.get('kind') or '')
        if dicha in PART_KINDS:
            return dicha
        nombre = ' '.join((str(row.get('model') or ''),
                           str(row.get('part_number') or ''),
                           str(row.get('description') or ''))).lower()
        for clase, palabras in _COMPONENT_WORDS:
            if any(p in nombre for p in palabras):
                return clase
        return 'other'
    puertos = row.get('ports')
    if isinstance(puertos, str):
        try:
            import json as _json                 # noqa: PLC0415
            puertos = _json.loads(puertos or '{}')
        except Exception:                        # pylint: disable=broad-except
            puertos = {}
    puertos = puertos if isinstance(puertos, dict) else {}
    if arbol == 'module-types':
        nombre = ' '.join((str(row.get('model') or ''),
                           str(row.get('part_number') or ''))).lower()
        for clase, palabras in _MODULE_WORDS:
            if any(p in nombre for p in palabras):
                return clase
        if puertos.get('interfaces'):
            return 'nic'
        if puertos.get('power-ports') and len(puertos) == 1:
            return 'psu'
        return 'module'

    def tiene(k):
        return bool(puertos.get(k))

    alimentado = str(row.get('is_powered', 1)) not in ('0', 'False', 'false')
    if tiene('power-outlets') and not tiene('interfaces'):
        # Un SAI y una regleta reparten corriente con las mismas señales: tomas y ninguna
        # interfaz. Lo único que los separa es cómo se llaman, y por eso esta es la ÚNICA regla
        # de nombre que se aplica a un dispositivo — estrecha a propósito: solo aquí, solo con
        # `ups` como palabra suelta. Sin ella, `ups` es una opción del filtro que no encuentra
        # nunca nada, y son dos cosas que no se sustituyen igual: cuando un SAI se apaga, lo que
        # cuelga de él sigue con luz; cuando es la regleta, no.
        nombre = str(row.get('model') or '').lower()
        if re.search(r'\bups\b|\bsai\b', nombre):
            return 'ups'
        return 'pdu'
    if (tiene('front-ports') or tiene('rear-ports')) and not tiene('interfaces') \
            and not alimentado:
        return 'patch_panel'
    if tiene('device-bays'):
        return 'server'                          # un chasis: lo que lleva dentro son servidores
    if tiene('interfaces'):
        cuantas = sum(int(v or 0) for v in (puertos.get('interfaces') or {}).values())
        return 'switch' if cuantas >= 8 else 'server'
    if not alimentado:
        return 'shelf'                           # sin puertos y sin alimentar: una bandeja
    return 'other'


#: Las familias de puertos, en el orden en que se preguntan. Una sola lista porque contarlos y
#: nombrarlos recorren lo mismo, y dos copias se separan el día que la biblioteca añada una.
PORT_KINDS = ('interfaces', 'power-ports', 'power-outlets', 'console-ports',
              'console-server-ports', 'front-ports', 'rear-ports', 'module-bays',
              'device-bays')

#: El tope de bocas nombradas por familia, dicho donde se limpia la lista. Aquí por su nombre de
#: siempre: es el mismo número y no puede haber dos.
PORT_LIST_MAX = _PORT_LIST_MAX


def _port_list(doc: dict) -> dict:
    """``{'interfaces': [{'name': 'gi1', 'type': '1000base-t'}, …], …}`` — en su orden.

    **En su orden y no ordenado**: `gi10` va después de `gi9` en el equipo y antes alfabéticamente,
    y una lista de puertos que no sale en el orden del panel frontal no sirve para lo único que se
    le pide, que es encontrar la boca que se está mirando.

    El documento de la biblioteca trae por boca lo mismo que se guarda —nombre y tipo— y algunas
    cosas más que aquí no se leen, así que es la misma limpieza que la de la puerta de entrada:
    dos que hicieran lo mismo acabarían haciéndolo distinto, y el fallo saldría según si el modelo
    entró importado o escrito a mano.
    """
    return clean_port_list(doc)


def _ports(doc: dict) -> dict:
    """``{'interfaces': {'1000base-t': 48}, …}`` — counted by kind, never listed.

    A missing ``type`` counts under ``''`` rather than being dropped: "this model has four
    somethings" is worth more to a capacity figure than silence, and the alternative hides the
    gap in the source data.
    """
    out: dict = {}
    for kind in PORT_KINDS:
        rows = doc.get(kind)
        if not isinstance(rows, list) or not rows:
            continue
        counts: dict = {}
        for entry in rows:
            name = str((entry or {}).get('type') or '') if isinstance(entry, dict) else ''
            counts[name] = counts.get(name, 0) + 1
        out[kind] = counts
    return out


#: Tomas de corriente que significan que la fuente está FUERA de la caja: un conector de
#: continua o un USB es la salida de un alimentador, no una entrada de red eléctrica. Lo demás
#: —`iec-60320-c14`, `nema-5-15p`, `saf-d-grid`— es corriente de pared, y eso solo entra en un
#: equipo que lleva la fuente dentro.
_DC_IN = ('dc-', 'usb-', 'molex-')


def _power_type(doc: dict) -> str:
    """Por dónde come, deducido de las tomas que el modelo declara.

    La biblioteca no trae este dato con este nombre, pero trae la respuesta. Deducirlo aquí y
    no en la pantalla es lo que hace que sirva para filtrar y para sumar: quien pregunte
    «cuántos enchufes hace falta en este armario» tiene que poder preguntárselo a la base de
    datos, no a ocho mil fichas abiertas de una en una.

    Vacío cuando el modelo no dice nada, que no es lo mismo que «no se alimenta» —eso lo dice
    `is_powered`— sino que quien subió el fichero no rellenó esa parte.
    """
    tomas = doc.get('power-ports')
    tipos = [str((e or {}).get('type') or '').strip().lower()
             for e in (tomas if isinstance(tomas, list) else ()) if isinstance(e, dict)]
    if tipos:
        return 'external' if any(t.startswith(_DC_IN) for t in tipos) else 'internal'
    # Sin toma de corriente puede seguir comiendo: por el cable de red. `pd` es «powered
    # device», el que recibe — al revés que el switch, que es `pse` y sí gasta enchufe.
    puertos = doc.get('interfaces')
    for e in (puertos if isinstance(puertos, list) else ()):
        if isinstance(e, dict) and str(e.get('poe_mode') or '').strip().lower() == 'pd':
            return 'poe'
    return ''


def walk(root: str):
    """Every ``.yaml`` under *root*, deepest-first order not guaranteed and not needed."""
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.lower().endswith(('.yaml', '.yml')):
                yield os.path.join(base, name)


class CatalogStore(BaseStore):
    """The models, and the one import that replaces them."""

    _TABLE = SCHEMA.name

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(SCHEMA)
        # Los fabricantes son la raíz de esto, y quien los crea es esta clase: nadie va a
        # teclear trescientos antes de traerse la biblioteca. Construido aquí y no recibido de
        # fuera porque importar SIN crearlos dejaría el catálogo colgando de nada, y eso no
        # puede depender de que quien construya el store se acuerde de pasar el otro.
        self.brands = BrandStore(db)
        # Qué decía esta ficha antes, y quién la cambió. Un modelo del catálogo es un dato
        # compartido —de él cuelgan plantillas, piezas estampadas y la altura de un alzado— así
        # que corregirlo no es editar una fila: es cambiar lo que otros ya usaban.
        self.revs = RevisionStore(db)
        self.backfill_kinds()
        self.backfill_brands()
        self.backfill_power()

    def backfill_brands(self) -> int:
        """Dar de alta los fabricantes de lo que ya estaba importado. Devuelve cuántas filas.

        Mismo caso que `backfill_kinds` y misma razón: `ADD COLUMN` no puede inventarse el
        valor, así que quien ya tenía las ocho mil quinientas filas las vería sin fabricante y
        la pantalla de fabricantes vacía. Nadie reinstala para recibir un arreglo, y menos aún
        vuelve a descargar ochocientos cincuenta megas para que salga una lista.

        No necesita internet: el nombre ya está en cada fila. Y se hace **una vez** — la
        pregunta previa contesta cero en cuanto no queda ninguna.
        """
        try:
            fila = self._db.fetchone(
                f"SELECT COUNT(*) FROM {self._sql_table} "
                f"WHERE (brand_uid = '' OR brand_uid IS NULL) AND manufacturer <> ''")
        except Exception:                       # pylint: disable=broad-except
            return 0                            # la tabla puede no existir todavía
        if not fila or not int(fila[0] or 0):
            return 0
        # Por NOMBRE distinto y no fila a fila: son ocho mil quinientas filas de trescientos
        # fabricantes, y preguntar por cada una sería ocho mil quinientas búsquedas para
        # trescientas respuestas.
        nombres = self._db.fetchall(
            f"SELECT DISTINCT manufacturer FROM {self._sql_table} "
            f"WHERE (brand_uid = '' OR brand_uid IS NULL) AND manufacturer <> ''") or ()
        n = 0
        for (nombre,) in nombres:
            uid = self.brands.ensure(str(nombre or ''))
            if not uid:
                continue
            self._db.execute(
                f"UPDATE {self._sql_table} SET brand_uid = ? "
                f"WHERE manufacturer = ? AND (brand_uid = '' OR brand_uid IS NULL)",
                (uid, str(nombre)))
            n += 1
        self._db.commit()
        return n

    def backfill_power(self) -> int:
        """Deducir por dónde come lo que ya estaba importado. Devuelve cuántas filas.

        La columna es nueva y `ADD COLUMN` no puede inventarse el valor, así que ocho mil
        modelos la traían vacía y la plantilla no podía decir si un equipo llevaba la fuente
        dentro. No hace falta internet ni volver a importar: las tomas están contadas en `ports`
        desde la primera importación, y la deducción es la misma que hace :func:`_power_type`.

        Lo único que no se recupera así es el `poe_mode`, que la biblioteca pone en la interfaz
        y aquí no se guarda. Ese vuelve con la siguiente importación de ese fabricante, y
        mientras tanto queda vacío — que es la verdad, no un cero.

        Una vez: la pregunta previa contesta cero en cuanto no queda ninguna.
        """
        try:
            fila = self._db.fetchone(
                f"SELECT COUNT(*) FROM {self._sql_table} "
                f"WHERE (power_type = '' OR power_type IS NULL) AND ports <> ''")
        except Exception:                       # pylint: disable=broad-except
            return 0                            # la tabla puede no existir todavía
        if not fila or not int(fila[0] or 0):
            return 0
        import json
        n = 0
        for uid, crudo in (self._db.fetchall(
                f"SELECT uid, ports FROM {self._sql_table} "
                f"WHERE (power_type = '' OR power_type IS NULL) AND ports <> ''") or ()):
            try:
                tomas = (json.loads(crudo or '{}') or {}).get('power-ports') or {}
            except (TypeError, ValueError):
                continue
            if not tomas:
                continue
            # El mismo criterio que al leer el YAML, sobre lo que quedó contado: las claves de
            # `ports` SON los tipos de toma, así que aquí hay exactamente la misma respuesta.
            tipo = ('external' if any(str(t or '').lower().startswith(_DC_IN) for t in tomas)
                    else 'internal')
            self._db.execute(f'UPDATE {self._sql_table} SET power_type = ? WHERE uid = ?',
                             (tipo, str(uid)))
            n += 1
        self._db.commit()
        return n

    def brand_counts(self) -> dict:
        """Cuántos modelos tiene cada fabricante, por su uid.

        De una sola consulta: la pantalla los enseña todos con su cuenta, y preguntarlo
        fabricante a fabricante serían trescientas consultas para pintar trescientos renglones.
        """
        rows = self._db.fetchall(
            f'SELECT brand_uid, COUNT(*) FROM {self._sql_table} '
            f"WHERE brand_uid <> '' GROUP BY brand_uid") or ()
        return {str(r[0]): int(r[1]) for r in rows}

    def backfill_kinds(self) -> int:
        """Clasificar lo que se importó antes de que existiera la columna. Devuelve cuántas.

        `ADD COLUMN` no puede inventarse el valor, así que una columna nueva sobre una tabla
        llena aparece vacía: quien ya tenía el catálogo vería «Sin clasificar» en las ocho mil
        quinientas filas y un filtro que no filtra. Nadie reinstala para recibir un arreglo, y
        menos aún vuelve a descargar ochocientos cincuenta megas para que salga una palabra.

        Se puede hacer aquí porque la deducción **no necesita internet**: sale de los puertos y
        del árbol, y las dos cosas ya están guardadas.

        Una vez: la pregunta previa es un `COUNT` que contesta cero en cuanto no queda ninguna,
        y entonces esto sale sin tocar nada.
        """
        try:
            fila = self._db.fetchone(
                f"SELECT COUNT(*) FROM {self._sql_table} WHERE kind = '' OR kind IS NULL")
        except Exception:                       # pylint: disable=broad-except
            return 0                            # la tabla puede no existir todavía
        if not fila or not int(fila[0] or 0):
            return 0
        n = 0
        for row in self.list("kind = '' OR kind IS NULL"):
            self._db.execute(
                f'UPDATE {self._sql_table} SET kind = ? WHERE uid = ?',
                (kind_of(row), str(row['uid'])))
            n += 1
        self._db.commit()
        return n

    _COLS = tuple(c.name for c in SCHEMA.columns)

    def _row(self, row) -> dict:
        out = {name: row[i] for i, name in enumerate(self._COLS)}
        import json
        # Las dos columnas de JSON se deshacen AQUÍ, en el único sitio por el que sale una fila:
        # quien la reciba trabaja con diccionarios y no con texto, y dejar que cada pantalla
        # decida cuándo interpretarlo es tener dos que se olvidan.
        for campo in ('ports', 'port_list', 'extra'):
            try:
                out[campo] = json.loads(out.get(campo) or '{}')
            except Exception:                   # pylint: disable=broad-except
                out[campo] = {}
        return out

    def list(self, where: str = '', params: tuple = (), limit: int = 0,
             offset: int = 0) -> list[dict]:
        sql = f'SELECT {", ".join(self._COLS)} FROM {self._sql_table}'
        if where:
            sql += f' WHERE {where}'
        # Sin distinguir mayúsculas, y dicho aquí y no dejado a la base de datos: esto corre
        # sobre tres motores con tres criterios distintos por defecto —MySQL no distingue,
        # SQLite sí, PostgreSQL depende del idioma del sistema— y el orden de una lista no
        # puede depender de dónde esté instalado el panel.
        sql += ' ORDER BY LOWER(manufacturer), LOWER(model)'
        if limit:
            sql += f' LIMIT {int(limit)}'
            if offset:
                # Después del LIMIT porque sin él no hay OFFSET que valga: los tres motores
                # que esto soporta lo escriben igual, y ninguno acepta un OFFSET suelto.
                sql += f' OFFSET {int(offset)}'
        return [self._row(r) for r in (self._db.fetchall(sql, params) or ())]

    def count(self, where: str = '', params: tuple = ()) -> int:
        """Cuántos hay en total, que no es lo mismo que cuántos se están enseñando.

        Sin esta pregunta un listado recortado a doscientos parece un catálogo de doscientos, y
        quien busque el modelo que está en la fila mil doscientos concluirá que no se importó.
        """
        sql = f'SELECT COUNT(*) FROM {self._sql_table}'
        if where:
            sql += f' WHERE {where}'
        fila = self._db.fetchone(sql, params)
        return int(fila[0]) if fila else 0

    def get(self, uid: str) -> dict | None:
        rows = self.list('uid = ?', (str(uid or ''),))
        return rows[0] if rows else None

    def suggest(self, maker: str, model: str) -> dict | None:
        """The model a device's own words point at, or ``None``.

        A **proposal**. Nothing calls this and writes the answer: the device said a string, the
        catalogue has a row whose normalised name is the same string, and a person says whether
        those are the same thing.
        """
        k = key(maker, model)
        if not k:
            return None
        rows = self.list('match_key = ?', (k,), limit=1)
        return rows[0] if rows else None

    def delete(self, uid: str, var_dir: str = '', media_dir: str = '') -> bool:
        """Quitar un modelo, con sus imágenes. `True` si había uno.

        Importar reemplaza una importación entera, que es la respuesta a «este catálogo está
        viejo» y no a «este modelo sobra». Sin esto, quitar una fila obligaba a reimportar las
        otras cinco mil.

        Las imágenes se van con él porque nadie más las mira: las guardó esta importación y les
        apunta esta fila. Dejarlas es dejar un fichero inalcanzable en una carpeta que crece
        durante toda la vida de la instalación — el mismo agujero que se tapó al reimportar.
        """
        fila = self.get(uid)
        if not fila:
            return False
        self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (str(uid),))
        # Y su historial: las versiones de algo que ya no existe no contestan a nada y se
        # quedarían para siempre.
        self.revs.forget(uid)
        for cara in ('front_image', 'rear_image'):
            nombre = str(fila.get(cara) or '')
            if nombre:
                media.forget(var_dir, nombre, media_dir)
        return True

    #: Lo que se puede escribir a mano en un modelo. Ni `uid`, ni `source`, ni la fecha: son
    #: del almacén, y dejar que una petición los toque es dejar que reescriba de dónde vino
    #: algo. Ni las imágenes, que se guardan por su propio camino.
    _EDITABLE = ('manufacturer', 'model', 'slug', 'u_tenths', 'full_depth', 'part_number',
                 'airflow', 'subdevice', 'is_powered', 'tree', 'kind', 'description', 'size',
                 'url', 'kit_qty', 'power_type')

    def create(self, row: dict, source: str = 'manual', *, actor: str = '') -> str:
        """Un modelo escrito a mano. Devuelve su `uid`.

        Para lo que no está en ninguna biblioteca: el armario que montó el electricista, la
        bandeja con el mini-PC, el dispositivo de un fabricante que no publica nada. Con su propio
        origen, así que ninguna importación lo toca — que es justo lo que hace falta cuando lo
        que se ha escrito no existe en ningún repositorio del mundo.
        """
        import json                              # noqa: PLC0415
        values = {c: row[c] for c in self._EDITABLE if c in row}
        values['manufacturer'] = str(values.get('manufacturer') or '').strip()
        values['model'] = str(values.get('model') or '').strip()
        if not values['manufacturer'] or not values['model']:
            return ''
        values.setdefault('tree', 'device-types')
        # El fabricante, como fila. Se crea si es la primera vez que aparece — que es lo que
        # pasa con el armario que alguien escribe de un fabricante que no publica nada.
        values['brand_uid'] = self.brands.ensure(values['manufacturer'])
        values['kind'] = str(values.get('kind') or '') or kind_of(dict(row, _tree=values['tree']))
        # Marcada como decidida: si se escribió a mano, se escribió a propósito.
        values['kind_set'] = 1
        values.update({
            'uid': new_uid(), 'source': str(source or 'manual'),
            'imported_at': BaseStore._now(),
            'match_key': key(values['manufacturer'], values['model']),
            'updated_at': BaseStore._now(), 'updated_by': str(actor or ''), 'rev': 1,
            'ports': json.dumps(row.get('ports') or {}, sort_keys=True),
            'port_list': json.dumps(clean_port_list(row.get('port_list')), sort_keys=True),
            'extra': json.dumps(row.get('extra') or {}, sort_keys=True),
        })
        # Las imágenes, si quien llama ya las guardó. No vienen de la petición —un nombre de
        # fichero llegado por la red no toca este disco— sino de `copy_images`, que las volvió a
        # guardar por el almacén de medios y devolvió los nombres que él acuñó.
        for cara in ('front_image', 'rear_image'):
            if media.is_name(str(row.get(cara) or '')):
                values[cara] = row[cara]
        cols = [c for c in self._COLS if c in values]
        self._db.execute(
            f'INSERT INTO {self._sql_table} ({", ".join(cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})',
            tuple(values[c] for c in cols))
        self._db.commit()
        # La primera versión es la ficha recién creada. Sin ella el historial empezaría por el
        # segundo cambio y no habría contra qué comparar el primero.
        self.revs.keep(str(values['uid']), self.get(str(values['uid'])) or {},
                       action='create', actor=actor)
        return str(values['uid'])

    def set_image(self, uid: str, face: str, name: str, *, actor: str = '') -> bool:
        """Poner o quitar la imagen de una cara. `True` si había fila.

        Aparte de `update` a propósito: lo que se guarda aquí es un nombre que **acuñó el
        almacén de medios**, no algo que alguien tecleó — y dejar `front_image` entre los campos
        editables sería dejar que una petición escribiera un nombre de fichero en esta columna.
        """
        if face not in ('front', 'rear') or not self.get(uid):
            return False
        self._db.execute(
            f'UPDATE {self._sql_table} SET {face}_image = ? WHERE uid = ?',
            (str(name or ''), str(uid)))
        self._db.commit()
        # Poner o quitar una imagen no cambia ningún campo comparable, así que la acción es lo
        # único que lo cuenta: sin ella el historial tendría un renglón vacío.
        self.revs.keep(uid, self.get(uid) or {},
                       action='image' if name else 'image_drop', actor=actor)
        return True

    def copy_images(self, origen: dict, var_dir: str = '', media_dir: str = '') -> dict:
        """Las imágenes de una fila, guardadas OTRA VEZ con nombres nuevos.

        Un clon que apuntara a los ficheros del original es una bomba de relojería: borrar
        cualquiera de los dos se lleva el fichero, y el otro se queda enseñando un hueco sin que
        nada haya fallado. Es el mismo agujero que se tapó al reimportar, y no se vuelve a abrir
        por ahorrar unos kilobytes.
        """
        fuera = {}
        for cara in ('front_image', 'rear_image'):
            nombre = str((origen or {}).get(cara) or '')
            if not nombre or not media.is_name(nombre):
                continue
            datos, err = media.read(var_dir, nombre, media_dir)
            if err or not datos:
                continue
            nuevo, err = media.save(var_dir, datos, media_dir)
            if not err and nuevo:
                fuera[cara] = nuevo
        return fuera

    def update(self, uid: str, fields: dict, *, actor: str = '') -> bool:
        """Corregir un modelo. `True` si había uno.

        Vale para los importados y no solo para los escritos a mano: la deducción no va a
        acertar los ocho mil quinientos, y quien mira la fila sabe lo que es. Corregir la clase
        deja la marca puesta, que es lo que la salva de la próxima importación.
        """
        actual = self.get(uid)
        if not actual:
            return False
        values = {c: fields[c] for c in self._EDITABLE if c in fields}
        # Los dos que son JSON. Fuera de `_EDITABLE` porque esa lista se copia en crudo y estos
        # hay que serializarlos — y por eso llevaban desde el principio **sin poder editarse**:
        # `create` los trataba aparte y aquí no los trataba nadie, así que corregir las medidas
        # de un armario o los atributos de un disco decía «guardado» y no guardaba nada. Un fallo
        # que no da error: la pantalla afirma que escribió, y al volver a abrir sigue igual.
        import json                              # noqa: PLC0415
        for campo in ('ports', 'port_list', 'extra'):
            if isinstance(fields.get(campo), dict):
                v = clean_port_list(fields[campo]) if campo == 'port_list' else fields[campo]
                values[campo] = json.dumps(v, sort_keys=True)
        if not values:
            return False
        if 'kind' in values:
            values['kind_set'] = 1
        for campo in ('manufacturer', 'model'):
            if campo in values:
                values[campo] = str(values[campo] or '').strip()
        if values.get('manufacturer') == '' or values.get('model') == '':
            return False
        # El nombre normalizado se recalcula si cambió alguno de los dos: es lo que casa un
        # dispositivo con su modelo, y dejarlo viejo rompe esa correspondencia sin decir nada.
        if 'manufacturer' in values or 'model' in values:
            values['match_key'] = key(values.get('manufacturer', actual['manufacturer']),
                                      values.get('model', actual['model']))
        values['updated_at'] = BaseStore._now()
        values['updated_by'] = str(actor or '')
        try:
            values['rev'] = int(actual.get('rev') or 1) + 1
        except (TypeError, ValueError):
            values['rev'] = 2
        cols = list(values)
        self._db.execute(
            f'UPDATE {self._sql_table} SET {", ".join(c + " = ?" for c in cols)} WHERE uid = ?',
            tuple(values[c] for c in cols) + (str(uid),))
        self._db.commit()
        self.revs.keep(uid, self.get(uid) or {}, action='edit', actor=actor)
        return True

    def drop_many(self, uids, var_dir: str = '', media_dir: str = '') -> int:
        """Quitar varios. Devuelve cuántos había.

        Uno a uno y no con un `DELETE ... IN (...)`, a propósito: cada fila puede llevar dos
        imágenes que hay que borrar del disco, y una sentencia que se lleve las filas de golpe
        dejaría los ficheros huérfanos — que es el agujero que ya se tapó al reimportar.
        """
        n = 0
        for uid in (uids or ()):
            if self.delete(uid, var_dir, media_dir):
                n += 1
        return n

    def drop_source(self, source: str, var_dir: str = '', media_dir: str = '') -> int:
        """Vaciar un origen entero. Devuelve cuántos se fueron.

        El origen es la unidad en la que ENTRARON —`replace` reemplaza uno completo— así que es
        la unidad natural en la que se van. Sin esto, deshacer una importación equivocada era
        reimportar las otras para que `replace` se la llevara por delante: rehacer el trabajo
        bueno para deshacer el malo.
        """
        filas = self.list('source = ?', (str(source or ''),))
        return self.drop_many([f['uid'] for f in filas], var_dir, media_dir)

    def kinds(self) -> list[tuple]:
        """Las clases que hay y cuántos modelos tiene cada una, para poder filtrar por ellas.

        Del catálogo entero y no de la página: un filtro que solo ofrece lo que se está viendo
        cambia de opciones al pasar de página, que es la forma más rápida de que nadie se fíe.
        """
        rows = self._db.fetchall(
            f'SELECT kind, COUNT(*) FROM {self._sql_table} '
            'GROUP BY kind ORDER BY COUNT(*) DESC') or ()
        return [(str(r[0]), int(r[1])) for r in rows]

    def trees(self) -> list[tuple]:
        """Cuántos modelos hay de cada forma: dispositivos, módulos, armarios, componentes.

        Es el filtro de primer nivel de la pantalla. Sin él, los DIMM y los armarios comparten
        tabla con los ocho mil dispositivos y no hay forma de mirar solo una de las cuatro cosas
        — que es justo como se mira: nadie busca «un armario o un DIMM».
        """
        rows = self._db.fetchall(
            f'SELECT tree, COUNT(*) FROM {self._sql_table} '
            'GROUP BY tree ORDER BY COUNT(*) DESC') or ()
        return [(str(r[0] or 'device-types'), int(r[1])) for r in rows]

    def sources(self) -> list[tuple]:
        """Los orígenes que hay y cuántos modelos tiene cada uno.

        Para poder elegir uno antes de vaciarlo. Escribirlo a mano sería teclear una etiqueta
        que ya está guardada, y equivocarse en una letra es vaciar cero modelos sin decir nada.
        """
        rows = self._db.fetchall(
            f'SELECT source, COUNT(*) FROM {self._sql_table} '
            'GROUP BY source ORDER BY source') or ()
        return [(str(r[0]), int(r[1])) for r in rows]

    def makers(self, where: str = '', params: tuple = ()) -> list[tuple]:
        """Los fabricantes y cuántos modelos tiene cada uno, opcionalmente de un subconjunto.

        Con *where* porque la rejilla tiene que OBEDECER el filtro que enseña: una lista de
        marcas con el tipo puesto en «switch» que siguiera contando sus impresoras diría una
        cosa y enseñaría otra, y las marcas sin ningún switch sobrarían enteras.
        """
        sql = f'SELECT manufacturer, COUNT(*) FROM {self._sql_table} '
        if where:
            sql += f'WHERE {where} '
        # Por el nombre en minúsculas: ordenando por el valor del carácter, la `Z` es el 90 y la
        # `a` el 97, así que `ghipsystems` acababa detrás de `Zyxel` — al final de trescientos
        # treinta y seis nombres, que es donde nadie lo busca.
        sql += 'GROUP BY manufacturer ORDER BY LOWER(manufacturer)'
        rows = self._db.fetchall(sql, params) or ()
        return [(str(r[0]), int(r[1])) for r in rows]

    def scope_of(self, rows, partial: bool = False):
        """Qué marcas cubre una importación parcial, o ``None`` si cubre la fuente entera.

        **Las que llegaron, no las que se pidieron.** Lo que autoriza a borrar un modelo viejo
        es que haya llegado su sustituto: marcar «Dell» y que no baje ni un fichero —de tres
        mil, alguno se cae— es una descarga fallida, no un fabricante que ha dejado de publicar.
        Los fabricantes marcados dicen solo una cosa, que la importación es parcial; qué cubre
        lo dicen las filas.

        Lo que sí se pierde así es la marca que arriba se ha quedado sin modelos: esa se limpia
        cuando alguien se baja la biblioteca entera, que es la importación que sí afirma algo
        sobre lo que ya no está.

        Por el nombre normalizado, que es lo único que sobrevive de una importación a otra: los
        `uid` se regeneran, y `HP`, `H.P.` y `hp` son la misma casa escrita por tres personas.
        """
        if not partial:
            return None
        alcance = {brand_slug((r or {}).get('manufacturer') or '') for r in rows}
        alcance.discard('')
        return alcance

    def replace(self, source: str, rows, var_dir: str = '', media_dir: str = '',
                partial: bool = False) -> int:
        """Put an import's worth of models in, replacing that source's previous one.

        By source and not wholesale: a panel may hold the library AND a handful of models
        somebody typed for equipment nobody has published. Clearing the table would take those
        with it, and they are the ones that cannot be fetched again.

        **Y dentro de la fuente, solo lo que la importación cubría.** Sin *partial* se
        reemplaza la fuente entera, que es lo que significa bajarse la biblioteca completa: lo
        que arriba ya no está, aquí tampoco. Con *partial*, el borrado no sale de las marcas que
        estas filas traen — marcar «Dell» en la pantalla es traerse Dell, y no una afirmación de
        que HP y Cisco han dejado de existir. Ver :meth:`scope_of`.

        Con *var_dir* se guardan además las imágenes que la lectura haya traído en `_images`, y
        se borran las de las filas que esta fuente reemplaza — solo esas. Reimportar la
        biblioteca cada pocos meses sin borrarlas llena la carpeta con ficheros a los que ya no
        apunta nadie; borrar «las que no estén en la nueva» se llevaría por delante las de los
        modelos tecleados a mano, que no vienen de ninguna importación.
        """
        source = str(source or 'library')
        rows = list(rows or ())
        alcance = self.scope_of(rows, partial)
        # Las que se van, leídas ANTES de borrarlas: de una fila borrada no queda ni el `uid`
        # con el que quitarla ni el nombre de su imagen con el que borrarla del disco.
        fuera = []
        for vieja in (self._db.fetchall(
                f'SELECT uid, manufacturer, front_image, rear_image FROM {self._sql_table} '
                'WHERE source = ?', (source,)) or ()):
            if alcance is None or brand_slug(vieja[1]) in alcance:
                fuera.append(vieja)
        if var_dir or media_dir:
            for vieja in fuera:
                for nombre in vieja[2:]:
                    if media.is_name(nombre):
                        media.forget(var_dir, nombre, media_dir)
        # Lo que una persona decidió, apuntado ANTES de borrar y por su nombre normalizado:
        # los `uid` se regeneran en cada importación, así que lo único que sobrevive de una a
        # otra es qué modelo es. Sin esto, actualizar la biblioteca se llevaría por delante
        # cuarenta correcciones hechas en marzo, en silencio y meses después.
        suyas = {}
        for r in (self._db.fetchall(
                f'SELECT match_key, kind FROM {self._sql_table} '
                'WHERE source = ? AND kind_set = 1', (source,)) or ()):
            if r[0]:
                suyas[str(r[0])] = str(r[1] or '')
        if alcance is None:
            self._db.execute(f'DELETE FROM {self._sql_table} WHERE source = ?', (source,))
        else:
            # Por `uid` y a trozos: son las filas que se acaban de leer, y un `IN` de ocho mil
            # marcadores no lo acepta ningún motor de los cuatro.
            for i in range(0, len(fuera), 400):
                trozo = [str(v[0]) for v in fuera[i:i + 400]]
                self._db.execute(
                    f'DELETE FROM {self._sql_table} '
                    f'WHERE uid IN ({", ".join("?" for _ in trozo)})', tuple(trozo))
        import json
        stamp = BaseStore._now()
        n = 0
        for row in rows:
            if not row:
                continue
            values = dict(row)
            # La imagen que vino con el modelo, guardada por el almacén de medios — que mira lo
            # que hay DENTRO del fichero para decidir si es una imagen, acuña el nombre y no
            # escribe fuera de su carpeta. Lo que el YAML decía (`true`) se sustituye por el
            # nombre de lo guardado, o se queda vacío si no había nada que guardar: una
            # afirmación de que existe una imagen no sirve para dibujarla.
            values['tree'] = str(row.get('_tree') or 'device-types')
            # Qué es, calculado UNA vez y aquí: al leer se calcularía ocho mil quinientas veces
            # por página, y el filtro tiene que poder preguntárselo a la base de datos.
            # Lo que la fila DIGA que es manda sobre la deducción. Deducir es lo que se hace
            # cuando nadie lo ha dicho; cuando alguien lo dice —un genérico del panel, una fila
            # escrita a mano— deducir es contradecirle. Ninguna importación de la biblioteca
            # trae esta clave, así que en la práctica solo pasa con lo escrito aquí.
            dicha = str(row.get('kind') or '')
            # Contra el vocabulario del ÁRBOL de la fila y no contra el de los dispositivos: en
            # `component-types` las clases son las de una pieza, y comparar con las otras haría
            # que `memory` se leyera como «no dijo nada» y se dedujera encima.
            # El fabricante de esta fila, creado la primera vez que aparece. Trescientos
            # `ensure` para ocho mil filas: el store los busca por slug y devuelve el que ya
            # está, así que la segunda vez no escribe nada.
            values['brand_uid'] = self.brands.ensure(str(values.get('manufacturer') or ''))
            vocabulario = kinds_for(values['tree'])
            values['kind'] = dicha if dicha in vocabulario else kind_of(row)
            if dicha in vocabulario:
                values['kind_set'] = 1
            # El nombre normalizado, aquí y no solo en `parse()`: por aquí pasan también las
            # filas que nadie analizó —los básicos del panel— y sin él no casan con ningún
            # dispositivo ni hay por dónde rescatar una corrección.
            if not values.get('match_key'):
                values['match_key'] = key(str(values.get('manufacturer') or ''),
                                          str(values.get('model') or ''))
            # Y si alguien ya había corregido este modelo, su decisión manda sobre la
            # deducción: es lo que significa haberla tomado.
            corregida = suyas.get(str(values.get('match_key') or ''))
            if corregida:
                values['kind'] = corregida
                values['kind_set'] = 1
            for face in ('front', 'rear'):
                datos = (row.get('_images') or {}).get(face)
                nombre = ''
                if datos and (var_dir or media_dir):
                    # A la cesta de la BIBLIOTECA: son mil doscientas imágenes que se vuelven a
                    # bajar con un botón, y mezclarlas con lo que alguien subió aquí es no poder
                    # distinguir después lo reemplazable de lo que no está en ningún otro sitio.
                    nombre, _err = media.save(var_dir, datos, media_dir, 'library')
                values[f'{face}_image'] = nombre
            values.pop('_images', None)
            values.pop('_tree', None)
            values.pop('_stem', None)
            values.update({'uid': new_uid(), 'source': source, 'imported_at': stamp,
                           'ports': json.dumps(values.get('ports') or {}, sort_keys=True),
                           'port_list': json.dumps(values.get('port_list') or {},
                                                   sort_keys=True),
                           # Lo que solo tiene un armario, como JSON igual que los puertos: la
                           # columna guarda texto y quien la lea espera texto, así que serializar
                           # aquí y no en tres sitios es lo que evita que uno de los tres olvide.
                           'extra': json.dumps(values.get('extra') or {}, sort_keys=True)})
            cols = [c for c in self._COLS if c in values]
            self._db.execute(
                f'INSERT INTO {self._sql_table} ({", ".join(cols)}) '
                f'VALUES ({", ".join("?" for _ in cols)})',
                tuple(values[c] for c in cols))
            n += 1
        self._db.commit()
        return n


#: Cómo se llama la imagen de un modelo en la biblioteca: `<fabricante>/<slug>.front.png`
#: dentro de `elevation-images/`. Es una convención del repositorio y no un formato, así que se
#: busca de varias formas y se acepta la primera que exista — un modelo cuya imagen no se
#: encuentre se queda sin ella, que es exactamente como estaba antes.
_IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg')


def _image_names(row: dict, face: str) -> list:
    """Los nombres con los que la imagen de este modelo puede estar guardada.

    La carpeta depende del árbol —los módulos están en `module-images/` y no en
    `elevation-images/`— y el nombre puede ser el slug o el modelo: los módulos suelen no traer
    slug, así que el fichero se llama como el modelo. Se prueban los dos, que son dos búsquedas
    en un diccionario y no dos peticiones.
    """
    fab = str(row.get('manufacturer') or '').strip()
    if not fab:
        return []
    carpeta = IMAGE_DIRS.get(str(row.get('_tree') or 'device-types'), 'elevation-images')
    nombres, vistos = [], set()
    # El nombre del FICHERO primero, que es el único que no hay que deducir. Un modelo puede
    # llevar una barra dentro —`CPAC-2-100/25F`— y una barra en un nombre de fichero es una
    # carpeta: el repositorio la cambia por un guion, y reproducir esa transformación aquí
    # sería copiar una regla ajena y tener que acertar también la siguiente.
    for base in (str(row.get('_stem') or '').strip(),
                 str(row.get('slug') or '').strip(),
                 str(row.get('model') or '').strip()):
        if not base or base in vistos:
            continue
        vistos.add(base)
        nombres += [f'{carpeta}/{fab}/{base}.{face}{ext}' for ext in _IMG_EXT]
    return nombres


def _wants(row: dict, face: str) -> bool:
    """Si merece la pena buscar la imagen de esa cara.

    Un dispositivo lo DICE en su YAML (`front_image: true`), y preguntárselo antes evita doce mil
    búsquedas que casi siempre dicen que no.

    Un módulo no lo dice nunca —su YAML no trae ese campo— y sin embargo la mitad tienen imagen
    en `module-images/`. Fiarse del campo ahí es no encontrar ninguna, así que para ellos se
    busca siempre: son búsquedas en un diccionario que ya está en memoria, no peticiones.
    """
    if str(row.get('_tree') or '') == 'module-types':
        return True
    dicho = str(row.get(f'{face}_image') or '').strip().lower()
    return dicho not in ('', 'false', '0', 'none')


def read_dir(root: str):
    """Parse a directory of the library, skipping what is not a device type.

    Cada modelo sale con sus imágenes leídas si estaban al lado: ``row['_images']`` es
    ``{cara: bytes}``, y quien guarde decide qué hacer con ellas. Aquí no se escribe nada — este
    módulo lee, y mezclar leer con escribir es lo que convierte un importador en algo que hay
    que revisar entero cada vez que se toca.
    """
    import os as _os                                             # noqa: PLC0415
    for path in walk(root):
        try:
            with io.open(path, encoding='utf-8') as fh:
                row = parse(fh.read())
        except OSError:
            continue
        if not row:
            continue
        row['_images'] = {}
        for face in ('front', 'rear'):
            if not _wants(row, face):
                continue
            for rel in _image_names(row, face):
                completo = _os.path.join(root, *rel.split('/'))
                try:
                    if _os.path.getsize(completo) > media.MAX_BYTES:
                        break
                    with io.open(completo, 'rb') as fh:
                        row['_images'][face] = fh.read()
                    break
                except OSError:
                    continue
        yield row


def read_zip(path: str):
    """…and the same from a zip, which is how an isolated install gets one.

    Entries are read by name from the archive index and never extracted: a zip that names
    ``../../etc/anything`` is a zip that writes outside the directory it was told to use, and
    the only reliable defence is to never put its contents on a disk. Nothing here needs to.

    **El envoltorio se quita.** GitHub sirve un repositorio metido en una carpeta que lleva su
    nombre y su rama, y las imágenes se buscan por `elevation-images/<Fabricante>/…`. Con el
    envoltorio puesto ninguno de los dos nombres es incorrecto y tampoco son el mismo: la
    búsqueda devuelve `None` sin decir por qué, y salen ocho mil modelos sin una sola imagen.
    """
    with zipfile.ZipFile(path) as zf:
        envoltorio = gh.wrapper_of(zf.infolist())
        dentro = {gh.member_inner(i, envoltorio).lower(): i
                  for i in zf.infolist() if not i.is_dir()}
        # ¿Tiene la forma de la biblioteca? Se decide MIRANDO EL ARCHIVO ENTERO y una sola vez.
        #
        # Si la tiene, el árbol de cada fichero dice qué es —un módulo entra como módulo y un
        # armario como armario— y lo que está fuera de los tres árboles no es un modelo: es el
        # README del repositorio, o sus tests, o su esquema.
        #
        # Si no la tiene, entra todo YAML como dispositivo. Es el zip que alguien prepara a mano, y
        # nadie se inventa `device-types/<Fabricante>/` para catorce ficheros propios.
        arboles = {p[0] for p in (_split_path(k) for k in dentro) if p}
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(('.yaml', '.yml')):
                continue
            partido = _split_path(gh.member_inner(info, envoltorio))
            if arboles and not partido:
                continue
            # An entry big enough to be a decompression bomb is not a device type: the largest
            # real one is a few kilobytes.
            if info.file_size > 512 * 1024:
                continue
            try:
                row = parse(zf.read(info).decode('utf-8', 'replace'))
            except Exception:                   # pylint: disable=broad-except
                continue
            if not row:
                continue
            row['_tree'] = partido[0] if partido else 'device-types'
            row['_stem'] = gh.member_inner(info, envoltorio).split('/')[-1].rsplit('.', 1)[0]
            # Las imágenes, del mismo índice y sin extraer nada. El índice se mira una vez y no
            # una por modelo: mil modelos por seis nombres por dos caras contra una lista de
            # doce mil entradas es un cuadrado que se nota.
            row['_images'] = {}
            for face in ('front', 'rear'):
                if not _wants(row, face):
                    continue
                for rel in _image_names(row, face):
                    entrada = dentro.get(rel.lower())
                    if entrada is None or entrada.file_size > media.MAX_BYTES:
                        continue
                    try:
                        row['_images'][face] = zf.read(entrada)
                        break
                    except Exception:           # pylint: disable=broad-except
                        continue
            yield row


# ══ De GitHub, y enseñando antes qué hay ════════════════════════════════════════════════
#
# La biblioteca vive en `netbox-community/devicetype-library` —o donde diga la configuración: hay
# quien mantiene un fork con sus propios equipos—. Son más de seis mil modelos de doscientos
# fabricantes, y una instalación con equipos de cinco no quiere los otros ciento noventa y cinco:
# importarlo todo llena el buscador de ruido para siempre.
#
# **No se descarga el repositorio.** Pesa ochocientos cincuenta megas porque lleva una imagen de
# alzado por dispositivo. Lo que se pide es el índice —una petición, tres megas de nombres— y de ahí
# salen los fabricantes y sus cuentas sin bajar ningún modelo. Al importar se piden solo los
# ficheros de los fabricantes elegidos.
#
# La forma del repositorio es la que da por hecho todo esto: `device-types/<Fabricante>/*.yaml`,
# `module-types/<Fabricante>/*.yaml` y `elevation-images/<Fabricante>/<slug>.<cara>.<ext>`.

#: De dónde se trae si la configuración no dice otra cosa. Aquí y no en la pantalla: el valor por
#: defecto del registro y este tienen que ser el mismo, y dos sitios se separan.
LIBRARY_URL = 'https://github.com/netbox-community/devicetype-library'

#: Lo que puede traer de esa biblioteca. `device-types` son dispositivos enteros; `module-types`, lo
#: que va en una bahía —tarjetas de línea, transceptores— y de ahí saldrá un componente relleno
#: en vez de tecleado; `rack-types`, los armarios, con sus medidas y lo que aguantan.
#:
#: Los tres a la vez y distinguidos, que es lo que faltaba: entrar mezclados hacía que un armario
#: de 42U figurara como un equipo de 42U y que un transceptor ocupara U en un alzado.
LIBRARY_TREES = ('device-types', 'module-types', 'rack-types')

#: Y los que una fila puede declarar: los tres de la biblioteca más el de los componentes, que
#: no se descarga de ninguna parte. Dos constantes y no una porque son dos preguntas —qué se
#: puede IMPORTAR y qué puede SER una fila— y mezclarlas haría que el importador saliera a
#: buscar una carpeta `component-types/` que no existe en ningún repositorio.
TREES = LIBRARY_TREES + (COMPONENT_TREE,)

#: Dónde vive la imagen de cada uno. Los dispositivos en `elevation-images/`, los módulos en
#: `module-images/` — y buscar las segundas en la primera carpeta es no encontrar ninguna.
IMAGE_DIRS = {'device-types': 'elevation-images',
              'module-types': 'module-images',
              'rack-types': 'elevation-images'}

#: Cuántos ficheros como mucho en una importación. Cada uno es una petición, y aunque
#: `raw.githubusercontent.com` no gasta del límite de la API, seis mil peticiones seguidas son
#: media hora y una forma muy educada de que a uno lo bloqueen. Quien quiera la biblioteca entera
#: tiene la otra puerta: clonarla y apuntar a la carpeta.
MAX_FILES = 2000

#: Lo que puede ocupar un modelo. Un YAML de estos son dos kilobytes; doscientos cincuenta mil
#: dejan sitio a un chasis con cuatrocientos puertos declarados uno a uno.
MAX_YAML = 256 * 1024

_YAML_EXT = ('.yaml', '.yml')

#: Lo que puede pesar el repositorio entero. El de NetBox ronda los ochocientos cincuenta megas
#: —una imagen de alzado por dispositivo— y mil quinientos dejan sitio a que crezca sin dejar sitio a
#: que una dirección equivocada llene un disco.
MAX_LIBRARY_ZIP = 1536 * 1024 * 1024


def _split_path(rel: str):
    """``device-types/HP/DL380.yaml`` → ``('device-types', 'HP', 'DL380.yaml')``, o ``None``.

    Menos de tres partes es un fichero suelto del repositorio —el README, la licencia, el
    esquema— y no un modelo. Se descarta aquí y no en tres sitios.
    """
    partes = str(rel or '').split('/')
    if len(partes) < 3 or partes[0] not in LIBRARY_TREES:
        return None
    if not partes[-1].lower().endswith(_YAML_EXT):
        return None
    return partes[0], partes[1], partes[-1]


def browse(url: str = '', token: str = '') -> dict:
    """Qué fabricantes trae la biblioteca, sin importar nada todavía.

    ``{'vendors': [{'name', 'device_types', 'module_types', 'rack_types'}], 'paths': […],
    'error': ''}``.

    Una petición y ningún modelo descargado. Los nombres de los ficheros ya contestan la
    pregunta —cuántos hay por fabricante— y abrirlos para contarlos costaría seis mil descargas
    para enseñar una lista.

    *paths* es el índice tal cual, para que la importación posterior no lo vuelva a pedir.
    """
    rutas, err = gh.list_tree(str(url or LIBRARY_URL), token)
    if err:
        return {'vendors': [], 'paths': [], 'error': err}
    cuenta: dict = {}
    for rel in rutas:
        partido = _split_path(rel)
        if not partido:
            continue
        arbol, fabricante, _fichero = partido
        fila = cuenta.setdefault(fabricante, {'name': fabricante, 'device_types': 0,
                                              'module_types': 0, 'rack_types': 0})
        fila[arbol.replace('-', '_')] += 1
    return {'vendors': sorted(cuenta.values(), key=lambda v: v['name'].lower()),
            'paths': rutas, 'error': ''}


def read_remote(url: str = '', vendors=None, paths=None, on_progress=None, token: str = ''):
    """Los modelos de los fabricantes elegidos, pedidos por una sola conexión.

    *vendors* vacío o `None` significa todos, y eso son seis mil peticiones: la pantalla obliga
    a elegir, pero esto acepta las dos cosas porque una importación programada no tiene a nadie
    a quien preguntar. :data:`MAX_FILES` es lo que impide que «todos» sea media hora.

    *paths* es el índice que :func:`browse` ya trajo. Sin él se vuelve a pedir — una petición
    más, no un problema, pero pasarlo ahorra la única llamada que sí gasta del límite de la API.

    *on_progress* recibe ``(hechos, total, fase)`` por cada fichero pedido, con *fase* en
    ``'index'`` (pidiendo el índice, todavía sin total), ``'models'`` o ``'images'``. Aquí SÍ hay total —elegir los fabricantes ya dijo cuántos
    ficheros son— al revés que en un zip, donde nadie sabe cuántos modelos trae hasta leerlo.

    **Dos pasadas.** Primero los YAML, después las imágenes que esos YAML dijeron tener: qué
    imágenes hacen falta no se sabe hasta haber leído el modelo. Las dos por la misma conexión,
    que es lo que separa quince segundos de minuto y medio.

    Cada modelo sale con sus imágenes ya leídas, igual que :func:`read_zip`, y con `_tree` para
    que quien guarde sepa si es un dispositivo o un módulo: son la misma forma con dos significados,
    y mezclarlos haría que un transceptor apareciera como algo que ocupa U.
    """
    url = str(url or LIBRARY_URL)
    # Lo primero que pasa es esto, y tarda: tres megas de nombres de fichero. Se dice ANTES de
    # empezar porque hasta que llegue no hay total que enseñar, y sin decir nada lo que se ve
    # durante ese rato es un cero que parece que se ha colgado.
    if on_progress:
        on_progress(0, 0, 'index')
    if paths is None:
        paths, err = gh.list_tree(url, token)
        if err:
            raise RuntimeError(err)
    quiero = {str(v).lower() for v in (vendors or ())}
    # El índice como conjunto, para preguntar por una imagen sin recorrer once mil nombres por
    # cada cara de cada modelo. En minúsculas porque el fabricante de la carpeta de imágenes y
    # el del YAML no siempre coinciden en mayúsculas.
    indice = {str(p).lower(): str(p) for p in paths}
    elegidos = [rel for rel in paths
                if _split_path(rel) and (not quiero
                                         or _split_path(rel)[1].lower() in quiero)]
    if len(elegidos) > MAX_FILES:
        raise RuntimeError('dcim_catalog_too_many')

    # ── Pasada 1: los modelos ───────────────────────────────────────────────────────────
    #
    # Y avisando de cada uno MIENTRAS se baja, no al entregarlo. Las filas no salen de aquí hasta
    # el final —hay una segunda pasada de por medio— así que quien cuente lo entregado contará
    # cero durante todo el trabajo, que fue exactamente lo que enseñaba la pantalla.
    filas = []
    quiere_imagen = {}                          # ruta de la imagen -> [(fila, cara), ...]
    for hecho, (rel, datos, err) in enumerate(
            gh.fetch_many(url, elegidos, MAX_YAML), 1):
        if on_progress:
            on_progress(hecho, len(elegidos), 'models')
        if err or datos is None:
            # Un modelo que no baja no para la importación: son miles de ficheros de un
            # repositorio ajeno y uno roto no puede costar los demás.
            continue
        try:
            row = parse(datos.decode('utf-8', 'replace'))
        except Exception:                       # pylint: disable=broad-except
            continue
        if not row:
            continue
        row['_tree'] = rel.split('/')[0]
        # Cómo se llama el fichero, sin extensión: es el nombre con el que estará su imagen.
        row['_stem'] = rel.split('/')[-1].rsplit('.', 1)[0]
        row['_images'] = {}
        filas.append(row)
        for face in ('front', 'rear'):
            if not _wants(row, face):
                continue
            for nombre in _image_names(row, face):
                real = indice.get(nombre.lower())
                if real is not None:
                    quiere_imagen.setdefault(real, []).append((row, face))
                    break

    # ── Pasada 2: las imágenes que los modelos dijeron tener ────────────────────────────
    if quiere_imagen:
        cuantas = len(quiere_imagen)
        for hecho, (rel, datos, err) in enumerate(
                gh.fetch_many(url, list(quiere_imagen), media.MAX_BYTES), 1):
            if on_progress:
                # Su propia fase y su propio total: bajar seiscientos modelos y bajar sus
                # imágenes son dos trabajos de duración distinta, y una sola barra para los dos
                # se queda parada en la mitad sin explicar por qué.
                on_progress(hecho, cuantas, 'images')
            if err or datos is None:
                continue
            # Por nombre y no por posición: `fetch_many` devuelve la ruta que pidió, y fiarse
            # del orden sería fiarse de que ninguna se saltó.
            for row, face in quiere_imagen.get(rel, ()):
                row['_images'][face] = datos

    for row in filas:
        yield row


def read_whole(url: str = '', var_dir: str = '', on_progress=None):
    """Todos los modelos, bajándose el repositorio de una vez.

    La otra cara de :func:`read_remote`, y la que conviene cuando se quieren **todos**: pedir
    diez mil ochocientos ficheros de uno en uno son tres cuartos de hora aunque la conexión se
    reutilice, y el mismo contenido en un zip baja en poco más de un minuto. Para tres
    fabricantes es al revés, y por eso están las dos.

    Devuelve lo mismo que :func:`read_zip` —de hecho es quien lee— con las imágenes ya sacadas
    del propio archivo. Nada se extrae a disco: se lee por el índice del zip.

    El archivo se borra al terminar. Ochocientos cincuenta megas no son una caché que ahorre una
    descarga dentro de seis meses, son un disco lleno esperando a que nadie se acuerde.
    """
    url = str(url or LIBRARY_URL)
    zip_url, _dentro = gh.zip_url(url)
    if not zip_url:
        raise RuntimeError('dcim_catalog_bad_url')
    if on_progress:
        on_progress(0, 0, 'download')

    def _bajando(hechos, total):
        if on_progress:
            # En megas y no en bytes: lo que se enseña es un número que alguien lee, y
            # ochocientos cincuenta millones no se leen.
            on_progress(hechos // (1024 * 1024), (total or 0) // (1024 * 1024), 'download')

    # Sin carpeta de caché a propósito: `download` deja el archivo en un temporal y no lo guarda
    # entre usos, que es lo que hay que hacer con algo de este tamaño.
    ruta, err, _cache = gh.download(zip_url, MAX_LIBRARY_ZIP, _bajando)
    if err or not ruta:
        raise RuntimeError(err or 'dcim_catalog_download_failed')
    try:
        if on_progress:
            on_progress(0, 0, 'models')
        for hechas, row in enumerate(read_zip(ruta), 1):
            if on_progress and hechas % 50 == 0:
                # Cada cincuenta y no cada uno: leer el zip va deprisa, y avisar ocho mil veces
                # es ocho mil escrituras para una barra que solo puede moverse cien.
                on_progress(hechas, 0, 'models')
            yield row
    finally:
        # Siempre, salga bien o mal: si esto no se borra, cada importación deja ochocientos
        # cincuenta megas en el temporal del sistema — que es exactamente lo que ya pasó una vez
        # con los archivos de las MIB.
        gh._rm_quiet(ruta)                      # noqa: SLF001
