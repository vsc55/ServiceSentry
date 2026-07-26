#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-instance permission keys, and what to do when their resource disappears.

A role may narrow a global flag down to one instance — ``server.<uid>.edit``,
``module.<name>.view``, ``cluster.<uid>.delete``.  Those keys name a resource that lives
in a different table (or, for modules, in the module configuration), and nothing tied the
two together: deleting a host left its keys in every role's permission list for good.

They granted nothing — a UUID is never reused, so the key referred to something that could
not come back — but they piled up unseen, and the Permissions section counts them, so a
role would report more scoped grants than it really has.

Module keys are the exception worth stating: a module NAME can come back, so a stale
``module.ping.edit`` would silently apply to whatever is called ``ping`` next.  That is
the direction that matters, which is why removing a module purges its keys too rather
than keeping them "just in case it returns".

Flask-free on purpose: the web glue that persists and audits is in :mod:`.mixin`.
"""

from __future__ import annotations

from typing import Iterable

#: Prefixes of the per-instance keys, i.e. the resources whose permissions can be scoped.
SCOPED_PREFIXES = ('module', 'server', 'cluster')


def scoped_keys(prefix: str, rid: str) -> set:
    """Every key that scopes *prefix* to *rid* — all four actions."""
    return {f'{prefix}.{rid}.{action}' for action in ('view', 'add', 'edit', 'delete')}


def strip_scoped(custom_roles: dict, prefix: str, ids: Iterable[str]) -> list:
    """Drop the keys of the given resources from every custom role, in place.

    Returns the UIDs of the roles that actually changed, so the caller can decide whether
    persisting (and auditing) is worth it.  Built-in roles are never touched: their
    permissions come from code and hold no per-instance keys at all.
    """
    dead = set()
    for rid in ids:
        if rid:
            dead |= scoped_keys(prefix, str(rid))
    if not dead:
        return []
    changed = []
    for uid, role in custom_roles.items():
        perms = role.get('permissions') or []
        kept = [p for p in perms if p not in dead]
        if len(kept) != len(perms):
            role['permissions'] = kept
            changed.append(uid)
    return changed


def cluster_item_uids(modules_cfg: dict) -> set:
    """The UIDs of every cluster item in a module configuration.

    A cluster is a multi-host-bound check — an item carrying a ``host_uids`` list — and it
    is identified by its item UID, which is what ``cluster.<uid>.<action>`` names.
    """
    out = set()
    for _mod, cfg in (modules_cfg or {}).items():
        if not isinstance(cfg, dict):
            continue
        for coll, items in cfg.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for key, item in items.items():
                if isinstance(item, dict) and isinstance(item.get('host_uids'), list):
                    out.add(str(item.get('uid') or key))
    return out
