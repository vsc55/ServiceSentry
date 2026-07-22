#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Directory group sources contributed by a provider (self-describing).

The group→role mapping widget lets an admin pull the groups straight from the directory
backing that auth section instead of typing DNs / object ids by hand.  Which directory
that is depends on the provider (LDAP for ``ldap``, Microsoft Graph for ``oidc``/``saml2``)
— knowledge that used to live in ``web_admin`` as ``sec === 'ldap'`` / ``'oidc'|'saml2'``
branches, including each provider's endpoint and even its request-body field name.

Now every provider declares its own source in its ``manifest.py`` (see
:mod:`lib.discovery`) and the panel renders the button, the picker and the name lookup
generically::

    GROUP_SOURCES = [
        {'section': 'ldap',                     # the config section it backs
         'label_key': 'grm_fetch_groups',       # i18n key of the fetch button
         'icon': 'bi-cloud-download',
         'fetch_fn': '_ldapFetchGroups',        # JS the provider ships in web/*_ui.html
         'pick_fn': '_ldapPickGroup',
         'lookup_url': '/api/v1/auth/ldap/group_lookup',
         'lookup_key': 'dn',                    # body field carrying the group id
         'picker_id': 'ldapGroupPicker',
         'hint_key': 'grm_pick_hint'},
    ]

Adding a third IdP is then "drop a provider with a manifest + its web UI" — no change in
``web_admin``.  A section simply *without* a source renders no fetch button (and no
display-name column), so the capability drives the UI instead of a hardcoded list of
section names.
"""

from __future__ import annotations

_PKG_ROOTS = ('lib.providers', 'lib.core', 'lib.services')

_ALLOWED = ('section', 'label_key', 'icon', 'fetch_fn', 'pick_fn',
            'lookup_url', 'lookup_key', 'picker_id', 'hint_key')

#: Keys a usable source must carry (without them the panel could not render/call it).
_REQUIRED = ('section', 'label_key', 'fetch_fn', 'lookup_url', 'picker_id')


def _normalize(raw) -> dict | None:
    """Keep known keys; drop anything missing what the renderer needs."""
    if not isinstance(raw, dict):
        return None
    src = {k: raw[k] for k in _ALLOWED if k in raw}
    if not all(src.get(k) for k in _REQUIRED):
        return None
    src.setdefault('lookup_key', 'id')
    src.setdefault('icon', 'bi-cloud-download')
    return src


def discover_group_sources() -> list[dict]:
    """Every declared group source, one per section (first declaration wins)."""
    from lib.discovery import scan_flat  # noqa: PLC0415
    seen: dict[str, dict] = {}
    for raw in scan_flat('GROUP_SOURCES', roots=_PKG_ROOTS):
        src = _normalize(raw)
        if src and src['section'] not in seen:
            seen[src['section']] = src
    return list(seen.values())


def group_source_for(section: str) -> dict | None:
    """The group source backing *section*, or None when it has none."""
    for src in discover_group_sources():
        if src['section'] == section:
            return src
    return None
