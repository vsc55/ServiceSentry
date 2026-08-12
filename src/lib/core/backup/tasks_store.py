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
    # Retention as BUCKETS, not a counter: seven copies can be one week at daily resolution or
    # two years at monthly, and only the second survives finding out in March that something
    # broke in January. A copy is kept if ANY rule claims it, so "7 daily + 4 weekly + 6
    # monthly" costs 17 copies rather than 180. All of them zero means keep everything.
    # The uid of a shared retention profile, empty meaning "my own numbers, below". A pointer
    # and not a copy: editing "GFS estándar" has to change every task that follows it, which is
    # the only reason to have profiles rather than a button that fills the boxes in. The task's
    # own numbers stay stored underneath — they are what it goes back to when it is unlinked,
    # and what stands if the profile is ever removed.
    'profile': '',
    'keep_last': 3,        # the newest N, whatever the calendar says
    'keep_daily': 7,
    'keep_weekly': 4,
    'keep_monthly': 6,
    'keep_yearly': 0,
    # A ceiling in BYTES for this task's copies, 0 = none. The buckets say what is worth
    # keeping; this says what there is room for, and it can only ever take away what the
    # buckets already chose.
    'max_size': 0,
    # What retention was before the buckets. Read as `keep_last` when no bucket is set, so a
    # task written by an older build goes on behaving exactly as it did without being rewritten.
    'keep': 0,
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
        return [self._with_defaults(doc) for doc in self.list()]

    @staticmethod
    def _with_defaults(doc) -> dict:
        """One stored task, filled in — and read as what it MEANT when it was written.

        The catch the defaults create on their own: a task written before retention had buckets
        holds only `keep`, and merging today's defaults underneath would hand it four buckets it
        never asked for. So a task that names no bucket is read as the counter it was, and one
        that names any is read as written. Not migrated on disk: a task that was working must
        not need rewriting to go on working, and a migration is a thing that can go wrong once
        for every install.
        """
        doc = doc or {}
        out = {**DEFAULTS, **doc}
        from lib.core.backup.schedule import RETENTION_KEYS  # noqa: PLC0415
        buckets = [k for k in RETENTION_KEYS if k != 'max_size']
        if not any(k in doc for k in buckets):
            try:
                legacy = int(doc.get('keep') or 0)
            except (TypeError, ValueError):
                legacy = 0
            if legacy > 0:
                out.update({k: 0 for k in buckets})
                out['keep_last'] = legacy
        return out

    def enabled_tasks(self) -> list:
        return [t for t in self.list_tasks() if t.get('enabled', True)]


def create(db: BaseConnector, **kw) -> BackupTasksStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return BackupTasksStore(db, **kw)
