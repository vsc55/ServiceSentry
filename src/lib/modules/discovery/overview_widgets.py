#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-contributed Overview widgets — generic catalog (core, no module code).

A watchful module may declare one Overview dashboard widget (a dict) — or several
(a list) — in its ``schema.json``.  Everything module-specific (icon, which check
to show, click-through URL, …) is supplied by the module's own schema/hooks; the
core only reads these generic keys and never hard-codes any module::

    "__overview_widget__": [
        {"id": "<id>", "view": "stat",  "icon": "bi-...", "scope": "<entry id>",
         "link": "https://..."},
        {"id": "<id>", "view": "table", "icon": "bi-...", "selector": true}
    ]

The widget's **title** is the module's translated ``pretty_name``; its **data** is
produced by the module's ``Watchful.overview_widget(items, status, lang)`` hook
(generic shape: ``{entries: [...], aggregate: {...}}``) — the same data feeds every
widget the module contributes.  Nothing module-specific lives in the core.

Per-widget keys:

* ``view`` — ``stat`` (a Servers-like stat card: a big count + a coloured badge per
  state; the default) or ``table`` (a dense listing).
* ``id`` — distinguishes a module's widgets (``''`` = the primary one, key
  ``mw_<module>``; others are ``mw_<module>_<id>``).
* ``scope`` (stat) — which entry the card shows, by its ``id`` (from the hook's
  ``entries``); ``''`` = aggregate across every entry.
* ``selector`` (table) — show the scope selector (all / aggregate / a specific entry).
* ``link`` — makes the widget clickable: opens that external URL in a new tab.
"""

from __future__ import annotations

import json
import os

# Reuse the credential-catalog helpers (watchfuls dir resolution + lang loader).
from lib.modules.discovery.credential_schemas import _watchfuls_dir, _module_i18n


def _widget_spec(d: dict) -> dict:
    """Normalise one ``__overview_widget__`` declaration into a widget descriptor.
    ``view`` = ``stat`` (a Servers-like stat card, default) or ``table`` (a dense
    listing with a scope selector)."""
    return {
        'id':       str(d.get('id') or ''),          # '' = the module's primary widget
        'view':     'table' if d.get('view') == 'table' else 'stat',
        'icon':     str(d.get('icon') or 'bi-grid-1x2'),
        'perm':     str(d.get('perm') or 'modules_view'),
        'cols':     int(d.get('cols') or 4),
        'h':        d.get('h') or 340,
        'scope':    str(d.get('scope') or ''),        # stat: which check kind to show
        'link':     str(d.get('link') or ''),         # click-through URL (opens in a new tab)
        'selector': bool(d.get('selector')),          # table: show the scope selector
        'multi':    bool(d.get('multi')),
    }


def overview_widgets_catalog(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: {module, label_i18n, widgets: [descriptor, ...]}}`` for every
    module declaring ``__overview_widget__`` (a single dict, or a list to contribute
    several widgets — e.g. a stat card AND a table).  The label is the module's
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
        if isinstance(decl, dict):
            decls = [decl]
        elif isinstance(decl, list):
            decls = [d for d in decl if isinstance(d, dict)]
        else:
            continue
        if not decls:
            continue
        lang_data = _module_i18n(os.path.join(base, entry))
        label_i18n = {lang: data.get('pretty_name')
                      for lang, data in lang_data.items()
                      if isinstance(data, dict) and isinstance(data.get('pretty_name'), str)}
        out[entry] = {
            'module':     entry,
            'label_i18n': label_i18n or {'en_EN': entry},
            'widgets':    [_widget_spec(d) for d in decls],
        }
    return out
