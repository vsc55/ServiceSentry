#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small shared helpers for the API route handlers."""

from datetime import datetime, timezone

from flask import session

from ..constants import SYSTEM_USER


def touch_entity(entity: dict) -> None:
    """Stamp ``updated_at`` (UTC ISO-8601) and ``updated_by`` (current user) on
    *entity* in place — the audit-trail update applied on every entity edit.
    Single source for the create/update handlers (users, groups, roles).
    """
    entity['updated_at'] = datetime.now(timezone.utc).isoformat()
    entity['updated_by'] = session.get('username', SYSTEM_USER)


def track_change(changes: list, entity: dict, field: str, new_value,
                 *, old_default='') -> None:
    """Record an audit change and apply it: append ``{field, old, new}`` to
    *changes* when ``entity[field]`` differs from *new_value*, then store it.

    Standardises the compare/record/assign tail repeated across the update
    handlers.  Per-field validation, transformation and side effects stay at
    the call site; fields whose audit value is a derived/sorted form (roles,
    permissions, groups) keep their bespoke inline handling.
    """
    old_value = entity.get(field, old_default)
    if old_value != new_value:
        changes.append({'field': field, 'old': old_value, 'new': new_value})
    entity[field] = new_value
