#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-contributed Overview widgets — generic catalog (core, no module code).

A watchful module may declare an Overview dashboard widget in its ``schema.json``::

    "__overview_widget__": {"icon": "bi-diagram-3", "multi": true,
                            "perm": "modules_view", "cols": 4, "h": 340}

The widget's **title** is the module's translated ``pretty_name``; its **data** is
produced by the module's ``Watchful.overview_widget(items, status, lang)`` hook
(generic shape: ``{entries: [...], aggregate: {...}}``).  The core renders it
generically — nothing module-specific lives in the core.

``multi`` (default False) lets the same widget be added several times (e.g. one
per standalone cluster); the core gives each instance its own scope selector.
"""

from __future__ import annotations

import json
import os

# Reuse the credential-catalog helpers (watchfuls dir resolution + lang loader).
from lib.credential_schemas import _watchfuls_dir, _module_i18n


def overview_widgets_catalog(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: {icon, multi, perm, cols, h, label_i18n}}`` for every
    module declaring ``__overview_widget__``.  The label is the module's
    translated ``pretty_name`` (so the title carries no core string)."""
    out: dict = {}
    base = _watchfuls_dir(watchfuls_dir)
    if not os.path.isdir(base):
        return out
    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        sp = os.path.join(base, entry, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, encoding='utf-8') as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        decl = schema.get('__overview_widget__')
        if not isinstance(decl, dict):
            continue
        lang_data = _module_i18n(os.path.join(base, entry))
        label_i18n = {lang: data.get('pretty_name')
                      for lang, data in lang_data.items()
                      if isinstance(data, dict) and isinstance(data.get('pretty_name'), str)}
        out[entry] = {
            'module':     entry,
            'icon':       str(decl.get('icon') or 'bi-grid-1x2'),
            'multi':      bool(decl.get('multi')),
            'perm':       str(decl.get('perm') or 'modules_view'),
            'cols':       int(decl.get('cols') or 4),
            'h':          decl.get('h') or 340,
            'label_i18n': label_i18n or {'en_EN': entry},
        }
    return out
