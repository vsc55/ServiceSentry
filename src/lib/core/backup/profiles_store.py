#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for retention profiles — a named policy several tasks can share.

The buckets are what make retention worth configuring and also what make it long: five numbers
and a ceiling, in every task, retyped from memory each time a task is created. Three tasks with
"the same" policy were three chances to type 6 where the others say 4, and nothing on screen
would ever have said they disagreed.

A profile is that policy given a name and one home. A task points at it, so editing "GFS
estándar" changes every task that uses it at once — which is the whole reason to have profiles
rather than a button that fills the boxes in.

Schema::

    backup_profiles(uid PK, data(json {name, keep_last, keep_daily, keep_weekly,
                                       keep_monthly, keep_yearly, max_size}),
                    created_at, updated_at, updated_by)

A task may still carry its own numbers instead — see `tasks_store.DEFAULTS['profile']`. A
profile is an offer to stop repeating yourself, not a place everything has to go through.
"""

from __future__ import annotations

from lib.core.notify.doc_store import JsonDocStore
from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_PROFILES_SCHEMA = TableSpec(
    name='backup_profiles',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
)

# The same fields a task carries, because a profile IS a task's retention with a name on it.
# Kept in step by `RETENTION_KEYS`, which is what both read.
DEFAULTS: dict = {
    'name': '',
    'keep_last': 3,
    'keep_daily': 7,
    'keep_weekly': 4,
    'keep_monthly': 6,
    'keep_yearly': 0,
    'max_size': 0,
}


# Starting points, offered by the editor when somebody creates a profile. Here and not in the
# browser: they are the panel's opinion about how much history is worth keeping, and an opinion
# written in a template is one the API cannot state — the same reason the part catalogue travels
# with the list rather than being a second list in JavaScript.
#
# Offered, never applied on their own: a profile exists because somebody made it, so an install
# with no profiles has none, rather than three nobody asked for cluttering the select.
SUGGESTED: tuple = (
    # A week of dailies and nothing older. The honest default for an install whose config
    # changes daily and whose history is not worth a year of disk.
    {'key': 'backup_suggest_short',
     'keep_last': 3, 'keep_daily': 7, 'keep_weekly': 0, 'keep_monthly': 0, 'keep_yearly': 0},
    # The shape borg and restic settled on: daily detail near, monthly reach far. ~17 copies.
    {'key': 'backup_suggest_gfs',
     'keep_last': 3, 'keep_daily': 7, 'keep_weekly': 4, 'keep_monthly': 6, 'keep_yearly': 0},
    # Years, for the install where "when did this setting change?" is asked about last spring.
    {'key': 'backup_suggest_long',
     'keep_last': 3, 'keep_daily': 7, 'keep_weekly': 4, 'keep_monthly': 12, 'keep_yearly': 3},
)


class BackupProfilesStore(JsonDocStore):
    """One row per retention profile."""

    SCHEMA = _PROFILES_SCHEMA

    def list_profiles(self) -> list:
        """Every profile, with the missing fields filled in.

        Normalised here for the same reason tasks are: the scheduler, the API and the form all
        ask a profile the same questions, and a default applied in two of the three is how a
        policy prunes differently from what the screen says it does.
        """
        return [{**DEFAULTS, **(doc or {})} for doc in self.list()]


def create(db: BaseConnector, **kw) -> BackupProfilesStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return BackupProfilesStore(db, **kw)
