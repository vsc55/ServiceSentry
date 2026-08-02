#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Foundational, layer-agnostic constants.

These live in ``lib.core`` (the foundational layer) so that core domains,
providers and the web admin can all import them in the correct direction
(everyone → ``lib.core``), instead of ``lib.core`` reaching up into
``lib.web_admin`` for them.

**Which names get a constant.**  Only the ones that are STORED.  ``SYSTEM_USER`` and
``ANONYMOUS_USER`` are values written into rows — the audit ``user`` column, ``actor``,
``updated_by`` — in about forty places, so they get a name.  The built-in group and role keys
(``'administrators'``, ``'admin'``…) stay literals: they only ever INDEX the map below, right
next to it, and ``ROLES`` is derived rather than written again.

The dividing line is how each one fails.  A mistyped key raises ``KeyError`` on the spot; a
mistyped value writes an audit entry attributed to an actor that does not exist, and nothing
notices until somebody reads the log asking who did something.  So the thing that fails
silently gets the single spelling, and the thing that fails loudly does not need one.
"""

# Reserved internal username for system-generated audit entries.
# This name MUST NOT be assigned to any real user account.
SYSTEM_USER: str = 'system'

# …and for entries caused by someone who never identified themselves: a SCIM client with a
# bad bearer token, and anything else that is refused before an identity exists.
#
# NOT `system`, which means the panel acted on its own — a service starting, a scheduled
# prune. An intrusion attempt filed under `system` reads as the panel doing it to itself, and
# it lands in the one filter these entries are most often looked up by. Blank is no better: an
# empty cell reads as a missing value rather than as "there was no identity to record".
ANONYMOUS_USER: str = 'anonymous'

# ── Built-in identities ─────────────────────────────────────────────────────────────
# The stable UUIDs of every built-in role, group and user, in ONE declaration: "which UIDs
# are built in" then has a single answer, and the reverse lookup below can exist at all.
#
# They live here, and not with a domain, because no single domain owns them: users,
# groups, roles, permission resolution, SCIM and the CLI all name them.  They sat in the
# permissions catalog, which was the one module that never used them — and putting them
# in ``lib.core.roles`` instead would make the permissions catalog import a domain while
# that domain already imports the catalog.  This module exists precisely so the direction
# stays one-way (everyone → ``lib.core``).
#
# The **variant block** carries the kind: ``…-8001-…`` users, ``…-8002-…`` groups,
# ``…-8003-…`` roles.  A UID therefore says what it names without any lookup, and a new kind
# takes the next value.  (``8``/``9``/``a``/``b`` in the first position is what makes a UUID
# RFC-4122 variant 1, so the whole family stays valid.)
#
# A UID is the identity of that role/group in the database, in every user record referencing
# one, and over SCIM — so these values are FIXED from here on.  Changing one again would need
# a rewrite of everything holding it, not an edit here: nothing raises, it simply resolves to
# "unknown role" and demotes every account on the next read.

# The namespace itself, declared ONCE and composed into every value below.  Written this way
# round — prefix first, identities built from it — so a built-in cannot be declared outside
# the reserved range at all; deriving the prefix back out of the values would have left that
# possible and merely detectable.  One edit here moves every built-in together.
#
# It is reserved: nothing else may ever be minted inside it (``lib.core.uids.new_uid`` holds
# up the other end), which is what lets "is this UID one of ours?" be answered by looking at
# the value instead of searching three tables — with no false positive possible.
#
# The trailing dash belongs to the prefix, not to the seven call sites: composing is then a
# plain concatenation with no punctuation to remember, and the one site that forgot it would
# produce a malformed identifier rather than an error.  It also anchors the group boundary in
# the ``startswith`` test.
BUILTIN_UID_PREFIX: str = '00000000-0000-4000-'

BUILTIN_UIDS: dict[str, dict[str, str]] = {
    'user': {
        SYSTEM_USER:    BUILTIN_UID_PREFIX + '8001-000000000001',
        ANONYMOUS_USER: BUILTIN_UID_PREFIX + '8001-000000000002',
    },
    'group': {
        'administrators': BUILTIN_UID_PREFIX + '8002-000000000001',
    },
    'role': {
        'none':     BUILTIN_UID_PREFIX + '8003-000000000000',
        'admin':    BUILTIN_UID_PREFIX + '8003-000000000001',
        'editor':   BUILTIN_UID_PREFIX + '8003-000000000002',
        'viewer':   BUILTIN_UID_PREFIX + '8003-000000000003',
    },
}


# ── Derived views ───────────────────────────────────────────────────────────────────
# The names everything already imports, all DERIVED from the map above so a UID is still
# written in exactly one place.
#
# ``BUILTIN_ROLE_UIDS`` is rebuilt highest privilege first — the order ``ROLES`` means — which
# the declaration is not (``none`` leads it there so the ranges read in order).
BUILTIN_ROLE_UIDS: dict[str, str] = {
    k: BUILTIN_UIDS['role'][k] for k in ('admin', 'editor', 'viewer', 'none')
}

# The built-in role keys, highest privilege first: the same four names used to exist as two
# independent literals, so adding a built-in role meant remembering both.
ROLES: tuple[str, ...] = tuple(BUILTIN_ROLE_UIDS)

BUILTIN_GROUP_UIDS: dict[str, str] = dict(BUILTIN_UIDS['group'])

# Built-in groups by UID — they cannot be deleted or modified.  Precomputed because it is
# asked once per group on every listing.
BUILTIN_GROUP_UID_SET: frozenset[str] = frozenset(BUILTIN_GROUP_UIDS.values())

# The two identities the panel writes under itself.  They are accounts in every sense that
# matters to a reader of the audit log — a name, a stable UID, a row in the users list — and
# in no sense that matters to a login: no password, no session, no permissions.  Giving them
# UIDs is what makes them first-class: before this they were bare strings, so the one column
# that answers "who did this" pointed at nothing the rest of the system knew about.
#
# Built-in the same way a role or a group is: declared once, never editable, never deletable.
BUILTIN_USER_UIDS: dict[str, str] = dict(BUILTIN_UIDS['user'])

BUILTIN_USER_UID_SET: frozenset[str] = frozenset(BUILTIN_USER_UIDS.values())

# Which kind a UID names, or ``None`` for anything not built in.  The reverse map is also what
# makes "no two built-ins share a UID" checkable rather than merely intended.
BUILTIN_UID_KIND: dict[str, str] = {
    uid: kind for kind, uids in BUILTIN_UIDS.items() for uid in uids.values()
}


def builtin_kind(uid) -> str | None:
    """``'role'`` / ``'group'`` / ``'user'`` for a built-in UID, else ``None``."""
    return BUILTIN_UID_KIND.get(str(uid or ''))

# Neither may ever belong to a real account. An audit entry answers "who did this", and a user
# able to take one of these names would have their actions read as the panel's own, or as an
# unauthenticated caller's — the log would still be complete and no longer trustworthy.
#
# Checked as a SET rather than one name at a time, and from here rather than in each caller,
# because accounts arrive by five different doors: the users API, and the four that provision
# on the fly (LDAP, OIDC, SAML2, SCIM). Only the first one used to check, so an IdP with a
# user called `system` created a local `system` and nothing anywhere noticed.
#
# DERIVED from the UID map: a third built-in identity is one line, not two that can diverge.
RESERVED_USERNAMES: frozenset[str] = frozenset(BUILTIN_USER_UIDS)


def is_reserved_username(name) -> bool:
    """Is *name* one of the identities the audit log reserves? Case-insensitive."""
    return str(name or '').strip().lower() in RESERVED_USERNAMES
