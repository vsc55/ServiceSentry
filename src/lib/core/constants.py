#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Foundational, layer-agnostic constants.

These live in ``lib.core`` (the foundational layer) so that core domains,
providers and the web admin can all import them in the correct direction
(everyone → ``lib.core``), instead of ``lib.core`` reaching up into
``lib.web_admin`` for them.
"""

# Reserved internal username for system-generated audit entries.
# This name MUST NOT be assigned to any real user account.
SYSTEM_USER: str = 'system'

# ── Built-in identities ─────────────────────────────────────────────────────────────
# Stable UUIDs for the built-in roles and groups.  NEVER change them: they are the
# identity of a role/group in the database, in every user record that references one,
# and over SCIM.
#
# They live here, and not with a domain, because no single domain owns them: users,
# groups, roles, permission resolution, SCIM and the CLI all name them.  They sat in the
# permissions catalog, which was the one module that never used them — and putting them
# in ``lib.core.roles`` instead would make the permissions catalog import a domain while
# that domain already imports the catalog.  This module exists precisely so the direction
# stays one-way (everyone → ``lib.core``).
BUILTIN_ROLE_UIDS: dict[str, str] = {
    'admin':    '00000000-0000-4000-8000-000000000001',
    'editor':   '00000000-0000-4000-8000-000000000002',
    'viewer':   '00000000-0000-4000-8000-000000000003',
    'none':     '00000000-0000-4000-8000-000000000000',
}

BUILTIN_GROUP_UIDS: dict[str, str] = {
    'administrators': '00000000-0000-4000-8000-000000000010',
}

# Built-in groups by UID — they cannot be deleted or modified.  Precomputed because it is
# asked once per group on every listing.
BUILTIN_GROUP_UID_SET: frozenset[str] = frozenset(BUILTIN_GROUP_UIDS.values())

# The built-in role keys, highest privilege first.  DERIVED from the UID map rather than
# written again: the same four names used to exist as two independent literals, so adding
# a built-in role meant remembering both.
ROLES: tuple[str, ...] = tuple(BUILTIN_ROLE_UIDS)
