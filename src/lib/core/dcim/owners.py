#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whose is this, and therefore who may see it — the inventory's half of it.

The rule itself is no longer here. Ownership is said at whatever level somebody knows it and
inherited downwards, innermost wins, and that is true of a rack, a host and a Microsoft 365
mailbox alike — so it lives in :mod:`lib.core.orgs.owners`, where a package that has never heard
of a cabinet can use it. This module re-exports it under the names forty call sites already use.

What stays is what only makes sense here:

* :func:`chain` — how to walk from an item up to its site, which is this domain's containment
  and nobody else's;
* :func:`opaque` — what is left of somebody else's rack item: it EXISTS, it OCCUPIES, and that
  is all it says.

**A shared rack is the reason any of this exists.** A holding's IT department shares a cabinet
between the group's companies; somebody from company B must see the rack, must see that U 12 is
taken — otherwise planning is impossible — and must not see whose it is or what it is called.

Two rules hold in this domain, written here rather than in each screen:

1. **Counts follow visibility.** A rack reporting "3 devices down" of which none are yours is an
   enumeration of somebody else's fleet through the back door — the same shape as the IDOR audit
   of 2026-05. What is counted is what can be seen.
2. **Free space is everybody's.** "6U free" reveals nothing about anybody and is half the reason
   this exists at all.
"""

from __future__ import annotations

from lib.core.orgs.owners import (ALL_ORGS_PERM, ORG_SCOPE,   # noqa: F401  (re-exported)
                                  may_see, owner_of, visible_orgs)


def chain(wa, scope: str, uid: str) -> list:
    """``[(scope, uid), …]`` from *uid* up to its site, innermost first.

    Declared to :mod:`lib.core.orgs.scopes` (see this package's manifest) so the core can
    resolve who owns an item without knowing that rooms are inside sites. The walk itself is
    :meth:`DcimStore.chain_of`, which is where the tables are.
    """
    store = getattr(wa, '_dcim_store', None)
    if store is None:
        return [(str(scope or ''), str(uid or ''))]
    return store.chain_of(scope, uid)


def opaque(item) -> dict:
    """Somebody else's item, as much of it as may be said: it exists, and it occupies.

    Built by REMOVING from a copy rather than by copying the safe fields across. The two are the
    same today and stop being the same the first time a column is added: a whitelist that is not
    updated omits a field, which is a screen with a hole in it, and a blacklist that is not
    updated leaks one. Only one of those two failures is a security bug, so the code is written
    to fail the other way.
    """
    keep = ('uid', 'rack_uid', 'u_start', 'u_height', 'face')
    out = {k: item.get(k) for k in keep}
    out['foreign'] = True
    return out
