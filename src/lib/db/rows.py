#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One table's worth of ordinary bookkeeping, for the tables that need nothing else.

:class:`lib.db.store_base.BaseStore` gives every store the plumbing — the connector, the
freshness stamp, "what time is it in the format this project writes". What it deliberately does
NOT give is CRUD, because most domains have real queries: joins, JSON payloads, a row that
becomes three dicts. Forcing those through one hierarchy costs more than the duplication.

But some tables have none of that. They differ in their columns and not at all in what is done
to them: list, get, create, update, delete. Written out per table that is one copy per table of
"how a row becomes a dict" — and the copy somebody forgets to update is the one that silently
drops a column.

This lived inside ``lib.core.dcim.store``, where it was written, and stayed there while it was
one domain's business. It stopped being that when companies moved to the core: a table of
companies is the same five methods over three columns, and a core package importing them out of
the inventory would be the core depending on a domain to know how to write a row.
"""

from __future__ import annotations

from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import TableSpec
from lib.db.store_base import BaseStore


def rank(cuenta: dict, limit: int = 0) -> list:
    """Los valores de ``{valor: cuántos}``, **del más usado al menos**.

    Del más usado primero porque es el orden en que se elige: el color que hay en cuarenta cables
    es el que va a llevar el cuarenta y uno. Alfabéticamente serían códigos hexadecimales
    ordenados por su primera letra, que no significa nada.

    Y con el valor como segundo criterio: dos colores empatados a tres cables tienen que salir
    siempre en el mismo orden, o la lista baila entre dos aperturas sin que nadie haya tocado
    nada — que es peor que un orden discutible.
    """
    fuera = sorted((cuenta or {}).items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [k for k, _ in (fuera[:limit] if limit else fuera)]


class Rows(BaseStore):
    """One table's worth of ordinary bookkeeping.

    Public rather than private because more than one package keeps its tables this way — the
    inventory's fourteen, the templates' two, the companies' two. A helper behind a leading
    underscore is a copy waiting to happen in the next package that needs it.
    """

    def __init__(self, db: BaseConnector, spec: TableSpec) -> None:
        super().__init__(db)
        self._spec = spec
        self._TABLE = spec.name
        self._cols = tuple(c.name for c in spec.columns)

    def bootstrap(self) -> None:
        self._db.reconcile_table(self._spec)

    def has(self, col: str) -> bool:
        """Si esta tabla lleva esta columna.

        Para que quien recorre el almacén DESCUBRA cuáles llevan número de inventario en vez de
        traer una lista escrita a mano. Una lista es algo que hay que acordarse de tocar el día
        que una tabla más lo lleve, y no acordarse no da ningún error: da un número repetido.
        """
        return str(col or '') in self._cols

    def counts(self, col: str) -> dict:
        """``{valor: cuántos}`` — lo que esa columna tiene puesto, sin los vacíos.

        En la BASE, agrupando: traerse la tabla entera para contar cinco valores distintos
        construye un diccionario por fila de toda la instalación y los tira todos menos cinco.

        Los NÚMEROS y no sólo los valores porque hay quien tiene que sumar los de dos tablas: un
        latiguillo rojo y un cable de corriente rojo son el mismo rojo, y dos listas ordenadas no
        se pueden mezclar sin volver a contar.
        """
        if not self.has(col):
            return {}
        sql = (f"SELECT {col}, COUNT(*) AS n FROM {self._sql_table} "
               f"WHERE {col} <> '' GROUP BY {col}")
        return {r[0]: int(r[1] or 0) for r in (self._db.fetchall(sql) or ()) if r and r[0]}

    def in_use(self, col: str, limit: int = 0) -> list:
        """Los valores que ya tiene esa columna, **del más usado al menos**.

        Para poder ofrecer lo que la casa ya usa en vez de una lista escrita a mano: los colores
        de latiguillo de una instalación son cinco, y elegirlos de una rueda de dieciséis
        millones la deja con nueve azules que no son el mismo azul.

        Del más usado primero porque es el orden en que se elige: el color que hay en cuarenta
        cables es el que va a llevar el cuarenta y uno. Alfabéticamente serían códigos
        hexadecimales ordenados por su primera letra, que no significa nada.

        En la BASE, agrupando: traerse la tabla entera para contar cinco valores distintos
        construye un diccionario por fila de toda la instalación y los tira todos menos cinco.
        """
        return rank(self.counts(col), limit)

    def _row(self, row) -> dict:
        return {name: row[i] for i, name in enumerate(self._cols)}

    def list(self, where: str = '', params: tuple = (),
             limit: int = 0, offset: int = 0) -> list[dict]:
        """Las filas que cumplan *where*, opcionalmente **de** *offset* y **hasta** *limit*.

        El tope es de la consulta y no del que llama: traer la tabla entera para quedarse con
        treinta filas construye un diccionario por fila de toda la instalación y luego lo tira.
        En una sala pequeña no se nota; es exactamente el trabajo que no se nota hasta que hay
        una sala grande, que es cuando ya está escrito en cuatro sitios.

        `ORDER BY uid` cuando se pagina, y sólo entonces: sin un orden, «las treinta siguientes»
        no significa nada —dos motores pueden devolver las mismas filas en distinto orden— y
        paginar sobre eso repite unas y se salta otras. Por `uid` y no por un campo con sentido
        porque es el único que existe en todas estas tablas y es único: un orden estable es lo
        que hace que la página dos sea la página dos.
        """
        sql = f'SELECT {", ".join(self._cols)} FROM {self._sql_table}'
        if where:
            sql += f' WHERE {where}'
        if limit or offset:
            sql += ' ORDER BY uid'
            sql += f' LIMIT {int(limit) if limit else -1} OFFSET {int(offset)}'
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
