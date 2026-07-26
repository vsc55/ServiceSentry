#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mapping an identity provider's groups onto an application role.

Shared by the SSO providers that receive **plain group names** (OIDC, SAML2).  LDAP keeps
its own variant on purpose: Active Directory's ``memberOf`` returns full DNs, so it also
matches a short pattern against the first RDN (``CN=Admins,OU=…`` ← ``Admins``).  For a
value with no ``=`` the two are equivalent, but folding them together would give OIDC and
SAML that DN parsing too — harmless for a normal group name, yet a real behaviour change
for one containing ``,`` and ``=``.  A rename is not worth an edge case nobody asked for.
"""

from __future__ import annotations

# Highest wins: an identity in several mapped groups gets the strongest role, so adding a
# user to "viewers" can never take away admin they hold through another group.
ROLE_PRIORITY = ('admin', 'editor', 'viewer')


def map_role(groups: list, group_role_map: dict) -> str:
    """Best-matching application role for *groups*, or ``''`` when nothing matches.

    Matching is exact and case-insensitive.  Deliberately NOT a substring test: with one,
    a pattern of ``Admins`` would also match ``Admins-ReadOnly`` and silently promote it.

    A role the map produces but that is not in :data:`ROLE_PRIORITY` (a custom role) still
    wins over no role at all — it is returned once the known tiers are exhausted.
    """
    matched: dict = {}
    for g in groups:
        for pattern, role in (group_role_map or {}).items():
            if pattern.lower() == str(g).lower() and role not in matched:
                matched[role] = g
    for role in ROLE_PRIORITY:
        if role in matched:
            return role
    for role in matched:
        return role
    return ''
