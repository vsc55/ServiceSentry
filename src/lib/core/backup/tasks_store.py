#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for scheduled backup tasks.

A *task* is one standing instruction: **these parts, this often, keeping this many**. Several of
them is the whole point — configuration and inventory are worth a daily copy, the syslog and the
MIBs perhaps weekly, and with a single interval that cannot be said without copying everything at
the pace of the most demanding part, which is how a disk fills.

A table and not `config.json`, because a task is a RECORD, not a setting: it is created,
renamed, disabled and deleted one at a time, like a webhook or a host. `spec.py` holds scalars
an operator tunes; a list of things an operator keeps belongs where the other lists are.

Schema::

    backup_tasks(uid PK, data(json {name, enabled, every_hours, parts[], secrets, keep}),
                 created_at, updated_at, updated_by)

Nothing in ``data`` is encrypted: a task says WHAT to copy and how often, never a credential.
The copies it produces carry secrets or not, and that is a flag here, not a secret here.
"""

from __future__ import annotations

from lib.core.notify.doc_store import JsonDocStore
from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_TASKS_SCHEMA = TableSpec(
    name='backup_tasks',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
)

# What a task holds when the caller left a field out. `enabled` defaults to True for the same
# reason it does everywhere else in this panel: absent means "not said", not "off" — and a task
# somebody created and that silently never ran is the failure this whole feature exists against.
DEFAULTS: dict = {
    'name': '',
    'enabled': True,
    # How this task says WHEN. 'interval' survives the panel being down but drifts and cannot
    # say "Mondays at 03:00"; 'calendar' says exactly that — and keeps the catch-up, because it
    # asks "has the last window passed with no copy since" rather than "is it 03:00 now".
    'mode': 'interval',
    'every_hours': 24,
    'days': [],          # calendar only. Monday=0; EMPTY means every day, never "no days"
    'at': '03:00',       # calendar only
    'parts': ['core', 'config_file'],
    'secrets': True,
    'keep': 7,
}


class BackupTasksStore(JsonDocStore):
    """One row per scheduled task."""

    SCHEMA = _TASKS_SCHEMA

    def list_tasks(self) -> list:
        """Every task, with the missing fields filled in.

        Normalised HERE rather than at each reader: the scheduler, the API and the UI all ask
        the same questions of a task, and a default applied in two of the three is the kind of
        difference that shows up as "it ran weekly on the screen and daily on disk".
        """
        return [{**DEFAULTS, **(doc or {})} for doc in self.list()]

    def enabled_tasks(self) -> list:
        return [t for t in self.list_tasks() if t.get('enabled', True)]


def create(db: BaseConnector, **kw) -> BackupTasksStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return BackupTasksStore(db, **kw)
