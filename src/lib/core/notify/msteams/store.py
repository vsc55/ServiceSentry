#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for Microsoft Teams *channel* destinations (Incoming Webhooks).

Each record is one Teams channel ServiceSentry posts an Adaptive Card to on a
status change.  Like webhooks/hosts/credentials, they live in their **own** DB
table, not in ``config.json``.  The ``webhook_url`` field inside ``data`` embeds a
secret token, so it is encrypted at rest with :mod:`lib.security.secret_manager`;
``list``/``get`` return decrypted data so the dispatcher can post, and the API
route masks it before sending out.

Schema::

    msteams_channels(uid PK, data(json {name, enabled, webhook_url}),
                     created_at, updated_at, updated_by)

The CRUD is :class:`~lib.core.notify.doc_store.JsonDocStore`: this file declares the
table and nothing else, because nothing else about it was ever Teams-specific.
"""

from __future__ import annotations

from lib.core.notify.doc_store import JsonDocStore
from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_MSTEAMS_SCHEMA = TableSpec(
    name='msteams_channels',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
)


class MsTeamsStore(JsonDocStore):
    """Backend-agnostic store for Teams channel destinations (one row per channel)."""

    SCHEMA = _MSTEAMS_SCHEMA


def create(db: BaseConnector, **kw) -> MsTeamsStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return MsTeamsStore(db, **kw)
