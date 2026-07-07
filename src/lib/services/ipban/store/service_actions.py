#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``ip_service_action`` — the per-service block-action choice (fail2ban service
registry): one row per exposed service (``web``/``syslog``/…).

Written via the :class:`~lib.services.ipban.store.IpBanStore` facade; the live registry
(:class:`lib.services.ipban.exposed.IpBanServiceRegistry`) persists through
:meth:`set_service_action`.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_SVC = TableSpec(
    name='ip_service_action',
    columns=(
        Column('uid',     'TEXT', primary_key=True),   # stable row id
        Column('service', 'TEXT', nullable=False, default="''", unique=True),
        Column('action',  'TEXT', nullable=False, default="''"),
    ),
)

_TS = _SVC.name


class ServiceActionStore:
    """Per-service block-action choices (``ip_service_action``)."""

    def __init__(self, db: BaseConnector) -> None:
        self._db = db
        self._db.reconcile_table(_SVC)

    def service_actions(self) -> dict:
        """``{service_id: action}`` — the persisted per-service block-action choices."""
        try:
            rows = self._db.fetchall(f'SELECT service, action FROM {_TS}')
            return {r[0]: r[1] for r in rows if r[1]}
        except Exception:  # pylint: disable=broad-except
            return {}

    def set_service_action(self, service: str, action: str) -> None:
        """Upsert (or, on an empty action, delete) a service's block-action choice."""
        if not service:
            return
        try:
            with self._db.transaction():
                if not action:
                    self._db.execute(f'DELETE FROM {_TS} WHERE service = ?', (service,))
                    return
                row = self._db.fetchone(f'SELECT 1 FROM {_TS} WHERE service = ?', (service,))
                if row:
                    self._db.execute(f'UPDATE {_TS} SET action = ? WHERE service = ?',
                                     (action, service))
                else:
                    self._db.execute(
                        f'INSERT INTO {_TS} (uid, service, action) VALUES (?,?,?)',
                        (str(uuid.uuid4()), service, action))
        except Exception:  # pylint: disable=broad-except
            try:
                self._db.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
