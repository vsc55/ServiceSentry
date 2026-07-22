#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config-section actions contributed by a package (self-describing).

A provider/service/module may add **buttons** to a config section (e.g. the Entra ID
"Register in Azure" / "Rotate secret" buttons on the OIDC card) WITHOUT any package
specific code living in ``web_admin``: it declares them as data here, and the panel
renders them generically.

Convention — a package declares ``CONFIG_ACTIONS`` in its ``manifest.py`` (see
:mod:`lib.discovery`)::

    CONFIG_ACTIONS = [
        {'section': 'oidc', 'id': 'rotate_secret',
         'label_key': 'entra_oidc_secret_rotate',      # i18n key for the caption
         'tooltip_key': 'entra_oidc_secret_rotate_tt', # optional
         'icon': 'bi-arrow-repeat', 'variant': 'warning', 'order': 20,
         'fn': 'showEntraOidcRotateSecret',            # global JS fn the package ships
         'show_when': {'field': 'client_id', 'not_empty': True}},
    ]

``fn`` names a JavaScript function the SAME package ships in its ``web/*_ui.html``
(injected by the package web-assets discovery), so the behaviour travels with the
package while the panel only knows "render a button that calls this name".

``show_when`` is a tiny declarative gate evaluated by the frontend against the section's
current values: ``{'field': <name>, 'not_empty': True}`` renders the button only when
that field has a value (e.g. no "rotate secret" until an app is registered).

``perm`` (optional) names a permission flag the user must hold for the button to be
rendered at all — destructive actions declare the same flag their API endpoint enforces
(e.g. ``history_delete``). It is a UI gate on top of, never instead of, the server check.

``group_label_key`` (optional) names the caption of the actions row. When every visible
action of a section shares the same one, the panel uses it (e.g. "Entra ID" instead of a
generic "Actions"), so the row says WHOSE actions these are; when actions from different
packages share a section, it falls back to the generic label.

Variants are SOLID Bootstrap names (``primary``/``secondary``/``warning``…) — outline
variants are not used in this UI.
"""

from __future__ import annotations

# Where a package may declare config actions (same roots the notify-event discovery uses).
_PKG_ROOTS = ('lib.providers', 'lib.services', 'lib.core')

_ALLOWED = ('section', 'id', 'label_key', 'tooltip_key', 'icon', 'variant',
            'order', 'fn', 'show_when', 'group_label_key', 'perm')


def _normalize(raw) -> dict | None:
    """Keep only known keys; drop anything without a section, id, label_key and fn."""
    if not isinstance(raw, dict):
        return None
    act = {k: raw[k] for k in _ALLOWED if k in raw}
    if not all(act.get(k) for k in ('section', 'id', 'label_key', 'fn')):
        return None
    act.setdefault('variant', 'secondary')
    act.setdefault('order', 100)
    return act


def discover_config_actions() -> list[dict]:
    """Every config action declared by any package, sorted by (section, order, id).

    Declarations live in each package's ``manifest.py`` (``CONFIG_ACTIONS``); the shared
    scanner collects them and this only normalises + orders."""
    from lib.discovery import scan_flat  # noqa: PLC0415
    found = [a for a in (_normalize(r)
                         for r in scan_flat('CONFIG_ACTIONS', roots=_PKG_ROOTS)) if a]
    return sorted(found, key=lambda a: (a['section'], a.get('order', 100), a['id']))


def actions_for(section: str) -> list[dict]:
    """The declared actions for one config *section*, in render order."""
    return [a for a in discover_config_actions() if a['section'] == section]
