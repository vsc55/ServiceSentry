#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entity edit/audit helpers — flask-free, foundational (``lib.util``).

The shared compare/record/stamp tail for the domain edit handlers (users,
groups, roles). The caller resolves the acting user (e.g. from the web session)
and passes it in, so these stay free of any web/request context and can live in
the base layer that ``lib.core`` imports without inverting the dependency.
"""

from datetime import datetime, timezone


def touch_entity(entity: dict, actor: str = 'system') -> None:
    """Stamp ``updated_at`` (UTC ISO-8601) and ``updated_by`` (*actor*) on
    *entity* in place — the audit-trail update applied on every entity edit.
    Single source for the create/update handlers (users, groups, roles).
    """
    entity['updated_at'] = datetime.now(timezone.utc).isoformat()
    entity['updated_by'] = actor


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
