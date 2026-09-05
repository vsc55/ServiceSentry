#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Los adjuntos de una ficha: lo que no es una foto.

El manual, la hoja de características, el fichero de firmware, el PDF de la garantía. Hoy eso vive
en la carpeta de alguien —o en un correo de hace tres años— y el día que hace falta es un martes a
las once de la noche con una tarjeta que no arranca.

**No hay lista blanca de tipos, y eso es una decisión, no un olvido.** Lo útil aquí es abierto: un
PDF, un `.docx` que mandó el distribuidor, un `.zip` con el firmware, un `.txt` con la
configuración de fábrica. Una lista se quedaría corta cada semana y quien la sufre acabaría
renombrando ficheros para colarlos, que es peor que no tenerla.

Lo que hace que eso sea seguro es **cómo salen**: siempre como descarga, con el tipo genérico y
sin dejar que el navegador adivine (:mod:`lib.core.dcim.routes`). El panel no renderiza nunca un
fichero subido, así que un HTML o un SVG con guion dentro no se ejecuta en este origen — la misma
regla que ya se aplicaba a los SVG del almacén de imágenes, aquí llevada a todo.

Y como en las imágenes: **el nombre guardado lo acuña el panel**. Lo que el fichero se llamaba es
una etiqueta que se enseña, no una ruta — un nombre llegado por la red no toca este disco.
"""

from __future__ import annotations

import re

from lib.core.dcim import media
from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

#: De qué es este adjunto. Cerrado y corto: es para poder mirar «el manual» entre nueve ficheros,
#: no para clasificar. `other` es una respuesta.
#:
#: Lo que NO está es la factura o el albarán, y es la misma línea que separa las dos capas: un
#: modelo del catálogo es **genérico** —el manual del R740 vale para los veinte que hay— y una
#: factura es de UNA unidad, la que tiene número de serie. Eso cuelga del equipo del inventario,
#: que es donde se junta lo físico con el catálogo; y para eso está `scope`, que hoy solo vale
#: `type` porque todavía no se ha construido la otra mitad.
KINDS = ('manual', 'datasheet', 'firmware', 'warranty', 'other')

#: Lo que puede pesar uno. Más que una imagen —un manual de una cabina son treinta megas— y con
#: tope, porque sin él la carpeta de medios crece hasta donde alguien la arrastre.
MAX_BYTES = 32 * 1024 * 1024

#: Lo que se le quita al nombre que venía: separadores de ruta y caracteres de control. No para
#: poder usarlo —no se usa: el del disco lo acuña el panel— sino porque se enseña, y un nombre con
#: una barra dentro invita a leerlo como una ruta.
_SUCIO = re.compile(r'[\x00-\x1f\\/]+')

SCHEMA = TableSpec(
    name='dc_file',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        # De qué clase de cosa cuelga. Hoy solo `type` (un modelo del catálogo); la columna existe
        # porque lo siguiente que va a querer adjuntos es un equipo del inventario —su albarán,
        # su certificado de garantía— y una segunda tabla sería un segundo almacén igual.
        Column('scope',      'TEXT', nullable=False, default="'type'"),
        Column('ref_uid',    'TEXT', nullable=False),
        Column('kind',       'TEXT', nullable=False, default="'other'"),
        # Cómo se llamaba. Una ETIQUETA que se enseña, no una ruta: la del disco la acuña el
        # panel y va en `stored`.
        Column('label',      'TEXT', nullable=False, default="''"),
        Column('stored',     'TEXT', nullable=False, default="''"),
        Column('size',       'INTEGER', nullable=False, default='0'),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('created_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_dc_file_ref', ('scope', 'ref_uid')),),
)


def clean_label(name: str) -> str:
    """El nombre que venía, en condiciones de enseñarse. Vacío si no queda nada."""
    limpio = _SUCIO.sub('', str(name or '')).strip().strip('.')
    return limpio[:160]


class FileStore(BaseStore):
    """Los adjuntos, y de qué cuelga cada uno."""

    _TABLE = SCHEMA.name
    _COLS = tuple(c.name for c in SCHEMA.columns)

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(SCHEMA)

    def _row(self, row) -> dict:
        return {name: row[i] for i, name in enumerate(self._COLS)}

    def of(self, ref_uid: str, scope: str = 'type') -> list[dict]:
        """Los de una ficha, por clase y por nombre — que es como se buscan: «el manual»."""
        filas = [self._row(r) for r in (self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} '
            'WHERE scope = ? AND ref_uid = ?',
            (str(scope or 'type'), str(ref_uid or ''))) or ())]
        return sorted(filas, key=lambda f: (str(f.get('kind') or ''),
                                            str(f.get('label') or '').lower()))

    def get(self, uid: str) -> dict | None:
        filas = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE uid = ?',
            (str(uid or ''),)) or ()
        return self._row(filas[0]) if filas else None

    def add(self, ref_uid: str, stored: str, label: str, size: int, *, kind: str = 'other',
            actor: str = '', scope: str = 'type') -> str:
        """Apuntar uno recién guardado. ``''`` si no hay a qué colgarlo o no se guardó nada."""
        if not str(ref_uid or '') or not str(stored or ''):
            return ''
        uid = new_uid()
        self._db.execute(
            f'INSERT INTO {self._sql_table} ({", ".join(self._COLS)}) '
            f'VALUES ({", ".join("?" for _ in self._COLS)})',
            (uid, str(scope or 'type'), str(ref_uid),
             str(kind if kind in KINDS else 'other'),
             clean_label(label) or str(stored), str(stored), int(size or 0),
             BaseStore._now(), str(actor or '')))
        self._db.commit()
        return uid

    def copy(self, src_uid: str, dst_uid: str, var_dir: str = '', media_dir: str = '', *,
             actor: str = '', scope: str = 'type') -> int:
        """Llevar los adjuntos de una ficha a otra, **con sus ficheros duplicados**.

        Un clon que apuntara a los ficheros del original es una bomba de relojería: borrar
        cualquiera de los dos se lleva el fichero y el otro se queda sin manual sin que nada haya
        fallado. Es lo mismo que ya hacen las imágenes (`CatalogStore.copy_images`) y por la misma
        razón — contar cuántas fichas usan un fichero sería un mecanismo entero cuyo fallo se paga
        perdiendo el documento.

        El que no se pueda leer se salta: un clon sin uno de nueve manuales es mejor que un clon
        que no se crea.
        """
        n = 0
        for f in self.of(src_uid, scope):
            datos, err = media.read(var_dir, str(f.get('stored') or ''), media_dir, MAX_BYTES)
            if err or not datos:
                continue
            nuevo, err = media.keep(var_dir, datos, MAX_BYTES, media_dir)
            if err or not nuevo:
                continue
            if self.add(dst_uid, nuevo, str(f.get('label') or ''), len(datos),
                        kind=str(f.get('kind') or 'other'), actor=actor, scope=scope):
                n += 1
        return n

    def delete(self, uid: str) -> dict | None:
        """Quitar uno. Devuelve la fila que había, para que quien llame borre su fichero.

        Devuelta y no borrada aquí: este almacén sabe de filas y el de medios sabe de ficheros, y
        que uno alcanzara al otro sería que borrar una fila dependiera de tener a mano la carpeta.
        """
        fila = self.get(uid)
        if not fila:
            return None
        self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (str(uid),))
        self._db.commit()
        return fila

    def forget(self, ref_uid: str, scope: str = 'type') -> list[dict]:
        """Los de una ficha que se borra. Devuelve las filas, por lo mismo que :meth:`delete`.

        Sin esto, borrar un modelo dejaría sus manuales en el disco sin nada que apunte a ellos —
        el mismo agujero que se tapó al reimportar el catálogo.
        """
        filas = self.of(ref_uid, scope)
        for f in filas:
            self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (str(f['uid']),))
        if filas:
            self._db.commit()
        return filas
