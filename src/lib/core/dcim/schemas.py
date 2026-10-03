#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Los esquemas: qué campos tiene un modelo, dicho por quien publica la biblioteca.

Hasta ahora el formulario de escribir un modelo llevaba **mi lista de campos**, escrita mirando
unos cuantos YAML. Funciona hasta que la biblioteca añade uno —o hasta que alguien inventa una
clase de cosa que aquí no existe— y entonces hay que tocar el código para poder teclear un dato.

El repositorio publica `schema/devicetype.json`, `schema/moduletype.json` y `schema/racktype.json`:
la lista exacta de lo que puede traer cada cosa, con sus tipos y sus valores permitidos. Traerlos
es cambiar una lista escrita a mano por el dato de quien manda sobre él — la misma idea que el
registro de configuración de este panel: *el esquema es el dato, la pantalla la presentación*.

Y **clonarlos**, que es la otra mitad. Una sala tiene cosas que no están en ningún repositorio: un
cuadro eléctrico, una caja de fibra, un armario ignífugo de cintas. Un esquema propio —clonado del
que más se le parezca y con los campos que hagan falta— deja escribirlas con sus datos en vez de
meterlas como «otro» y apuntar lo demás en la descripción.

**Un esquema no es una tabla.** Los campos que este panel sabe guardar en una columna van a su
columna; el resto va a `extra`, que para eso está. Un esquema que pudiera crear columnas sería un
esquema capaz de romper la base de datos desde un formulario.
"""

from __future__ import annotations

import json

from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

#: Dónde vive cada esquema dentro del repositorio, y a qué árbol describe. Los nombres son de la
#: biblioteca y no se traducen: es el fichero que hay que ir a leer si algo no cuadra.
LIBRARY_FILES = (
    ('schema/devicetype.json', 'device-types'),
    ('schema/moduletype.json', 'module-types'),
    ('schema/racktype.json', 'rack-types'),
)

#: Las definiciones compartidas a las que apuntan los `$ref`. Sin resolverlas, la mitad de los
#: campos con lista de valores —el flujo de aire, la unidad de peso— se quedarían sin ella y el
#: formulario los pediría como texto libre: escribir «kilos» donde el importador espera `kg`.
LIBRARY_DEFS = 'schema/generated_schema.json'

#: Qué campo del esquema acaba en qué columna. Lo que no esté aquí va a `extra`, que es lo que
#: permite que un esquema propio pida cosas que esta tabla no conoce sin tocar la tabla.
FIELD_COLUMN = {
    'manufacturer': 'manufacturer',
    'model': 'model',
    'slug': 'slug',
    'description': 'description',
    'part_number': 'part_number',
    'airflow': 'airflow',
    'subdevice_role': 'subdevice',
    'u_height': 'u_height',                     # se convierte a décimas al guardar
    'is_full_depth': 'full_depth',
    'is_powered': 'is_powered',
}

#: Las familias de puerto. No son campos sueltos: son listas de componentes en el YAML, y aquí se
#: guardan **contadas**, que es lo que cabe en una pantalla y lo que sirve para una capacidad.
PORT_FIELDS = ('interfaces', 'power-ports', 'power-outlets', 'console-ports',
               'console-server-ports', 'front-ports', 'rear-ports', 'module-bays',
               'device-bays', 'inventory-items')

#: Lo que no se teclea nunca: las imágenes las guarda el almacén de medios con su propio nombre,
#: y `comments` es texto largo del que ninguna pantalla puede hacer nada.
SKIP_FIELDS = ('front_image', 'rear_image', 'comments', 'attribute_data', 'profile')

SCHEMA = TableSpec(
    name='dc_schema',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        Column('name',        'TEXT', nullable=False, default="''"),
        # A qué árbol describe: un esquema de armario no sirve para un transceptor. Vacío en uno
        # propio que no quiera parecerse a ninguno de los tres.
        Column('tree',        'TEXT', nullable=False, default="'device-types'"),
        # De dónde vino: `library` se puede volver a traer y se sobrescribe; `manual` es de quien
        # lo escribió y no lo toca ninguna descarga.
        Column('source',      'TEXT', nullable=False, default="'manual'"),
        # De cuál se clonó, para poder decirlo. No es una dependencia: el clon es suyo desde el
        # momento en que existe, y borrar el original no lo deja cojo.
        Column('based_on',    'TEXT', nullable=False, default="''"),
        # Los campos, como JSON: `[{name, type, enum, required, target}]`. En una columna porque
        # un esquema es un documento —se lee entero o no se lee— y una tabla de campos sería
        # cinco filas por esquema para no preguntar nunca por una sola.
        Column('fields',      'TEXT', nullable=False, default="'[]'"),
        Column('imported_at', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_schema_name', ('name',)),),
)


def _resolve(prop: dict, defs: dict) -> dict:
    """Un campo del esquema, con su `$ref` ya seguido.

    `weight_unit` no dice `enum: [kg, g, lb, oz]`: dice «mira la definición compartida». Sin
    seguirla, el formulario pide texto libre y alguien escribe «kilos» donde el importador
    espera `kg` — y eso no falla, se guarda mal.
    """
    ref = str(prop.get('$ref') or '')
    if ref and '/definitions/' in ref:
        nombre = ref.rsplit('/', 1)[-1]
        prop = dict(defs.get(nombre) or {}, **{k: v for k, v in prop.items() if k != '$ref'})
    return prop


def parse(doc: dict, defs: dict | None = None) -> list:
    """Un esquema JSON como la lista de campos que este panel puede pedir.

    Cada uno sale con ``{name, type, enum, required, target}``. *target* es dónde acabará el
    valor: una columna, `extra` o la cuenta de puertos — y se decide **aquí**, una vez, porque
    tres pantallas decidiéndolo por su cuenta son tres formas de guardar lo mismo en sitios
    distintos.
    """
    defs = (defs or {}).get('definitions') if isinstance(defs, dict) else None
    defs = defs or {}
    props = doc.get('properties') if isinstance(doc, dict) else None
    if not isinstance(props, dict):
        return []
    req = set(doc.get('required') or ())
    out = []
    for nombre in sorted(props):
        if nombre in SKIP_FIELDS:
            continue
        prop = _resolve(props[nombre] if isinstance(props[nombre], dict) else {}, defs)
        if nombre in PORT_FIELDS:
            tipo, destino = 'count', 'ports'
        elif nombre in FIELD_COLUMN:
            tipo, destino = str(prop.get('type') or 'string'), 'column'
        else:
            tipo, destino = str(prop.get('type') or 'string'), 'extra'
        out.append({'name': nombre, 'type': tipo, 'target': destino,
                    'enum': [str(v) for v in (prop.get('enum') or [])],
                    'required': nombre in req})
    return out


def fetch(url: str, gh) -> tuple:
    """Los tres esquemas de una biblioteca. ``([{name, tree, fields}], '')`` o ``([], motivo)``.

    Cuatro ficheros pequeños por la misma conexión: los tres esquemas y las definiciones que los
    tres comparten. No gasta del límite de la API —van por `raw`— y no baja ningún modelo.
    """
    quiero = [LIBRARY_DEFS] + [f for f, _t in LIBRARY_FILES]
    crudo = {}
    for rel, datos, err in gh.fetch_many(url, quiero, 512 * 1024):
        if err or datos is None:
            continue
        try:
            crudo[rel] = json.loads(datos.decode('utf-8', 'replace'))
        except Exception:                       # pylint: disable=broad-except
            continue
    if not crudo:
        return [], 'dcim_schema_not_found'
    defs = crudo.get(LIBRARY_DEFS) or {}
    salida = []
    for fichero, arbol in LIBRARY_FILES:
        doc = crudo.get(fichero)
        if not doc:
            continue
        campos = parse(doc, defs)
        if campos:
            salida.append({'name': fichero.rsplit('/', 1)[-1].replace('.json', ''),
                           'tree': arbol, 'fields': campos})
    return (salida, '') if salida else ([], 'dcim_schema_not_found')


class SchemaStore(BaseStore):
    """Los esquemas guardados: los traídos de la biblioteca y los que alguien escribió."""

    _TABLE = SCHEMA.name
    _COLS = tuple(c.name for c in SCHEMA.columns)

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(SCHEMA)

    def _row(self, row) -> dict:
        out = {name: row[i] for i, name in enumerate(self._COLS)}
        try:
            out['fields'] = json.loads(out.get('fields') or '[]')
        except Exception:                       # pylint: disable=broad-except
            out['fields'] = []
        return out

    def list(self) -> list[dict]:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} '
            'ORDER BY source, LOWER(name)') or ()
        return [self._row(r) for r in rows]

    def get(self, uid: str) -> dict | None:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE uid = ?',
            (str(uid or ''),)) or ()
        return self._row(rows[0]) if rows else None

    def by_name(self, name: str) -> dict | None:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE name = ?',
            (str(name or ''),)) or ()
        return self._row(rows[0]) if rows else None

    def save(self, name: str, tree: str, fields: list, source: str = 'manual',
             based_on: str = '') -> str:
        """Guardar uno, reemplazando el que tuviera ese nombre. Devuelve su `uid`.

        Por nombre y no por identificador porque volver a traer la biblioteca tiene que
        **actualizar** los tres, no añadir tres más cada vez. Un esquema propio que se llame
        igual que uno de la biblioteca se sobrescribiría, y por eso la pantalla no deja
        repetir el nombre: es la única defensa, y está donde se elige.
        """
        nombre = str(name or '').strip()
        if not nombre:
            return ''
        anterior = self.by_name(nombre)
        uid = anterior['uid'] if anterior else new_uid()
        datos = (uid, nombre, str(tree or ''), str(source or 'manual'), str(based_on or ''),
                 json.dumps(fields or [], sort_keys=True), BaseStore._now())
        if anterior:
            self._db.execute(
                f'UPDATE {self._sql_table} SET name = ?, tree = ?, source = ?, based_on = ?, '
                'fields = ?, imported_at = ? WHERE uid = ?', datos[1:] + (uid,))
        else:
            self._db.execute(
                f'INSERT INTO {self._sql_table} ({", ".join(self._COLS)}) '
                f'VALUES ({", ".join("?" for _ in self._COLS)})', datos)
        self._db.commit()
        return uid

    def delete(self, uid: str) -> bool:
        if not self.get(uid):
            return False
        self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (str(uid),))
        self._db.commit()
        return True
