#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qué se pregunta de un componente de cada clase — y de dónde sale esa lista.

«Samsung PM9A3 · 1.92 TB» alcanza para reconocer un disco en una lista y no alcanza para
comprarlo: hace falta saber si es M.2 o de 2,5", si va por NVMe o por SATA, y si la bahía que hay
libre lo admite. Eso cambia con cada clase —una CPU tiene zócalo y núcleos, un transceptor tiene
alcance— así que no cabe en columnas.

**Y no cabe en el código.** Once clases con cuatro atributos escritas en un fichero `.py` son una
lista que hay que publicar una release para tocar, y quien sabe qué formato tiene la tarjeta
nueva casi nunca es quien toca el código. Así que es un JSON:

* el que **viene con el panel** (``data/component_profiles.json``), que se revisa en un commit y
  lo reemplaza cada actualización;
* y el que alguien **guarde en la base de datos**, que sobrevive a la actualización y viaja en la
  copia de seguridad — que es la razón de que sea la base de datos y no un fichero en el disco:
  un despliegue con contenedor web y contenedor de trabajos **comparte la base y no el disco**.

**Manda la versión más alta.** El número es justo para eso: una actualización del panel que
publique la 3 supera a un parche local que iba por la 2, y un parche local que va por la 4 sigue
en pie hasta que el panel publique la 5. Sin el número habría que elegir entre que una mejora
publicada no llegue nunca a quien tocó algo una vez, o que un parche desaparezca sin aviso.

El nombre de cada campo se traduce con ``dcim_attr_<nombre>``; uno que esta pantalla no conozca
se enseña tal cual — peor que una palabra y mucho mejor que un hueco, que es lo que haría un
fichero que solo el código sabe leer.
"""

from __future__ import annotations

import json
import os

from lib.core.dcim.revisions import RevisionStore
from lib.core.dcim.store import PART_KINDS
from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec
from lib.db.store_base import BaseStore

#: El que viene con el panel.
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data',
                    'component_profiles.json')

#: Cómo se llama este documento en la tabla. Con nombre y no una tabla de una fila, porque el
#: siguiente documento que alguien quiera poder actualizar sin una release no tiene por qué
#: estrenar una tabla.
NAME = 'component'

#: Con qué nombre viven sus versiones en `dc_rev`. Distinto del de una ficha del catálogo porque
#: son dos cosas: una es un modelo y la otra es la lista de qué preguntar de los modelos.
SCOPE = 'profile'

#: Las formas de control que la pantalla sabe dibujar. Una lista cerrada: un `type` inventado en
#: un JSON saldría como una caja de texto sin decir que no se entendió, y quien lo escribió
#: creería que funcionó.
#:
#: `date` se guarda como texto ISO, por lo mismo que la garantía de un equipo: son tres motores
#: con tres tipos de fecha, y lo único que se hace con esto es ordenarlo y compararlo — que en
#: ISO es lo mismo.
TYPES = ('text', 'number', 'bool', 'date', 'enum')

SCHEMA = TableSpec(
    name='dc_profile',
    columns=(
        Column('name',       'TEXT', primary_key=True),
        Column('version',    'INTEGER', nullable=False, default='0'),
        Column('body',       'TEXT', nullable=False, default="'{}'"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
)

_CACHE: dict | None = None


def packaged() -> dict:
    """El documento que viene con el panel. Leído una vez: no cambia mientras corre el proceso.

    Un fichero roto **no tumba la sección**: sale un documento vacío y los componentes se quedan
    sin atributos, que es una pantalla más pobre y no una pantalla que no abre. Con el catálogo
    entero detrás, romper la lista de atributos no puede impedir mirar un modelo.
    """
    global _CACHE                               # noqa: PLW0603
    if _CACHE is None:
        try:
            with open(FILE, encoding='utf-8') as fh:
                _CACHE = normalise(json.load(fh))
        except Exception:                       # pylint: disable=broad-except
            _CACHE = {'version': 0, 'common': [], 'kinds': {}, 'size': {}}
    return _CACHE


def normalise(doc) -> dict:
    """Un documento, limpio: solo clases que existen y solo controles que se saben dibujar.

    Se limpia al leer y no al escribir porque también se lee el que viene con el panel, y una
    comprobación que solo corre en la puerta de entrada no protege del fichero que llega por la
    otra.
    """
    doc = doc if isinstance(doc, dict) else {}
    try:
        version = int(doc.get('version') or 0)
    except (TypeError, ValueError):
        version = 0
    kinds = {}
    for clase, campos in (doc.get('kinds') or {}).items():
        if str(clase) not in PART_KINDS:
            continue                            # un perfil de una clase que no existe no sale
        limpios = _fields(campos)
        if limpios:
            kinds[str(clase)] = limpios
    # Cómo se llama la casilla de tamaño en cada clase, y con qué ejemplo. Se limpia igual que
    # todo lo demás: una clase que no existe aquí sería una etiqueta que no sale nunca.
    tam = {}
    for clase, d in (doc.get('size') or {}).items():
        if str(clase) in PART_KINDS and isinstance(d, dict):
            tam[str(clase)] = {'label': str(d.get('label') or ''),
                               'hint': str(d.get('hint') or ''),
                               # Las unidades en las que se escribe. Sin ellas la casilla es
                               # texto libre, que es lo que hace falta donde el tamaño no es una
                               # magnitud —«media altura», «doble ancho»—.
                               'units': [str(u) for u in (d.get('units') or []) if str(u)]}
    return {'version': version, 'common': _fields(doc.get('common')), 'kinds': kinds,
            'size': tam}


#: Bloques con nombre propio dentro de una ficha. Ahora mismo uno: las fechas de la vida de
#: un modelo —se lanza, deja de venderse, deja de recibir parches, deja de poder contratarse
#: soporte— que son seis y responden a preguntas distintas, y sueltas entre los atributos son
#: seis casillas de fecha seguidas sin decir de qué van.
GROUPS = ('lifecycle',)


def group_fields(store, grupo: str) -> list:
    """Los campos comunes de un bloque, en el orden en que el documento los pone.

    Del documento y no de una lista aquí: añadir «fin de venta en Europa» tiene que ser editar
    un JSON, que es para lo que se sacó del código.
    """
    return [c for c in (effective(store).get('common') or ())
            if str(c.get('group') or '') == str(grupo)]


def _fields(campos) -> list:
    fuera = []
    for c in (campos if isinstance(campos, list) else ()):
        if not isinstance(c, dict):
            continue
        nombre = str(c.get('name') or '').strip()
        tipo = str(c.get('type') or 'text')
        if not nombre or tipo not in TYPES:
            continue
        campo = {'name': nombre, 'type': tipo}
        # De qué magnitud es la unidad. El desplegable sale pegado a ella y sin etiqueta propia:
        # el peso y su unidad son un dato y no dos, y separarlos ocupa el doble para decir menos.
        de = str(c.get('unit_of') or '').strip()
        if de:
            campo['unit_of'] = de
        # Y si escribe en una COLUMNA del modelo en vez de en `extra`. Es para lo que ya tiene
        # sitio propio —la disipación es la misma columna que la de un servidor— y guardarlo dos
        # veces serían dos respuestas a la misma pregunta que pueden discrepar.
        if c.get('column'):
            campo['column'] = True
        # En qué bloque se dibuja. Vocabulario cerrado a propósito: un grupo mal escrito sería
        # una sección entera que no sale en ninguna pantalla y que nadie echa de menos porque
        # nunca existió.
        grupo = str(c.get('group') or '').strip()
        if grupo in GROUPS:
            campo['group'] = grupo
        if tipo == 'enum':
            campo['enum'] = [str(v) for v in (c.get('enum') or []) if str(v) != '']
            if not campo['enum']:
                continue                        # un desplegable sin opciones no es un campo
        fuera.append(campo)
    return fuera


def problems(doc) -> list:
    """Qué se ha tirado de un documento que alguien sube. Vacío = entró entero.

    Se **dice** en vez de aceptarlo en silencio: un JSON con una clase mal escrita se guarda
    igual y deja media pantalla sin atributos, y quien lo subió no tiene forma de enterarse hasta
    que alguien va a rellenar una ficha.
    """
    doc = doc if isinstance(doc, dict) else {}
    fuera = []
    for clase, campos in (doc.get('kinds') or {}).items():
        if str(clase) not in PART_KINDS:
            fuera.append(f'kind:{clase}')
            continue
        limpios = {c['name'] for c in _fields(campos)}
        for c in (campos if isinstance(campos, list) else ()):
            nombre = str((c or {}).get('name') or '') if isinstance(c, dict) else ''
            if nombre not in limpios:
                fuera.append(f'{clase}.{nombre or "?"}')
    return fuera


def effective(store=None) -> dict:
    """El documento que manda: el del panel o el guardado, el de **versión más alta**.

    Con una excepción: **`common` se suma**. Ahí es donde el panel añade lo que pregunta de
    cualquier cosa —las seis fechas del ciclo de vida entraron por ahí— y quien hubiera guardado
    un documento con un número más alto antes de que existieran se quedaría sin ellas: sin error,
    sin aviso, y sin nada que relacione el hueco con aquella edición. Un campo que está en el
    código, que se sirve, y que no sale nunca.

    El guardado sigue mandando **campo a campo**: quien haya redefinido el peso se queda con el
    suyo. Lo que se pierde es poder borrar un campo común guardando un documento sin él, y eso a
    cambio de que ninguna instalación se quede sin lo que se publique.

    `kinds` y `size` no se suman: eso SÍ es lo que alguien edita, y quitar de allí una clase o un
    atributo es una decisión, no un olvido.
    """
    base = packaged()
    guardado = store.get() if store is not None else None
    if not guardado or int(guardado.get('version') or 0) <= int(base.get('version') or 0):
        return base
    cuerpo = dict(guardado['body'])
    suyos = {str(c.get('name')): c for c in (cuerpo.get('common') or ())}
    # En el orden del panel y con lo del guardado detrás: el que se publica es el que decide
    # cómo se leen, y lo que alguien añadió por su cuenta va después de lo que ya había.
    comunes = [suyos.get(str(c.get('name')), c) for c in (base.get('common') or ())]
    vistos = {str(c.get('name')) for c in comunes}
    comunes += [c for c in (cuerpo.get('common') or ()) if str(c.get('name')) not in vistos]
    cuerpo['common'] = comunes
    return cuerpo


def size_of(kind: str, doc: dict | None = None) -> dict:
    """Cómo se llama la casilla de tamaño de esa clase, y un ejemplo de cómo se escribe.

    ``{'label': 'capacity', 'hint': '1.92 TB'}``. La etiqueta se traduce con
    ``dcim_attr_<label>``; sin nada dicho, la palabra genérica.

    El ejemplo es la forma de pedir una unidad **sin partir el campo en dos**: en un número y una
    unidad aparte habría que decidir si 4 TB son 4·10¹² o 4·2⁴⁰ —las dos respuestas están en algún
    albarán— y convertir para enseñar lo que alguien ya escribió bien.
    """
    doc = doc if doc is not None else packaged()
    return dict((doc.get('size') or {}).get(str(kind or ''))
                or {'label': '', 'hint': '', 'units': []})


def fields(kind: str, doc: dict | None = None) -> list:
    """Los atributos de un componente de esa clase, con los comunes al final.

    Los comunes los últimos y no los primeros: lo primero que alguien quiere teclear de un disco
    es si es M.2 o de 2,5", no cuánto pesa.
    """
    doc = doc if doc is not None else packaged()
    return list((doc.get('kinds') or {}).get(str(kind or ''), [])) + list(doc.get('common') or [])


def common(doc: dict | None = None) -> list:
    """Lo que dice **todo** componente, sea de la clase que sea.

    Aparte de los atributos y no mezclado con ellos: un atributo es lo que distingue a una clase
    de otra, y algo que tienen todas no distingue nada. El peso de un DIMM va con su número de
    parte, no bajo un título que promete decir qué clase de disco es.
    """
    doc = doc if doc is not None else packaged()
    return list(doc.get('common') or [])


def compare(a: dict, b: dict) -> list:
    """Qué cambia entre dos versiones del documento, como una lista de renglones legibles.

    Por CLASE y por campo, y no como dos volcados de JSON uno al lado del otro: la pregunta que
    se hace mirando dos versiones es «¿qué se le añadió a los discos?», y a dos bloques de texto
    no se les puede preguntar eso.

    Cada renglón trae ``{where, name, before, after}``. *where* es la clase, o `common` o `size`.
    """
    a, b = normalise(a), normalise(b)
    fuera = []

    def _campos(doc, donde):
        origen = doc.get('common') if donde == 'common' else (doc.get('kinds') or {}).get(donde)
        return {c['name']: c for c in (origen or [])}

    sitios = ['common'] + sorted(set(a.get('kinds') or {}) | set(b.get('kinds') or {}))
    for donde in sitios:
        va, vb = _campos(a, donde), _campos(b, donde)
        for nombre in sorted(set(va) | set(vb)):
            uno, otro = va.get(nombre), vb.get(nombre)
            if _texto(uno) != _texto(otro):
                fuera.append({'where': donde, 'name': nombre,
                              'before': uno, 'after': otro})
    # Y el tamaño, que no es un campo sino cómo se llama y en qué se mide.
    for clase in sorted(set(a.get('size') or {}) | set(b.get('size') or {})):
        uno, otro = (a.get('size') or {}).get(clase), (b.get('size') or {}).get(clase)
        if _texto(uno) != _texto(otro):
            fuera.append({'where': 'size', 'name': clase, 'before': uno, 'after': otro})
    return fuera


def _texto(v) -> str:
    return '' if v is None else json.dumps(v, sort_keys=True, default=str)


class ProfileStore(BaseStore):
    """El documento que esta instalación haya guardado, si ha guardado alguno.

    **Un almacén, varios documentos.** La tabla lleva `name` desde el primer día justo para esto:
    los perfiles de componente y el catálogo de conectores son dos documentos que se actualizan
    igual —una versión más alta gana, se guarda quién y cuándo, y se puede volver al que viene
    con el panel— y una tabla por cada uno serían dos almacenes haciendo estas mismas cuatro
    cosas.

    Lo único que cambia es **cómo se limpia lo que entra**, porque un documento de conectores no
    tiene clases ni atributos. Por eso el limpiador se pasa: dado por hecho, el de los perfiles
    no dejaría nada de un documento de conectores y guardarlo diría «guardado» y guardaría un
    diccionario vacío. Un fallo que no da error.
    """

    _TABLE = SCHEMA.name
    _COLS = tuple(c.name for c in SCHEMA.columns)

    def __init__(self, db: BaseConnector, norm=None, scope: str = SCOPE) -> None:
        super().__init__(db)
        self._norm = norm or normalise
        self._scope = str(scope or SCOPE)
        self._db.reconcile_table(SCHEMA)
        # De este documento sale el formulario de TODOS los componentes, así que cambiarlo cambia
        # lo que todo el mundo puede teclear a partir de ese momento. Eso pide lo mismo que una
        # ficha del catálogo —quién, cuándo, y contra qué comparar— y lo pide sobre la tabla que
        # ya existe: `dc_rev` nació con un `scope` justo para la segunda cosa que lo necesitara.
        self.revs = RevisionStore(db)

    def get(self, name: str = NAME) -> dict | None:
        fila = self._db.fetchone(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE name = ?',
            (str(name or NAME),))
        if not fila:
            return None
        out = {c: fila[i] for i, c in enumerate(self._COLS)}
        try:
            out['body'] = self._norm(json.loads(out.get('body') or '{}'))
        except Exception:                       # pylint: disable=broad-except
            return None                         # una fila ilegible no es una versión más nueva
        out['version'] = int(out['body'].get('version') or 0)
        return out

    def save(self, doc: dict, *, name: str = NAME, actor: str = '') -> int:
        """Guardar un documento. Devuelve su versión, o ``0`` si no trae ninguna.

        Sin versión no se guarda: es lo único que decide cuál de los dos manda, y un documento
        sin ella sería uno que nunca se usa y que nadie entiende por qué no se usa.
        """
        limpio = self._norm(doc)
        if not limpio.get('version'):
            return 0
        blob = json.dumps(limpio, ensure_ascii=False, sort_keys=True)
        datos = (int(limpio['version']), blob, BaseStore._now(), str(actor or ''))
        if self.get(name):
            self._db.execute(
                f'UPDATE {self._sql_table} SET version = ?, body = ?, updated_at = ?, '
                'updated_by = ? WHERE name = ?', datos + (str(name),))
        else:
            self._db.execute(
                f'INSERT INTO {self._sql_table} ({", ".join(self._COLS)}) '
                f'VALUES ({", ".join("?" for _ in self._COLS)})', (str(name),) + datos)
        self._db.commit()
        self.revs.keep(name, limpio, action='save', actor=actor, scope=self._scope)
        return int(limpio['version'])

    def delete(self, name: str = NAME) -> bool:
        """Quitar el guardado y volver al que viene con el panel."""
        if not self.get(name):
            return False
        self._db.execute(f'DELETE FROM {self._sql_table} WHERE name = ?', (str(name or NAME),))
        self._db.commit()
        return True
