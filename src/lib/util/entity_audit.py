#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entity edit/audit helpers — flask-free, foundational (``lib.util``).

The shared compare/record/stamp tail for the domain edit handlers (users,
groups, roles). The caller resolves the acting user (e.g. from the web session)
and passes it in, so these stay free of any web/request context and can live in
the base layer that ``lib.core`` imports without inverting the dependency.
"""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """The one timestamp format this project stores: UTC, second resolution, ``…Z``.

    One function because there used to be two spellings — this module produced
    ``2026-07-26T10:00:00.123456+00:00`` and the stores ``2026-07-26T10:00:00Z`` — and for
    the same second the first sorts BELOW the second. Any code ordering or comparing the
    stored string (the freshness probe did) stopped being ordered by time exactly when two
    different writers touched the same table.
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def touch_entity(entity: dict, actor: str = 'system') -> None:
    """Stamp ``updated_at`` (UTC ISO-8601) and ``updated_by`` (*actor*) on
    *entity* in place — the audit-trail update applied on every entity edit.
    Single source for the create/update handlers (users, groups, roles).
    """
    entity['updated_at'] = utc_now_iso()
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
