#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las plataformas: con qué sale un equipo, escrito una vez.

Una plantilla decía «Debian 12» en una caja de texto. Veinte plantillas dicen «Debian 12»,
«debian 12», «Debian GNU/Linux 12» y «deb12», y entonces «cuántas máquinas hay que actualizar»
no tiene respuesta: hay cuatro respuestas parciales y ninguna la sabe nadie entero.

Así que es una tabla, con la misma regla que las marcas: **el slug es la identidad y el nombre
es lo que se lee**. Renombrar «Debian 12» a «Debian 12 (bookworm)» es editar una fila, no
buscar y reemplazar en veinte plantillas — y las que ya apuntaban a ella siguen apuntando.

**Y no es solo de un dispositivo físico.** Una máquina virtual corre RouterOS igual que lo corre
un router de metal, y lo que se pregunta de las dos es lo mismo: qué versión, hasta cuándo tiene
parches, quién la mantiene. Por eso la plataforma vive aquí y no dentro de la plantilla: quien
apunte a ella después —un equipo del inventario, una máquina virtual— apunta a la misma fila.

El fabricante es **opcional y es una marca de verdad** (`dc_brand`): RouterOS es de MikroTik y
Windows Server de Microsoft, pero Debian no es de nadie que aparezca en una factura, y obligar a
inventarse un fabricante para poder escribir «Debian» es inventarse un dato.
"""

from __future__ import annotations

import json

from lib.core.dcim.brands import slug_of
from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

#: Qué clase de cosa corre esto. No es una etiqueta suelta: separa lo que se instala en una
#: máquina de lo que ES la máquina, y decide qué plataformas ofrecerle a quien está creando una
#: máquina virtual y no un router.
KINDS = ('os', 'firmware', 'hypervisor', 'appliance', 'other')

SCHEMA = TableSpec(
    name='dc_platform',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        # Lo que se lee. Cambia; por eso no es la identidad.
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        # Lo que ES: el nombre normalizado. Es lo que impide que «Debian 12» y «debian  12»
        # acaben siendo dos plataformas que nadie puede juntar después.
        Column('slug',        'TEXT', nullable=False, default="''"),
        # De quién es, cuando es de alguien. Opcional a propósito: Debian no es de nadie que
        # salga en una factura, y obligar a rellenarlo sería obligar a inventárselo.
        Column('brand_uid',   'TEXT', nullable=False, default="''"),
        Column('kind',        'TEXT', nullable=False, default="'os'"),
        # La versión, aparte del nombre. «Debian» y «12» separados es lo que permite preguntar
        # «cuántas Debian hay» y «cuántas van por la 12» sin partir cadenas.
        Column('version',     'TEXT', nullable=False, default="''"),
        # De qué familia es, para poder leerlas en árbol: `Windows 11` agrupa a Pro, Home y
        # Enterprise. Una columna y no dos —familia y edición—: la hoja se calcula quitándole
        # el prefijo al nombre, y guardarla sería guardar dos veces lo mismo con la posibilidad
        # de que discrepen. Vacía es una plataforma que no agrupa con ninguna, que también pasa.
        Column('family',      'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        # Las fechas de su vida, en JSON y no en columnas: son las MISMAS SEIS que las de un
        # modelo del catálogo —fin de venta, fin de mantenimiento, fin de parches de seguridad,
        # última alta de soporte, última renovación, fin de soporte— y la lista sale del grupo
        # `lifecycle` del documento de perfiles. Con columnas, añadir la séptima sería una
        # migración; así es editar un JSON, que es para lo que ese documento existe.
        Column('extra',       'TEXT', nullable=False, default="'{}'"),
        Column('url',         'TEXT', nullable=False, default="''"),
        Column('notes',       'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_platform_slug', ('slug',), unique=True),),
)


class PlatformStore(BaseStore):
    """Las plataformas, y lo único que hay que saber de ellas: cuál es cuál."""

    _TABLE = SCHEMA.name
    _COLS = tuple(c.name for c in SCHEMA.columns)

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(SCHEMA)

    def _row(self, row) -> dict:
        fuera = {name: row[i] for i, name in enumerate(self._COLS)}
        # La columna guarda texto; quien la lea espera un diccionario. Deserializar aquí y no en
        # cada pantalla es lo que evita que una de ellas se olvide.
        try:
            fuera['extra'] = json.loads(fuera.get('extra') or '{}') or {}
        except (TypeError, ValueError):
            fuera['extra'] = {}
        return fuera

    def list(self) -> list[dict]:
        """Todas, por nombre.

        `LOWER` dicho en el SQL por lo mismo que en las marcas: son tres motores con tres
        criterios por defecto, y `pfSense` detrás de la Z es exactamente el fallo que eso da.
        """
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} '
            'ORDER BY LOWER(name), LOWER(version)') or ()
        return [self._row(r) for r in rows]

    def get(self, uid: str) -> dict | None:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE uid = ?',
            (str(uid or ''),)) or ()
        return self._row(rows[0]) if rows else None

    def find(self, name: str) -> dict | None:
        """La que se llama así, por su nombre normalizado. `None` si no está.

        Existe para poder preguntar ANTES de crear: el sembrado de básicos escribe la ficha
        entera al dar una de alta y solo rellena huecos en una que ya estaba, y esas son dos
        cosas distintas que hay que poder distinguir.
        """
        return self.by_slug(slug_of(' '.join(str(name or '').split())))

    def by_slug(self, slug: str) -> dict | None:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE slug = ?',
            (str(slug or ''),)) or ()
        return self._row(rows[0]) if rows else None

    def ensure(self, name: str, *, actor: str = '') -> str:
        """El uid de la que se llama así, creándola si no está. `''` si no hay nombre.

        Existe para lo que llega escrito: una plantilla que traía «Debian 12» en una caja de
        texto tiene que poder seguir diciendo lo mismo sin que nadie dé de alta nada primero.
        """
        nombre = ' '.join(str(name or '').split())
        clave = slug_of(nombre)
        if not clave:
            return ''
        ya = self.by_slug(clave)
        if ya:
            return str(ya['uid'])
        return self._insert({'name': nombre, 'slug': clave}, actor=actor)

    def create(self, row: dict, *, actor: str = '') -> str:
        """Una escrita a mano. `''` si no tiene nombre o ya hay otra que se llama igual."""
        datos = self._fields(row)
        if not datos.get('name') or self.by_slug(datos['slug']):
            return ''
        return self._insert(datos, actor=actor)

    def _insert(self, datos: dict, *, actor: str = '') -> str:
        valores = dict(datos)
        valores.setdefault('kind', 'os')
        valores.update({'uid': new_uid(), 'created_at': BaseStore._now(),
                        'updated_at': BaseStore._now(), 'updated_by': str(actor or '')})
        cols = [c for c in self._COLS if c in valores]
        self._db.execute(
            f'INSERT INTO {self._sql_table} ({", ".join(cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})',
            tuple(valores[c] for c in cols))
        self._db.commit()
        return str(valores['uid'])

    def update(self, uid: str, row: dict, *, actor: str = '') -> bool:
        datos = self._fields(row, parcial=True)
        if not self.get(uid):
            return False
        if 'name' in datos:
            if not datos['name']:
                return False
            otra = self.by_slug(datos['slug'])
            if otra and str(otra['uid']) != str(uid):
                return False
        if not datos:
            return True
        datos['updated_at'] = BaseStore._now()
        datos['updated_by'] = str(actor or '')
        cols = list(datos)
        self._db.execute(
            f'UPDATE {self._sql_table} SET {", ".join(f"{c} = ?" for c in cols)} WHERE uid = ?',
            tuple(datos[c] for c in cols) + (str(uid),))
        self._db.commit()
        return True

    def delete(self, uid: str) -> bool:
        if not self.get(uid):
            return False
        self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (str(uid),))
        self._db.commit()
        return True

    @staticmethod
    def _fields(row: dict, parcial: bool = False) -> dict:
        """Lo que una petición puede decir de una plataforma.

        El `slug` no llega de fuera: se deriva del nombre siempre. Dejarlo llegar sería dejar
        que dos plataformas se hicieran pasar por la misma.
        """
        data = row or {}
        fuera = {}
        if 'name' in data or not parcial:
            fuera['name'] = ' '.join(str(data.get('name') or '').split())
            fuera['slug'] = slug_of(fuera['name'])
        if 'kind' in data or not parcial:
            clase = str(data.get('kind') or '').strip()
            # Contra la lista y no como llegue: una clase inventada es un filtro que nunca
            # devuelve nada y una fila que no sale en ninguna pantalla.
            fuera['kind'] = clase if clase in KINDS else 'os'
        for campo in ('brand_uid', 'version', 'family', 'description', 'url', 'notes'):
            if campo in data or not parcial:
                fuera[campo] = str(data.get(campo) or '').strip()
        # Serializado aquí, por lo mismo que se deserializa al leer: un sitio y no tres.
        if 'extra' in data or not parcial:
            extra = data.get('extra')
            fuera['extra'] = json.dumps(extra if isinstance(extra, dict) else {},
                                        sort_keys=True)
        return fuera
