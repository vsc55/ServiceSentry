#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reading attributes off an ldap3 entry.

``ldap3`` does not return ``None`` for an attribute the entry does not carry — accessing
it **raises**.  So every read of an optional attribute needs a guard, and the codebase had
that guard written out eight times across :mod:`~lib.providers.ldap.auth` and
:mod:`~lib.providers.ldap.routes`, each an ``except Exception: pass``.

The broad catch is correct here and stays: the exception type is ldap3's own
(``LDAPCursorAttributeError`` and friends, which move between releases), the attribute
being absent is the expected case rather than a fault, and a directory that simply does
not publish ``displayName`` must not fail a login.  What was wrong is that the reasoning
lived nowhere and the pattern lived everywhere.

This is only for OPTIONAL attributes.  A failure that should change the outcome — a search
that errors, a bind that is refused — must not be routed through here; those are logged
where they happen.
"""

from __future__ import annotations


def attr_value(entry, name: str) -> str:
    """First value of *name* on *entry* as a string, or ``''`` when it is absent."""
    try:
        v = getattr(entry, name)
        if v and hasattr(v, 'values') and v.values:
            return str(v.values[0])
    except Exception:  # pylint: disable=broad-except  (ldap3 raises on a missing attribute)
        pass
    return ''


def attr_values(entry, name: str) -> list:
    """All values of *name* on *entry* as strings, or ``[]`` when it is absent."""
    try:
        v = getattr(entry, name)
        if v and hasattr(v, 'values'):
            return [str(x) for x in v.values]
    except Exception:  # pylint: disable=broad-except  (ldap3 raises on a missing attribute)
        pass
    return []


def first_named(entry, *names: str) -> str:
    """First non-empty value among *names* — e.g. ``displayName`` then ``cn``."""
    for n in names:
        val = attr_value(entry, n)
        if val:
            return val
    return ''
