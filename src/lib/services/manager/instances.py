#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DB-backed registry of running background-service instances (the heartbeat).

Each long-running service (monitoring / syslog / events) — whether it runs
**embedded** in the web admin or **standalone** in its own process/container —
upserts one row here every few seconds.  It is the *observed state* half of the
distributed control plane: the web admin reads this table to show the real state
of every instance (alive / stale / down), even the ones living in another pod,
and to discover each instance's ``control_url`` for the optional HTTP poke.

This is deliberately separate from the *desired state* (the ``config`` table,
e.g. ``monitoring|enabled``): config says what the operator wants, this table
says what is actually running.  The store is value-agnostic — it stores and
returns exactly what it is given.

Backed by a pluggable :class:`lib.db.BaseConnector` (the shared system DB), so a
``--monitor`` worker and the web admin write/read the same rows.
"""

from __future__ import annotations

import json
import time
import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec

_SCHEMA = TableSpec(
    name='service_instances',
    columns=(
        Column('uid',           'TEXT', primary_key=True),          # synthetic row id
        Column('instance_id',   'TEXT', nullable=False, default="''", unique=True),  # stable per process run
        Column('service_key',   'TEXT', nullable=False, default="''"),  # monitoring/syslog/events
        Column('mode',          'TEXT', nullable=False, default="''"),  # embedded / standalone
        Column('host',          'TEXT'),                             # pod / hostname
        Column('pid',           'INTEGER'),
        Column('version',       'TEXT'),                             # code version (drift detection)
        Column('control_url',   'TEXT'),                             # http://addr:port for the poke
        Column('running',       'INTEGER', nullable=False, default='0'),
        Column('started_at',    'REAL'),
        Column('last_seen',     'REAL'),
        Column('last_cycle_at', 'REAL'),                            # last check cycle / activity
        Column('detail',        'TEXT', nullable=False, default="''"),  # JSON extras (interval, ports…)
        # What the process RUNS ON — interpreter, OS, its packages. Written once (see
        # `set_env`) because none of it can change without a restart, and a restart is a new
        # row. Its own column and not part of `detail`: `detail` is rewritten on every beat.
        Column('env',           'TEXT', nullable=False, default="''"),  # JSON fingerprint
    ),
    indexes=(
        Index('idx_svcinst_key',      ('service_key',)),
        Index('idx_svcinst_lastseen', ('last_seen',)),
    ),
)

_T = _SCHEMA.name  # table name — single source of truth


def _loads(text):
    try:
        return json.loads(text) if text not in (None, '') else {}
    except (ValueError, TypeError):
        return {}


class ServiceInstancesStore:
    """Backend-agnostic registry of live service instances (heartbeat rows)."""

    _COLS = ('instance_id', 'service_key', 'mode', 'host', 'pid', 'version',
             'control_url', 'running', 'started_at', 'last_seen', 'last_cycle_at',
             'detail', 'env')

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._bootstrap()

    # ── Schema ──────────────────────────────────────────────────────────────────
    def _bootstrap(self) -> None:
        self._db.reconcile_table(_SCHEMA)

    # ── Write ───────────────────────────────────────────────────────────────────
    def heartbeat(
        self,
        instance_id: str,
        service_key: str,
        *,
        mode: str,
        running: bool,
        host: str | None = None,
        pid: int | None = None,
        version: str | None = None,
        control_url: str | None = None,
        last_cycle_at: float | None = None,
        started_at: float | None = None,
        detail: dict | None = None,
    ) -> None:
        """Upsert this instance's heartbeat row, refreshing ``last_seen`` to now.

        ``started_at`` is set only on the first insert (kept stable across beats).
        Best-effort: a write failure never propagates into the service loop."""
        now = time.time()
        dj = json.dumps(detail or {}, ensure_ascii=False)
        try:
            with self._db.transaction():
                exists = self._db.fetchone(
                    f'SELECT started_at FROM {_T} WHERE instance_id = ?', (instance_id,))
                if exists is not None:
                    self._db.execute(
                        f'UPDATE {_T} SET service_key=?, mode=?, host=?, pid=?, version=?, '
                        'control_url=?, running=?, last_seen=?, last_cycle_at=?, detail=? '
                        'WHERE instance_id=?',
                        (service_key, mode, host, pid, version, control_url,
                         1 if running else 0, now, last_cycle_at, dj, instance_id))
                else:
                    self._db.execute(
                        f'INSERT INTO {_T} (uid, instance_id, service_key, mode, host, pid, '
                        'version, control_url, running, started_at, last_seen, last_cycle_at, '
                        'detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (str(uuid.uuid4()), instance_id, service_key, mode, host, pid, version,
                         control_url, 1 if running else 0, started_at or now, now,
                         last_cycle_at, dj))
        except Exception:  # pylint: disable=broad-except
            pass

    def set_env(self, instance_id: str, env: dict | None) -> None:
        """Record what this instance runs on — once, at startup.

        Kept out of :meth:`heartbeat` on purpose. That row is rewritten every few seconds by
        every instance, and this is a few kilobytes that cannot change while the process
        lives: beating it would be the same bytes over the same wire forever, on the one
        table a multi-container install writes to most.
        """
        if not env:
            return
        try:
            self._db.execute(
                f'UPDATE {_T} SET env=? WHERE instance_id=?',
                (json.dumps(env, ensure_ascii=False), instance_id))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            pass          # best-effort, exactly like the beat it travels beside

    def mark_down(self, instance_id: str) -> None:
        """Mark an instance as cleanly stopped (running=0), keeping the row so the
        UI shows it as stopped rather than abruptly vanishing."""
        try:
            self._db.execute(
                f'UPDATE {_T} SET running=0, last_seen=? WHERE instance_id=?',
                (time.time(), instance_id))
            self._db.commit()
        except Exception:  # pylint: disable=broad-except
            pass

    def prune(self, older_than_secs: float = 86400) -> int:
        """Drop rows not seen for *older_than_secs* (dead instances that never
        marked themselves down — crashed pods, killed containers)."""
        try:
            cutoff = time.time() - max(0, older_than_secs)
            deleted = self._db.execute(
                f'DELETE FROM {_T} WHERE last_seen IS NOT NULL AND last_seen < ?', (cutoff,))
            self._db.commit()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    def clear_others(self, service_key: str, mode: str, host: str,
                     keep_instance_id: str) -> int:
        """Remove rows for the SAME (service, mode, host) but a different instance —
        i.e. previous runs of this very process (a restart gets a new PID → a new
        instance_id).  Called at startup so a restarted embedded/standalone service
        leaves exactly one live row instead of accumulating restart 'zombies'.
        (Distinct pods have distinct hostnames, so this never touches real replicas.)"""
        try:
            deleted = self._db.execute(
                f'DELETE FROM {_T} WHERE service_key=? AND mode=? AND host=? '
                'AND instance_id<>?',
                (service_key, mode, host, keep_instance_id))
            self._db.commit()
            return deleted
        except Exception:  # pylint: disable=broad-except
            return 0

    # ── Read ────────────────────────────────────────────────────────────────────
    def _row_to_dict(self, row: tuple) -> dict:
        d = dict(zip(self._COLS, row))
        d['running'] = bool(d.get('running'))
        d['detail'] = _loads(d.get('detail'))
        d['env'] = _loads(d.get('env'))
        return d

    def list_instances(self) -> list[dict]:
        """Every known instance row (most recently seen first)."""
        cols = ', '.join(self._COLS)
        rows = self._db.fetchall(
            f'SELECT {cols} FROM {_T} ORDER BY last_seen DESC')
        return [self._row_to_dict(r) for r in rows]

    def list_for(self, service_key: str) -> list[dict]:
        """Instances of a given service (most recently seen first)."""
        cols = ', '.join(self._COLS)
        rows = self._db.fetchall(
            f'SELECT {cols} FROM {_T} WHERE service_key = ? ORDER BY last_seen DESC',
            (service_key,))
        return [self._row_to_dict(r) for r in rows]


def create(db: BaseConnector) -> ServiceInstancesStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return ServiceInstancesStore(db)
