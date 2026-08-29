#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las versiones de una ficha del catálogo: qué decía antes, y quién la cambió.

Un modelo del catálogo es un dato **compartido**. De él cuelgan las plantillas, las piezas
estampadas en veinte máquinas y la altura con la que se dibuja un alzado, así que corregirlo no
es editar una fila: es cambiar lo que otros ya usaban. Y la corrección que rompe algo casi nunca
se descubre el día que se hace — se descubre semanas después, cuando alguien dice «esto antes
ponía otra cosa» y no hay forma de saber si tiene razón.

**Se guarda el estado DESPUÉS de cada cambio**, no el de antes. Así la última versión es lo que
hay ahora y una lista se lee sola: cada renglón trae lo que ese cambio hizo —la diferencia con el
renglón anterior— y volver a una versión es escribir sus valores, sin restar nada. Guardando el
estado previo haría falta traer la fila actual desde fuera para poder leer el último cambio, que
es un dato de más viajando para calcular algo que la tabla ya podría contestar sola.

**Y se poda.** Un catálogo con ocho mil modelos y sin tope es una tabla que crece durante toda la
vida de la instalación por una función que casi nadie mira. Se guardan las últimas
:data:`KEEP` de cada ficha, que es más de lo que nadie va a recorrer y muchísimo menos que todas.

El *scope* existe porque esto no es solo del catálogo: una plantilla quiere lo mismo —de ella
salieron veinte máquinas y es el estándar con el que se compra— y el documento de perfiles
también. Una tabla por cada una serían tres almacenes haciendo estas mismas cuatro cosas. Es la
misma forma que ``dc_owner``, y por la misma razón.
"""

from __future__ import annotations

import json

from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

#: Cuántas versiones se guardan de cada ficha. Sin tope, esta tabla crece para siempre; con una
#: sola, la pregunta que se le hace —«qué ponía antes»— solo se puede contestar una vez.
KEEP = 30

#: Lo que NO se compara al decir qué cambió. Son campos que se escriben solos y no son una
#: decisión de nadie: enseñarlos convertiría cada renglón del historial en una lista de tres cosas
#: que cambian siempre y una que importa.
#:
#: `kind_set` está aquí porque es la CONSECUENCIA de corregir la clase, no un cambio aparte:
#: saldría siempre junto a `kind` diciendo lo mismo con otras palabras.
#:
#: `parts` es de las plantillas y está aquí porque **no es un campo**: es la lista de lo que
#: lleva puesto, y compararla como texto pondría dos volcados de doce componentes uno al lado
#: del otro para decir que se añadió un disco. Se guarda en la versión —«¿de qué constaba?» es
#: casi siempre la pregunta— pero lo que ese cambio hizo lo dice la acción, que para eso está.
SKIP = ('uid', 'imported_at', 'match_key', 'brand_uid', 'kind_set',
        'updated_at', 'updated_by', 'rev', 'parts')

SCHEMA = TableSpec(
    name='dc_rev',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        # De qué clase de cosa es esta versión. Hoy solo `type` (un modelo del catálogo).
        Column('scope',    'TEXT', nullable=False, default="'type'"),
        Column('ref_uid',  'TEXT', nullable=False),
        Column('at',       'TEXT', nullable=False, default="''"),
        # El ORDEN, que no lo puede dar la fecha: este proyecto guarda segundos, y dos cambios
        # del mismo segundo se ordenarían al azar — que es como una versión aparece antes que la
        # que la produjo y la diferencia sale del revés. Un contador por ficha lo resuelve y no
        # depende del reloj de nadie.
        Column('seq',      'INTEGER', nullable=False, default='0'),
        Column('by',       'TEXT', nullable=False, default="''"),
        # Qué se hizo: `create`, `edit`, `image`, `image_drop`, `restore`. Aparte de la
        # diferencia, porque poner una imagen no cambia ningún campo que se pueda comparar y sin
        # esto sería un renglón vacío.
        Column('action',   'TEXT', nullable=False, default="'edit'"),
        # La ficha entera **como quedó**, en JSON. Entera y no solo lo que cambió: volver atrás
        # es escribir esto, y una diferencia no se puede escribir sin la fila que la precede —
        # que es justo la que puede haberse podado.
        Column('data',     'TEXT', nullable=False, default="'{}'"),
    ),
    indexes=(Index('idx_dc_rev_ref', ('scope', 'ref_uid', 'seq')),),
)


def diff(antes: dict, despues: dict) -> dict:
    """Qué cambió entre dos estados: ``{campo: [antes, después]}``.

    Comparado como texto a propósito: `1` y `'1'` son el mismo número escrito por dos caminos —
    uno viene de la base de datos y otro de un formulario— y decir que cambió sería llenar el
    historial de cambios que nadie hizo.
    """
    fuera = {}
    for campo in sorted(set(antes or {}) | set(despues or {})):
        if campo in SKIP:
            continue
        a, b = (antes or {}).get(campo), (despues or {}).get(campo)
        if _texto(a) == _texto(b):
            continue
        # Una columna de JSON se abre por dentro. Sin esto, cambiar la interfaz de un disco sale
        # como dos volcados de `extra` uno al lado del otro y hay que compararlos a ojo — que es
        # exactamente lo que este historial existe para no tener que hacer.
        if isinstance(a, dict) or isinstance(b, dict):
            a, b = a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}
            for clave in sorted(set(a) | set(b)):
                if _texto(a.get(clave)) != _texto(b.get(clave)):
                    fuera[f'{campo}.{clave}'] = [a.get(clave), b.get(clave)]
            continue
        fuera[campo] = [a, b]
    return fuera


def _texto(v) -> str:
    if v is None:
        return ''
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    return str(v)


class RevisionStore(BaseStore):
    """Lo que decía una ficha antes de cada cambio, y quién lo hizo."""

    _TABLE = SCHEMA.name
    _COLS = tuple(c.name for c in SCHEMA.columns)

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(SCHEMA)

    def _row(self, row) -> dict:
        out = {name: row[i] for i, name in enumerate(self._COLS)}
        try:
            out['data'] = json.loads(out.get('data') or '{}')
        except Exception:                       # pylint: disable=broad-except
            out['data'] = {}
        return out

    def keep(self, ref_uid: str, data: dict, *, action: str = 'edit', actor: str = '',
             scope: str = 'type') -> str:
        """Apuntar cómo quedó la ficha. Devuelve el uid de la versión, o ``''`` si no hay a qué.

        Se llama **después** de escribir, siempre por el mismo sitio: una versión que dependa de
        que cada ruta se acuerde de guardarla es una versión que falta justo en el cambio que
        alguien va a querer mirar.
        """
        if not str(ref_uid or ''):
            return ''
        uid = new_uid()
        fila = self._db.fetchone(
            f'SELECT MAX(seq) FROM {self._sql_table} WHERE scope = ? AND ref_uid = ?',
            (str(scope or 'type'), str(ref_uid)))
        seq = int((fila or (0,))[0] or 0) + 1
        self._db.execute(
            f'INSERT INTO {self._sql_table} ({", ".join(self._COLS)}) '
            f'VALUES ({", ".join("?" for _ in self._COLS)})',
            (uid, str(scope or 'type'), str(ref_uid), BaseStore._now(), seq,
             str(actor or ''), str(action or 'edit'),
             json.dumps(data or {}, sort_keys=True, default=str)))
        self._db.commit()
        self._prune(scope, ref_uid)
        return uid

    def _prune(self, scope: str, ref_uid: str) -> int:
        """Dejar solo las últimas :data:`KEEP`. Sin esto la tabla crece para siempre."""
        filas = self._db.fetchall(
            f'SELECT uid FROM {self._sql_table} WHERE scope = ? AND ref_uid = ? '
            'ORDER BY seq DESC', (str(scope or 'type'), str(ref_uid))) or ()
        sobran = [str(r[0]) for r in filas[KEEP:]]
        for uid in sobran:
            self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (uid,))
        if sobran:
            self._db.commit()
        return len(sobran)

    def history(self, ref_uid: str, scope: str = 'type') -> list[dict]:
        """Las versiones de una ficha, de la más nueva a la más vieja, con lo que cada una hizo.

        La diferencia se calcula **aquí** y no se guarda: guardarla sería el mismo dato dos
        veces, y el día que alguien cambie qué campos se comparan las viejas seguirían diciendo
        lo de antes.
        """
        filas = [self._row(r) for r in (self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} '
            'WHERE scope = ? AND ref_uid = ? ORDER BY seq DESC',
            (str(scope or 'type'), str(ref_uid or ''))) or ())]
        for i, fila in enumerate(filas):
            anterior = filas[i + 1]['data'] if i + 1 < len(filas) else {}
            fila['changes'] = diff(anterior, fila['data']) if anterior else {}
        return filas

    def get(self, uid: str, scope: str = 'type') -> dict | None:
        filas = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} '
            'WHERE uid = ? AND scope = ?', (str(uid or ''), str(scope or 'type'))) or ()
        return self._row(filas[0]) if filas else None

    def forget(self, ref_uid: str, scope: str = 'type') -> int:
        """Olvidar el historial de una ficha que se ha borrado. Las versiones de algo que ya no
        existe no contestan a nada y se quedarían para siempre."""
        filas = self._db.fetchall(
            f'SELECT uid FROM {self._sql_table} WHERE scope = ? AND ref_uid = ?',
            (str(scope or 'type'), str(ref_uid or ''))) or ()
        for (uid,) in filas:
            self._db.execute(f'DELETE FROM {self._sql_table} WHERE uid = ?', (str(uid),))
        if filas:
            self._db.commit()
        return len(filas)
