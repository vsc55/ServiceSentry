#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free overview helpers — layout normalization and widget permission gating,
extracted from :mod:`lib.core.overview.routes`.

Pure functions over plain dicts; no Flask.  The route owns request parsing, config/user
persistence and audit.
"""

from __future__ import annotations


def normalize_layout(widgets) -> list:
    """Coerce a posted dashboard layout to the canonical ``[{id, cols, h, hidden}]`` form,
    dropping entries that aren't dicts or lack an ``id``.  A non-list *widgets* yields ``[]``.
    Single source for the org-default and factory-reset endpoints."""
    return [
        {
            'id':     str(w.get('id', '')),
            'cols':   int(w.get('cols') or 2),
            'h':      w.get('h', 'auto'),
            'hidden': bool(w.get('hidden')),
        }
        for w in (widgets if isinstance(widgets, list) else [])
        if isinstance(w, dict) and w.get('id')
    ]


def widget_allowed(perms, desc: dict | None) -> bool:
    """True if *perms* satisfy a widget descriptor's permission gate — a widget with no gate
    is always allowed; otherwise the user needs one of ``perms.any`` or a permission starting
    with one of ``perms.prefix``."""
    p = (desc or {}).get('perms') or {}
    any_p, prefixes = p.get('any') or [], tuple(p.get('prefix') or [])
    if not (any_p or prefixes):
        return True
    return (any(x in perms for x in any_p)
            or bool(prefixes and any(str(x).startswith(prefixes) for x in perms)))
