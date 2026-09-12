#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backed leader lease for single-owner background services (HA failover).

Some services must NOT run on more than one instance at once: two monitoring
schedulers would double every check (and every alert); two event workers would
process the same cursor rows and double every notification.  But we still want
**hot standby** — extra replicas that take over within seconds if the active one
dies.

This store provides a per-service **lease**: each candidate periodically calls
:meth:`try_acquire`; exactly one becomes/stays the holder until its lease
``expires_at`` lapses (the holder renews it every heartbeat).  If the holder dies
and stops renewing, the lease expires and another replica acquires it — automatic
failover with no leader-election infra, just the shared DB.

The acquire is made race-safe by a *conditional* UPDATE
(``WHERE holder = <old> OR expires_at < now``): with two replicas contending for
an expired lease, only the first UPDATE matches; the second sees the holder
already changed and gets rowcount 0.

Active-active services (e.g. the syslog receiver behind a load balancer) simply
don't use this store.
"""

from __future__ import annotations

import time
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_SCHEMA = TableSpec(
    name='service_leader',
    columns=(
        Column('uid',                'TEXT', primary_key=True),   # stable row id
        # service_key stays the natural lookup key (unique) — the acquire relies on
        # its uniqueness to make a concurrent second INSERT fail.
        Column('service_key',        'TEXT', nullable=False, default="''", unique=True),
        Column('holder_instance_id', 'TEXT', nullable=False, default="''"),
        Column('holder_host',        'TEXT'),
        Column('acquired_at',        'REAL'),
        Column('renewed_at',         'REAL'),
        Column('expires_at',         'REAL'),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth


class ServiceLeaderStore:
    """Per-service leader lease with TTL-based failover."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Acquire / renew ─────────────────────────────────────────────────────────
    def try_acquire(self, service_key: str, instance_id: str, *,
                    host: str | None = None, ttl: float = 30.0) -> bool:
        """Become or stay the leader for *service_key*.  Returns True when this
        instance now holds the lease (freshly acquired or renewed)."""
        now = time.time()
        exp = now + max(1.0, ttl)
        try:
            with self._db.transaction():
                # Ensure a row exists (PK on service_key makes a concurrent second
                # INSERT fail; we ignore that and fall through to the read+update).
                row = self._db.fetchone(
                    f'SELECT holder_instance_id, expires_at FROM {_T} WHERE service_key=?',
                    (service_key,))
                if row is None:
                    try:
                        self._db.execute(
                            f'INSERT INTO {_T} (uid, service_key, holder_instance_id, '
                            'holder_host, acquired_at, renewed_at, expires_at) '
                            'VALUES (?,?,?,?,?,?,?)',
                            (str(uuid.uuid4()), service_key, instance_id, host, now, now, exp))
                        return True
                    except Exception:  # pylint: disable=broad-except
                        row = self._db.fetchone(
                            f'SELECT holder_instance_id, expires_at FROM {_T} '
                            'WHERE service_key=?', (service_key,))
                holder, expires = (row or ('', 0.0))
                if holder == instance_id:
                    self._db.execute(
                        f'UPDATE {_T} SET renewed_at=?, expires_at=?, holder_host=? '
                        'WHERE service_key=? AND holder_instance_id=?',
                        (now, exp, host, service_key, instance_id))
                    return True
                if not holder or expires is None or expires < now:
                    # Conditional claim: only succeeds if nobody else grabbed it first.
                    claimed = self._db.execute(
                        f'UPDATE {_T} SET holder_instance_id=?, holder_host=?, '
                        'acquired_at=?, renewed_at=?, expires_at=? '
                        'WHERE service_key=? AND (holder_instance_id=? OR expires_at < ?)',
                        (instance_id, host, now, now, exp, service_key, holder, now))
                    return bool(claimed)
                return False
        except Exception:  # pylint: disable=broad-except
            return False

    def release(self, service_key: str, instance_id: str) -> None:
        """Give up the lease if we hold it (clean shutdown → instant failover)."""
        try:
            self._db.execute(
                f'UPDATE {_T} SET holder_instance_id=\'\', expires_at=0 '
                'WHERE service_key=? AND holder_instance_id=?',
                (service_key, instance_id))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            pass

    # ── Read ────────────────────────────────────────────────────────────────────
    def current_leader(self, service_key: str) -> dict | None:
        """The current valid leader for *service_key*, or None when none holds a
        live lease."""
        row = self._db.fetchone(
            f'SELECT holder_instance_id, holder_host, expires_at FROM {_T} '
            'WHERE service_key=?', (service_key,))
        if not row:
            return None
        holder, host, expires = row
        if not holder or expires is None or expires < time.time():
            return None
        return {'instance_id': holder, 'host': host, 'expires_at': expires}

    def list_leaders(self) -> list[dict]:
        """Quién sostiene cada arriendo ahora mismo.

        ``renewed_at`` viaja con el resto porque es **cuándo dio su última vuelta** quien lo
        sostiene: el arriendo se renueva en cada pasada del trabajo que lo usa, así que es el
        único dato de «cuándo corrió esto» que se ve desde OTRO contenedor. El que lleva el
        propio hilo vive en su proceso y desde fuera no existe.
        """
        rows = self._db.fetchall(
            f'SELECT service_key, holder_instance_id, holder_host, expires_at, renewed_at '
            f'FROM {_T}')
        now = time.time()
        out = []
        for key, holder, host, expires, renewed in rows:
            if holder and expires and expires >= now:
                out.append({'service_key': key, 'instance_id': holder,
                            'host': host, 'expires_at': expires,
                            'renewed_at': float(renewed or 0)})
        return out


    def leases(self) -> list[dict]:
        """**Todos** los arriendos, vivos o no, con `live` diciendo cuál es cuál.

        Distinto de :meth:`list_leaders`, que descarta los caducados — y hace bien, porque lo
        que pregunta es «¿quién manda ahora?». Aquí la pregunta es otra: «¿quién dio la última
        vuelta y cuándo?», y para un trabajo lento la respuesta vive casi siempre en una fila
        caducada.

        Un escaneo de certificados corre cada 24 h y su arriendo dura una hora: está expirado el
        **96 %** del tiempo. Filtrarlo deja la pantalla diciendo «todavía no ha corrido nunca»
        sobre algo que corrió esta mañana, que es peor que no decir nada.
        """
        rows = self._db.fetchall(
            f'SELECT service_key, holder_instance_id, holder_host, expires_at, renewed_at, '
            f'acquired_at FROM {_T}')
        now = time.time()
        return [{'service_key': key, 'instance_id': holder or '', 'host': host or '',
                 'expires_at': float(expires or 0), 'renewed_at': float(renewed or 0),
                 'acquired_at': float(acquired or 0),
                 'live': bool(holder and expires and expires >= now)}
                for key, holder, host, expires, renewed, acquired in rows]


def create(db: BaseConnector) -> ServiceLeaderStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return ServiceLeaderStore(db)
