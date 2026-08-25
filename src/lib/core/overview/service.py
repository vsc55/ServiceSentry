#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask-free overview helpers — layout normalization and widget permission gating,
extracted from :mod:`lib.core.overview.routes`.

Pure functions over plain dicts; no Flask.  The route owns request parsing, config/user
persistence and audit.
"""

from __future__ import annotations


#: Per-instance settings a module widget carries besides its geometry: which check kind or
#: device it shows (``mws``), the minimum severity it lists (``mwlvl``), whether it draws the
#: usage ring (``mwchart``), and — for a chart widget — which measurement (``mwfig``) over how
#: many hours (``mwh``). They are part of what makes a widget THAT widget: two instances of the
#: same type differ only by these, which is the whole reason somebody puts two on a dashboard.
#:
#: A layout that dropped them would save the arrangement and lose the configuration, and an
#: admin publishing a default would hand everyone the right boxes showing the wrong things.
#: This list is the SERVER's half; the browser's is `_DW_INSTANCE_KEYS` in
#: `partials/overview/_layout.html`, and a key added to one and not the other is a setting
#: that survives a reload and vanishes on the next machine, with nothing said.
INSTANCE_KEYS = ('mws', 'mwlvl', 'mwchart', 'mwfig', 'mwh')


def normalize_layout(widgets) -> list:
    """Coerce a posted dashboard layout to the canonical ``[{id, cols, h, hidden}]`` form
    plus any :data:`INSTANCE_KEYS` present, dropping entries that aren't dicts or lack an
    ``id``.  A non-list *widgets* yields ``[]``.  Single source for the org-default and
    factory-reset endpoints."""
    out = []
    for w in (widgets if isinstance(widgets, list) else []):
        if not (isinstance(w, dict) and w.get('id')):
            continue
        item = {
            'id':     str(w.get('id', '')),
            'cols':   int(w.get('cols') or 2),
            'h':      w.get('h', 'auto'),
            'hidden': bool(w.get('hidden')),
        }
        for k in INSTANCE_KEYS:
            if w.get(k):
                item[k] = str(w[k])
        out.append(item)
    return out


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
