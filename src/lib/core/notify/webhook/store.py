#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relational store for outgoing notification webhooks.

A *webhook* is one HTTP endpoint ServiceSentry POSTs to on status changes.  Each
is an independent record (url, method, headers, body template, signing secret),
so — like hosts/credentials/modules — they live in their **own** DB table, not in
``config.json``.  The ``secret`` field inside ``data`` is encrypted at rest with
:mod:`lib.security.secret_manager`; ``list``/``get`` return decrypted data so the
dispatcher can sign requests, and the API route masks it before sending out.

Schema::

    webhooks(uid PK, data(json {name, enabled, url, method, headers,
                                 body_template, timeout, secret, secret_header}),
             created_at, updated_at, updated_by)

The CRUD is :class:`~lib.core.notify.doc_store.JsonDocStore`: this file declares the
table and nothing else, because nothing else about it was ever webhook-specific.
"""

from __future__ import annotations

from lib.core.notify.doc_store import JsonDocStore
from lib.db import BaseConnector
from lib.db.schema import Column, TableSpec

_WEBHOOKS_SCHEMA = TableSpec(
    name='webhooks',
    columns=(
        Column('uid',        'TEXT', primary_key=True),
        Column('data',       'TEXT', nullable=False, default="'{}'"),
        Column('created_at', 'TEXT', nullable=False, default="''"),
        Column('updated_at', 'TEXT', nullable=False, default="''"),
        Column('updated_by', 'TEXT', nullable=False, default="''"),
    ),
)


class WebhooksStore(JsonDocStore):
    """Backend-agnostic store for notification webhooks (one row per webhook)."""

    SCHEMA = _WEBHOOKS_SCHEMA


def create(db: BaseConnector, **kw) -> WebhooksStore:
    """Factory mirroring the other stores' ``create(connector)`` helpers."""
    return WebhooksStore(db, **kw)
