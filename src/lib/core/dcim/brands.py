#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las marcas: la raíz de la jerarquía del catálogo.

Hasta ahora un fabricante era **una cadena de texto repetida ocho mil quinientas veces**. Eso
alcanza para agrupar una rejilla y no alcanza para nada más: no hay dónde apuntar la web de
soporte, ni el número de cliente, ni por qué esta casa compra a esos y no a otros; renombrar
«HP» a «Hewlett Packard Enterprise» son ocho mil quinientos `UPDATE`; y dos formas de escribir el
mismo nombre son dos fabricantes que nadie puede juntar.

Así que es una tabla, y el orden queda como es de verdad:

    fabricante → modelo del catálogo (`dc_type`) → plantilla (`dc_build`) → equipo (`dc_item`)

**`slug` es la identidad, no el nombre.** El nombre es lo que se lee y cambia; el slug es el
nombre normalizado —minúsculas, sin puntuación— y es lo que hace que la biblioteca, al reimportar,
vuelva a encontrar al mismo fabricante en vez de crear otro. Es la misma regla que casa un modelo
con lo que un dispositivo dice de sí mismo (:func:`lib.core.dcim.catalog.key`), y por el mismo
motivo: las formas de escribir un nombre propio se cuentan por docenas.

**Se crean solos al importar.** Nadie va a teclear trescientos fabricantes antes de traerse la
biblioteca — y si hubiera que hacerlo, no se haría. Lo que se teclea es lo que el catálogo no
puede saber: dónde se abre un ticket, con qué número de cliente, y qué hay que recordar de ellos.
"""

from __future__ import annotations

import re

from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

_WORD = re.compile(r'[^a-z0-9]+')

SCHEMA = TableSpec(
    name='dc_brand',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        # Lo que se lee. Cambia —una compra, un cambio de marca— y por eso no es la identidad.
        Column('name',        'TEXT', nullable=False, default="''", unique=True),
        # Lo que ES. El nombre normalizado: es lo que hace que reimportar la biblioteca vuelva a
        # encontrar al mismo fabricante en vez de crear otro con la puntuación cambiada.
        Column('slug',        'TEXT', nullable=False, default="''"),
        Column('description', 'TEXT', nullable=False, default="''"),
        # La web del fabricante, y **dónde se abre un ticket o se baja un firmware**, que no es
        # la misma y es la que hace falta a las tres de la mañana. Ninguna biblioteca las trae:
        # son de esta casa, y son justo lo que no cabía en una columna de texto repetida.
        Column('url',         'TEXT', nullable=False, default="''"),
        Column('support_url', 'TEXT', nullable=False, default="''"),
        # El número de cliente o de contrato con ellos. Lo primero que piden por teléfono.
        Column('account',     'TEXT', nullable=False, default="''"),
        Column('created_at',  'TEXT', nullable=False, default="''"),
        Column('updated_at',  'TEXT', nullable=False, default="''"),
        Column('updated_by',  'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_brand_slug', ('slug',), unique=True),),
)


def slug_of(name: str) -> str:
    """El nombre normalizado, que es por lo que se reconoce a un fabricante.

    `HP`, `H.P.` y `hp` son el mismo, y la biblioteca los escribe de las tres formas según quién
    subiera el fichero. Sin esto, reimportar crea un fabricante nuevo cada vez que alguien pone
    un punto donde no lo había.
    """
    return _WORD.sub('', str(name or '').lower())


class BrandStore(BaseStore):
    """Las marcas, con lo que esta casa sabe de ellas."""

    _TABLE = SCHEMA.name
    _COLS = tuple(c.name for c in SCHEMA.columns)

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(SCHEMA)

    def _row(self, row) -> dict:
        return {name: row[i] for i, name in enumerate(self._COLS)}

    def list(self) -> list[dict]:
        """Todos, por nombre.

        `LOWER` dicho en el SQL: son tres motores con tres criterios por defecto —MySQL no
        distingue mayúsculas, SQLite sí, PostgreSQL depende del idioma del sistema— y `i-PRO`
        detrás de la Z es exactamente el fallo que eso produce.
        """
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} '
            'ORDER BY LOWER(name)') or ()
        return [self._row(r) for r in rows]

    def get(self, uid: str) -> dict | None:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE uid = ?',
            (str(uid or ''),)) or ()
        return self._row(rows[0]) if rows else None

    def by_slug(self, slug: str) -> dict | None:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE slug = ?',
            (str(slug or ''),)) or ()
        return self._row(rows[0]) if rows else None

    def ensure(self, name: str, *, actor: str = '') -> str:
        """El uid del fabricante que se llama así, creándolo si no está. `''` si no hay nombre.

        Por **slug** y no por nombre: al reimportar la biblioteca vuelven los mismos trescientos,
        y buscarlos por el texto exacto crearía uno nuevo cada vez que alguien cambia un punto de
        sitio. Y sin tocar lo que ya hubiera: la web de soporte que alguien escribió es de esta
        casa, y una importación no tiene por qué saber nada de ella.
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
        """Uno escrito a mano. `''` si no tiene nombre o ya hay otro que se llama igual."""
        datos = self._fields(row)
        if not datos.get('name') or self.by_slug(datos['slug']):
            return ''
        return self._insert(datos, actor=actor)

    def _insert(self, datos: dict, *, actor: str = '') -> str:
        valores = dict(datos)
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
            otro = self.by_slug(datos['slug'])
            if otro and str(otro['uid']) != str(uid):
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
        """Lo que una petición puede decir de un fabricante.

        Campo a campo: `uid`, `created_at` y el `slug` **no** se escriben desde fuera. El slug se
        deriva del nombre siempre — dejar que llegue en la petición sería dejar que dos
        fabricantes se hicieran pasar por el mismo.
        """
        data = row or {}
        fuera = {}
        if 'name' in data or not parcial:
            fuera['name'] = ' '.join(str(data.get('name') or '').split())
            fuera['slug'] = slug_of(fuera['name'])
        for campo in ('description', 'url', 'support_url', 'account'):
            if campo in data or not parcial:
                fuera[campo] = str(data.get(campo) or '').strip()
        return fuera
