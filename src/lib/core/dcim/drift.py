#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``dc_drift`` — what the panel has already said about a cable, so it does not say it again.

The panel can tell that somebody moved a patch cord: :func:`lib.core.dcim.service.cable_check`
compares what is declared against what the devices themselves report over LLDP, and marks a
cable ``other_port`` when the ports they name are not the ones written down. That has existed
for a while. What did not exist is anyone **saying so** — it only appeared if a person opened
the cabling tab and pressed Check.

A scanner that notices every thirty minutes and tells you every thirty minutes is worse than
one that never tells you: the channel is silenced within two days and the one alert that
mattered goes with it. So each finding is announced **once**, and again only if it *changes*.

Why a table rather than a dict in the scanner
---------------------------------------------
Because this runs in containers. A deployment has several web replicas, the lease picks one of
them to scan, and that one is not the same process tomorrow — a rolling deploy, a restarted pod,
a node drained. An in-memory "already told you" dies with the process, and the next leader
announces the whole backlog again as if it were new. `event_cooldowns` exists for exactly this
reason and says so in its own docstring; this is the same problem with a different subject.

The row is also what re-arms the alert. A finding whose key stops appearing is deleted, so a
cable that is put back and moved again **is** announced again — which is the difference between
remembering and going quiet.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

#: `drift_key` y no `key`: `key` es palabra reservada en MySQL, y este proyecto ya pagó esa
#: lección esta misma semana —`dc_rev.by` dejó el historial de versiones sin funcionar fuera de
#: SQLite—. Entrecomillarla habría valido; no usarla vale más.
SCHEMA = TableSpec(
    name='dc_drift',
    columns=(
        Column('uid',         'TEXT', primary_key=True),
        # Qué hallazgo es. `moved:<uid del cable>` o `undeclared:<device>|<device>` ordenado, porque
        # estar enchufados es simétrico y quién es «el primero» no es un hecho del cable.
        Column('drift_key',   'TEXT', nullable=False, default="''", unique=True),
        Column('kind',        'TEXT', nullable=False, default="''"),
        # Lo que se vio, resumido. Es lo que distingue «esto sigue igual» de «esto ha cambiado
        # otra vez»: mover el mismo latiguillo a una tercera boca es un hallazgo nuevo, y con
        # sólo la clave sería el mismo de antes y se callaría.
        Column('fingerprint', 'TEXT', nullable=False, default="''"),
        Column('first_seen',  'REAL', nullable=False, default='0'),
        Column('notified_at', 'REAL', nullable=False, default='0'),
        # Cuántas veces se ha dicho ESTE hallazgo. Es lo que hace posible «repítelo tres veces
        # y luego cállate»: sin el contador, un límite sólo se puede aplicar dentro de un
        # proceso, y aquí el proceso cambia.
        Column('times',       'INTEGER', nullable=False, default='0'),
    ),
)

_T = SCHEMA.name


class DriftStore:
    """Lo que ya se avisó del cableado, para no repetirlo."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(SCHEMA)

    def known(self) -> dict:
        """``{drift_key: {'kind', 'fingerprint', 'first_seen', 'notified_at'}}``."""
        try:
            filas = self._db.fetchall(
                f'SELECT drift_key, kind, fingerprint, first_seen, notified_at, times '
                f'FROM {_T}') or ()
        except Exception:  # pylint: disable=broad-except
            return {}
        return {str(r[0]): {'kind': str(r[1] or ''), 'fingerprint': str(r[2] or ''),
                            'first_seen': float(r[3] or 0), 'notified_at': float(r[4] or 0),
                            'times': int(r[5] or 0)}
                for r in filas}

    def remember(self, drift_key: str, kind: str, fingerprint: str, now: float,
                 *, first_seen: float = 0.0, times: int = 1) -> None:
        """Apuntar que esto ya se dijo. UPDATE y luego INSERT, que es el patrón portable."""
        try:
            tocadas = self._db.execute(
                f'UPDATE {_T} SET kind = ?, fingerprint = ?, notified_at = ?, times = ? '
                'WHERE drift_key = ?',
                (str(kind), str(fingerprint), float(now), int(times), str(drift_key)))
            if not tocadas:
                self._db.execute(
                    f'INSERT INTO {_T}(uid, drift_key, kind, fingerprint, first_seen, '
                    'notified_at, times) VALUES(?, ?, ?, ?, ?, ?, ?)',
                    (str(uuid.uuid4()), str(drift_key), str(kind), str(fingerprint),
                     float(first_seen or now), float(now), int(times)))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            pass

    def forget(self, drift_keys) -> int:
        """Olvidar los hallazgos que ya no se ven — es lo que vuelve a armar el aviso.

        Un cable que se arregla y se vuelve a mover tiene que volver a avisar. Sin esto, el
        primer aviso sería también el último.
        """
        claves = [str(k) for k in (drift_keys or ())]
        if not claves:
            return 0
        try:
            marcas = ','.join('?' * len(claves))
            n = self._db.execute(
                f'DELETE FROM {_T} WHERE drift_key IN ({marcas})', tuple(claves))
            self._db.commit()
            return int(n or 0)
        except Exception:  # pylint: disable=broad-except
            return 0

    def clear(self) -> int:
        try:
            n = self._db.execute(f'DELETE FROM {_T}')
            self._db.commit()
            return int(n or 0)
        except Exception:  # pylint: disable=broad-except
            return 0
