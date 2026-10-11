#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``plan2d_kind`` — the objects somebody created from a plan's screen.

The base objects and each screen's own are code (:mod:`lib.core.plan2d.kinds`); these are the
ones a screen's users add —a pallet, a vending machine, a badge printer— and they belong to
that screen (``screen``) only. Their ``kind_key`` is what the things placed on the plan carry,
so it is minted here (``u-`` and ten letters) and never changes: renaming an object must not
orphan the forty already placed.
"""

from __future__ import annotations

import secrets
import string

from lib.core.plan2d.kinds import CUSTOM_DEFAULTS, CUSTOM_PREFIX
from lib.core.uids import new_uid
from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

SCHEMA = TableSpec(
    name='plan2d_kind',
    columns=(
        Column('uid',      'TEXT', primary_key=True),
        # The screen it belongs to (`register_screen`): `dcim` today.
        Column('screen',   'TEXT', nullable=False, default="''"),
        # What the placed things carry. `u-` and ten letters, minted here and never changed.
        Column('kind_key', 'TEXT', nullable=False, default="''"),
        Column('name',     'TEXT', nullable=False, default="''"),
        Column('icon',     'TEXT', nullable=False, default="'bi-square'"),
        # 1 = equipment: it can be linked to a monitored device and a cable traced to it.
        Column('device',   'INTEGER', nullable=False, default='0'),
        Column('mount',    'TEXT', nullable=False, default="'floor'"),
        # Its usual size and height off the floor, in millimetres.
        Column('w_mm',     'INTEGER', nullable=False, default='600'),
        Column('d_mm',     'INTEGER', nullable=False, default='600'),
        Column('h_mm',     'INTEGER', nullable=False, default='1000'),
        Column('base_mm',  'INTEGER', nullable=False, default='0'),
        Column('layer',    'TEXT', nullable=False, default="'room'"),
        Column('front',    'INTEGER', nullable=False, default='0'),
        # How it is drawn: fill and line colours (#rrggbb), the dash of its outline, the letters.
        Column('fill',     'TEXT', nullable=False, default="'#94a3b8'"),
        Column('line',     'TEXT', nullable=False, default="''"),
        Column('dash',     'TEXT', nullable=False, default="''"),
        Column('abbr',     'TEXT', nullable=False, default="''"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_plan2d_kind_screen', ('screen',)),
             Index('idx_plan2d_kind_key', ('screen', 'kind_key'), unique=True)),
)

_LETTERS = string.ascii_lowercase + string.digits
#: What a request may write: the fields of an object, never its screen or its key.
_FIELDS = tuple(CUSTOM_DEFAULTS)


def new_key() -> str:
    return CUSTOM_PREFIX + ''.join(secrets.choice(_LETTERS) for _ in range(10))


class PlanKindStore(BaseStore):
    """The objects created from each screen."""

    _TABLE = SCHEMA.name
    _COLS = tuple(c.name for c in SCHEMA.columns)

    def __init__(self, db: BaseConnector) -> None:
        super().__init__(db)
        self._db.reconcile_table(SCHEMA)

    def _row(self, row) -> dict:
        out = {name: row[i] for i, name in enumerate(self._COLS)}
        out['key'] = out['kind_key']
        return out

    def of_screen(self, screen: str) -> list[dict]:
        """A screen's objects, in the order they were created."""
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE screen = ? '
            'ORDER BY created_at, uid', (str(screen or ''),)) or ()
        return [self._row(r) for r in rows]

    def get(self, uid: str) -> dict | None:
        rows = self._db.fetchall(
            f'SELECT {", ".join(self._COLS)} FROM {self._sql_table} WHERE uid = ?',
            (str(uid or ''),)) or ()
        return self._row(rows[0]) if rows else None

    def create(self, screen: str, row: dict, *, actor: str = '') -> dict:
        """A new object of *screen*, already cleaned and judged. Returns ``{uid, key}``."""
        ahora = BaseStore._now()
        valores = {k: row[k] for k in _FIELDS if k in row}
        valores.update({'uid': new_uid(), 'screen': str(screen), 'kind_key': new_key(),
                        'created_at': ahora, 'updated_at': ahora, 'updated_by': str(actor or '')})
        cols = [c for c in self._COLS if c in valores]
        self._db.execute(
            f'INSERT INTO {self._sql_table} ({", ".join(cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})',
            tuple(valores[c] for c in cols))
        self._db.commit()
        return {'uid': valores['uid'], 'key': valores['kind_key']}

    def update(self, uid: str, row: dict, *, actor: str = '') -> bool:
        if not self.get(uid):
            return False
        datos = {k: row[k] for k in _FIELDS if k in row}
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
