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
package while the panel only knows "render a button that calls this name".  It is called
with the **section id** as its only argument, so one function can serve several sections
(the Entra "check permissions" button is the same code for ``oidc`` and ``saml2``); a
handler that only ever serves one section simply declares no parameter and ignores it.

``show_when`` is a tiny declarative gate evaluated by the frontend against the section's
current values: ``{'field': <name>, 'not_empty': True}`` renders the button only when
that field has a value (e.g. no "rotate secret" until an app is registered).

``perm`` (optional) names a permission flag the user must hold for the button to be
rendered at all — destructive actions declare the same flag their API endpoint enforces
(e.g. ``history_delete``). It is a UI gate on top of, never instead of, the server check.

``group_label_key`` (optional) names the group an action belongs to, and the caption shown
above it (e.g. "Entra ID", so the row says WHOSE actions these are). Actions sharing a key
are rendered together; a section whose actions declare different keys shows one group each,
in declaration order, and anything without a key falls back to the generic label.

``desc_key`` (optional) is one line saying what the action DOES, shown beside its label. A
button caption has room for a verb and a noun, which is enough to identify an action you
already know and not enough to tell you what it will do to your data — and Maintenance is a
section where being wrong about that is expensive.

``button_key`` (optional) is what the BUTTON says, when the surrounding card already carries
the name and the description. "Eliminar todos los eventos de auditoría" is the right title
and a terrible button: the card has said all of that, so the button only has to name the verb
("Borrar", "Vaciar"). Falls back to ``label_key``, which is what the single-row layout needs
and what an action with nothing around it should keep saying.

Variants are SOLID Bootstrap names (``primary``/``secondary``/``warning``…) — outline
variants are not used in this UI.
"""

from __future__ import annotations

# Where a package may declare config actions (same roots the notify-event discovery uses).
_PKG_ROOTS = ('lib.providers', 'lib.services', 'lib.core')

_ALLOWED = ('section', 'id', 'label_key', 'tooltip_key', 'icon', 'variant',
            'order', 'fn', 'show_when', 'group_label_key', 'desc_key', 'button_key',
            'perm')


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
