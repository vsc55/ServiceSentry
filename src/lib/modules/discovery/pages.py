#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-contributed top-level pages — generic catalog (core, no module code).

A watchful module may claim a **section of its own** — a top-level page beside
Overview / History / Syslog, with its URL, its sidebar entry and its own pane —
by declaring ``__page__`` in its ``schema.json``::

    "__page__": {"id": "m365", "icon": "bi-microsoft", "order": 40,
                 "render": "renderM365Page", "perm": "modules_view"}

Everything module-specific (icon, what the page shows, how it looks) comes from the
module; the core only reads these generic keys and never hard-codes a module.

Per-page keys (all optional except where noted):

* ``id`` — the page id; defaults to the module name.  It becomes the URL
  (``/<id>``), the pane (``tab-<id>``) and the sidebar button (``btn-nav-<id>``),
  so it must be unique and URL-safe.
* ``icon`` — Bootstrap icon for the sidebar entry.
* ``order`` — position among the sections (core pages use 10/20/30).
* ``render`` — name of the JS entry point the wiring calls when the pane opens.
  The module ships it in its own ``web/_ui.html`` (same contract as a
  ``CONFIG_ACTION``'s ``fn``).  **Omit it** to get the core's generic renderer, which
  paints whatever ``page_data`` returned — a module needs no front-end code at all.
* ``refresh`` — name of the watchful action the generic renderer's "refresh" button
  calls for live data (e.g. ``page_refresh``).  Omit it and the page is cache-only.
* ``perm`` — permission gating BOTH the route and the sidebar entry.  Defaults to
  ``modules_view``: watchful modules own no permission flags of their own (they
  have no Python manifest), so a page must reuse an existing one.

The page's **title** is the module's translated ``pretty_name``, exactly like a
module-contributed Overview widget — no core string names a module.

The **data** comes from the module's ``Watchful.page_data(items, status, lang)``
hook (cached monitor results, instant), and a live refresh is a normal watchful
action (``/api/v1/modules/watchfuls/<module>/<action>``) the module declares and
serves itself.
"""

from __future__ import annotations

import json
import os
import re

# Reuse the credential-catalog helpers (watchfuls dir resolution + lang loader).
from lib.modules.discovery.credential_schemas import _watchfuls_dir, _module_i18n

# The id lands in a URL, an element id and a Bootstrap tab target, so keep it to
# the same shape the action dispatch already demands of a module name.
_ID_RE = re.compile(r'^[a-z][a-z0-9_]*$')

# Ids the core already owns — a module may not shadow a built-in section, the admin
# panel or the public status page.
_RESERVED = frozenset({'admin', 'overview', 'history', 'syslog', 'status', 'account', 'login'})


def _page_spec(module: str, d: dict) -> dict | None:
    """Normalise one ``__page__`` declaration into a page descriptor.

    Returns ``None`` for anything unusable (bad or reserved id), so one malformed
    declaration can never break the panel — the section just does not appear.
    """
    if not isinstance(d, dict):
        return None
    pid = str(d.get('id') or module).strip().lower()
    if not _ID_RE.match(pid) or pid in _RESERVED:
        return None
    return {
        'id':     pid,
        'module': module,
        'icon':   str(d.get('icon') or 'bi-grid-1x2'),
        'order':  int(d.get('order') or 100),
        'render': str(d.get('render') or ''),      # '' = core renders from page_data alone
        'refresh': str(d.get('refresh') or ''),    # watchful action for the live refresh
        'perm':   str(d.get('perm') or 'modules_view'),
    }


def module_pages_catalog(watchfuls_dir: str | None = None) -> list:
    """Return the ordered descriptors of every module claiming a top-level page.

    Each is ``{id, module, icon, order, render, perm, label_i18n}``; the label is
    the module's translated ``pretty_name``.  Ordered by ``(order, id)``; a module
    whose id collides with an earlier one is dropped (first declaration wins), so
    the registry can never end up with two sections fighting over a URL.
    """
    out: list = []
    seen: set = set()
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
        spec = _page_spec(entry, schema.get('__page__'))
        if spec is None or spec['id'] in seen:
            continue
        seen.add(spec['id'])
        lang_data = _module_i18n(os.path.join(base, entry))
        label_i18n = {lang: data.get('pretty_name')
                      for lang, data in lang_data.items()
                      if isinstance(data, dict) and isinstance(data.get('pretty_name'), str)}
        spec['label_i18n'] = label_i18n or {'en_EN': entry}
        out.append(spec)
    return sorted(out, key=lambda p: (p['order'], p['id']))
