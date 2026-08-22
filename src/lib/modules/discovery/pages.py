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
* ``views`` — optional list of the section's VIEWS.  A module that has more than one
  thing to show does not claim a second section: it declares its views here and the
  sidebar entry becomes a parent with a flyout, exactly like Infrastructure's or
  Access's.  They share the page's URL, its pane and its permission — a view is a
  sub-path (``/m365/storage``), never a route of its own::

      "views": [{"slug": "status",  "icon": "bi-activity", "label": "view_status"},
                {"slug": "storage", "icon": "bi-hdd", "label": "view_storage",
                 "kind": "table", "action": "storage_report"}]

  Per view: ``slug`` (URL-safe, required), ``icon``, ``label`` (a key in the MODULE's
  own lang file — the core owns no string naming a module's view), ``kind``
  (``rows`` = the section/row layout, the default; ``table`` = the generic inventory
  table) and ``action`` (a watchful action answering that view's data; declaring one
  makes the view LIVE — it asks when opened and keeps nothing).  The first view is the
  one a bare ``/m365`` opens.

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

# Ids the core already owns. The URL is no longer the reason — module pages live under
# `/module/<id>`, so a path collision is impossible by construction — but the id is ALSO the
# pane (`tab-<id>`) and the sidebar button (`btn-nav-<id>`), and those share one namespace
# with the core's. A module calling itself `overview` would render into the core's pane.
_RESERVED = frozenset({'admin', 'overview', 'history', 'syslog', 'status', 'account', 'login'})


def _views(d: dict) -> list:
    """Normalise the optional ``views`` list.

    Anything unusable is dropped rather than raising: a malformed view costs its own
    entry in the flyout, never the section.  Fewer than two usable views means the
    section has nothing to choose between, so it renders as the plain item it was —
    a parent with one child is a menu that wastes a click.
    """
    out, seen = [], set()
    for v in (d.get('views') or []):
        if not isinstance(v, dict):
            continue
        slug = str(v.get('slug') or '').strip().lower()
        if not _ID_RE.match(slug) or slug in seen:
            continue
        seen.add(slug)
        out.append({
            'slug':   slug,
            'icon':   str(v.get('icon') or 'bi-grid-1x2'),
            'label':  str(v.get('label') or ''),      # key in the MODULE's lang file
            'kind':   str(v.get('kind') or 'rows'),
            'action': str(v.get('action') or ''),     # declared → the view is live
        })
    return out if len(out) > 1 else []


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
    # WHERE the page belongs, declared rather than assumed. A section of its own is the
    # right home for something an operator watches — m365's status, azure's — and the wrong
    # one for something an operator ADMINISTERS: the MIB library is managed beside Services,
    # Modules and Credentials, not beside the dashboards. The core places it; it still has no
    # idea which module asked.
    placement = str(d.get('placement') or 'section').strip().lower()
    if placement not in ('section', 'system'):
        placement = 'section'
    return {
        'id':     pid,
        'module': module,
        'icon':   str(d.get('icon') or 'bi-grid-1x2'),
        'order':  int(d.get('order') or 100),
        'placement': placement,
        'render': str(d.get('render') or ''),      # '' = core renders from page_data alone
        'refresh': str(d.get('refresh') or ''),    # watchful action for the live refresh
        'perm':   str(d.get('perm') or 'modules_view'),
        'views':  _views(d),                       # [] = a plain section, no flyout
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
        # A view names itself in the MODULE's own lang file, the same rule the section
        # title follows: no core string may name a module's view. `ui` first because that
        # is where a module keeps its page vocabulary, `labels` after it for the modules
        # that never grew a `ui` block.
        for view in spec['views']:
            texts = {}
            for lang, data in lang_data.items():
                if not isinstance(data, dict):
                    continue
                for section in ('ui', 'labels'):
                    val = (data.get(section) or {}).get(view['label']) \
                        if isinstance(data.get(section), dict) else None
                    if isinstance(val, str) and val:
                        texts[lang] = val
                        break
            view['label_i18n'] = texts or {'en_EN': view['slug']}
        out.append(spec)
    out.extend(_core_pages(seen))
    return sorted(out, key=lambda p: (p['order'], p['id']))


def _core_pages(seen: set) -> list:
    """Sections a CORE package claims, declared as ``PAGE`` in its manifest.

    Same descriptor, same sidebar, same rules — the only difference is where the words come
    from. A module's section is titled by its ``pretty_name`` and its views named in its own
    lang file, because the core owns no string that names a module; a core section names
    itself, so its labels come from core i18n under the section the declaration points at.

    It exists because a page can outlive the module that used to declare it: SNMP's MIB
    library and profile catalogue are the core's, and a screen that disappeared when somebody
    removed the watchful would be a library you can still fill and no longer look at.
    """
    from lib.discovery import scan                     # noqa: PLC0415
    from lib.i18n import TRANSLATIONS                   # noqa: PLC0415

    def _texts(section: str, key: str) -> dict:
        out = {}
        for lang, data in TRANSLATIONS.items():
            val = ((data.get(section) or {}) if isinstance(data, dict) else {}).get(key)
            if isinstance(val, str) and val:
                out[lang] = val
        return out

    pages = []
    for pkg, decl in scan('PAGE'):
        spec = _page_spec(pkg, decl if isinstance(decl, dict) else None)
        if spec is None or spec['id'] in seen:
            continue
        seen.add(spec['id'])
        section = str((decl or {}).get('i18n') or '').strip()
        spec['module'] = ''            # nobody's module: the sidebar already allows this
        spec['label_i18n'] = (_texts(section, 'title') if section else {}) or {'en_EN': pkg}
        for view in spec['views']:
            view['label_i18n'] = (_texts(section, view['label']) if section else {}) \
                or {'en_EN': view['slug']}
        pages.append(spec)
    return pages
