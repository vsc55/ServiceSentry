#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a device saw, which is not the same kind of thing as what a check found.

A switch's forwarding table and a machine's ARP cache are the two things that say which
equipment is actually on the other end of a wire. They are also, on any real network, the two
that do not fit anywhere else this panel keeps data — and it is worth being precise about why,
because the temptation is to file them as ordinary readings and the cost of doing so is not
visible until somebody has a switch with four hundred entries on it.

* **They are many.** One row per MAC the switch has learned. A `check_state` row and a history
  series per MAC is thousands of rows for one device, most of them a laptop that connected
  once.
* **They are volatile.** Entries age out in minutes. As results they would be created and
  pruned every cycle, which is a table churning for no reader.
* **Nobody wants them as checks.** "The MAC aa:bb:cc is no longer on port 8" is not an alert,
  it is a person walking to a meeting room.
* **And they are only worth anything JOINED.** One device's ARP cache says little; the same
  cache cross-referenced with every interface MAC in the fleet says which machines can see
  each other, and a switch's forwarding table says which port each of them is on.

So: their own table, holding only the CURRENT picture, replaced wholesale per device and kind,
with no history behind it and nothing alerting on it. What reads it is the map.

WHO WRITES IT is the module, and what counts as evidence is the profile's word (``evidence``
on a metric): the core has no idea what a forwarding table is, and would be inventing a
vocabulary for the one device in front of whoever wrote it — the same rule as everywhere else
in this domain.
"""

from __future__ import annotations

import time

from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore

SCHEMA = TableSpec(
    name='net_evidence',
    columns=(
        Column('uid',   'TEXT', nullable=False),      # the device that SAW it
        Column('kind',  'TEXT', nullable=False),      # what kind of sighting ('fdb', 'arp'…)
        Column('key',   'TEXT', nullable=False),      # the thing seen (a MAC, an address)
        Column('value', 'TEXT'),                      # where it was seen (a port, a MAC)
        Column('ts',    'REAL', nullable=False, default='0'),
    ),
    # One row per (who saw it, what kind, what was seen). A device relearning the same MAC on
    # a different port is the same fact with a new answer, not a second fact.
    unique_constraints=(('uid', 'kind', 'key'),),
    indexes=(Index('idx_net_evidence_kind', ('kind', 'key')),),
)

_T = SCHEMA.name


class EvidenceStore(BaseStore):
    """The current sightings, per device and kind."""

    def __init__(self, db) -> None:
        super().__init__(db)
        self._qk = db.quote_ident('key')
        self._db.reconcile_table(SCHEMA)

    def replace(self, uid: str, kind: str, seen: dict) -> bool:
        """Make *seen* (``{key: value}``) the whole truth about *uid* and *kind*.

        Wholesale and not a merge, because the absence of an entry is information: a MAC that
        has aged out of a switch is a machine that is no longer on that port, and merging
        would leave the map drawing a cable that was unplugged last week.
        """
        uid, kind = str(uid or ''), str(kind or '')
        if not uid or not kind:
            return False
        now = time.time()
        rows = [(uid, kind, str(k), str(v if v is not None else ''), now)
                for k, v in (seen or {}).items() if str(k or '').strip()]
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_T} WHERE uid = ? AND kind = ?', (uid, kind))
                if rows:
                    self._db.executemany(
                        f'INSERT INTO {_T}(uid, kind, {self._qk}, value, ts) '
                        'VALUES(?, ?, ?, ?, ?)', rows)
            return True
        except Exception:                             # pylint: disable=broad-except
            return False                              # evidence is a nicety; a cycle is not

    def by_device(self, kind: str = '') -> dict:
        """``{uid: {key: value}}`` — everything currently seen, for the map to join."""
        out: dict = {}
        sql = f'SELECT uid, kind, {self._qk}, value FROM {_T}'
        args: tuple = ()
        if kind:
            sql += ' WHERE kind = ?'
            args = (str(kind),)
        try:
            for uid, _k, key, value in self._db.fetchall(sql, args) or ():
                out.setdefault(uid, {})[key] = value
        except Exception:                             # pylint: disable=broad-except
            return {}
        return out

    def forget(self, uid: str) -> bool:
        """Everything a device saw, dropped — for a machine leaving the registry."""
        try:
            self._db.execute(f'DELETE FROM {_T} WHERE uid = ?', (str(uid or ''),))
            self._db.commit()
            return True
        except Exception:                             # pylint: disable=broad-except
            return False

    def count(self) -> int:
        try:
            row = self._db.fetchone(f'SELECT COUNT(*) FROM {_T}')
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:                             # pylint: disable=broad-except
            return 0
