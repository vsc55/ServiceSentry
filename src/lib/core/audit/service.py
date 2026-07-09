#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free audit helpers extracted from :mod:`lib.core.audit.routes`.

The audit domain is a thin query/CRUD passthrough to :class:`~lib.core.audit.store.
AuditStore`, so this module holds only the one bit of route logic that isn't a store call:
looking an entry up by id before deleting it (to capture its fields for the audit trail).
Pure; no Flask.
"""

from __future__ import annotations


def find_entry(entries: list, entry_id: int) -> dict | None:
    """The audit entry whose ``_id`` matches *entry_id* (``None`` if absent)."""
    return next((e for e in entries if e.get('_id') == entry_id), None)
