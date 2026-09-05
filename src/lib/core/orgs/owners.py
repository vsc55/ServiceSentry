#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whose is this, and therefore who may see it. The rules, with no database in sight.

Ownership is **said** at whatever level somebody knows it and **inherited** downwards, innermost
wins; so the effective owner of anything is found by walking up its containment chain until the
first thing that was said.

The second half is the one with teeth. **A shared container breaks the assumption that seeing a
place means seeing what is in it.** A holding's IT department shares a cabinet between the
group's companies; somebody from company B must see the rack, must see that U 12 is taken —
otherwise planning is impossible — and must not see whose it is or what it is called. The same
shape turns up the moment a second package owns anything: a tenant shared between two
subsidiaries, a subscription somebody else pays for.

So a read of an owned thing has three outcomes, not two:

* **visible** — theirs, or they hold every company;
* **opaque** — somebody else's: it EXISTS, it OCCUPIES, and that is all it says;
* **absent** — nothing, for the things that carry no useful shape.

Opaque is the one that matters and the one that is easy to get wrong in the direction of a leak.
Two rules hold wherever it is used, and each package decides what shape it leaves behind:

1. An opaque thing has no name, no model, no serial and **no state**. What it keeps is what
   makes the container plannable — "U 12 to 13 are taken" — and that says nothing about whose
   they are.
2. **Counts follow visibility.** A rack reporting "3 devices down" of which none are yours is an
   enumeration of somebody else's fleet through the back door — the same shape as the IDOR audit
   of 2026-05. What is counted is what can be seen.
"""

from __future__ import annotations

#: The permission that grants every company at once. Named `_view` and not `_all` because
#: `viewer` being read-only is a NAMING invariant here — every flag that role holds ends in
#: `_view`, which is what makes "is this role read-only" answerable by looking rather than by
#: reading six manifests (tests/unit/test_wa_roles.py).
ALL_ORGS_PERM = 'orgs_all_view'

#: The per-company scope, minted the way `server.<uid>.view` is minted per device.
ORG_SCOPE = 'org.%s.view'


def owner_of(chain, said) -> str:
    """The company something belongs to, or ``''`` if nobody ever said.

    *chain* is ``[(scope, uid), …]`` innermost first — :func:`lib.core.orgs.scopes.chain_of` —
    and *said* is the map of declared ownerships (:meth:`OrgsStore.said`). Passing both in
    rather than reaching for a store is what lets a screen resolve four hundred items off two
    reads.
    """
    for scope, uid in chain or ():
        org = said.get((scope, uid))
        if org:
            return str(org)
    return ''


def visible_orgs(perms) -> set | None:
    """The companies a caller may see, or ``None`` for "all of them".

    ``None`` and ``set()`` are deliberately different answers: the first is a panel operator who
    holds the fleet, the second is somebody who has been granted a section and no company at all
    — who should see the containers with every item opaque, rather than an error. A screen that
    treats "no companies" as "no access" locks out exactly the person the scope was invented for.
    """
    perms = set(perms or ())
    if ALL_ORGS_PERM in perms:
        return None
    out = set()
    for p in perms:
        if p.startswith('org.') and p.endswith('.view'):
            uid = p[len('org.'):-len('.view')]
            if uid:
                out.add(uid)
    return out


def may_see(org_uid, allowed) -> bool:
    """Whether a thing owned by *org_uid* is visible to a caller with *allowed*.

    Something **nobody claims** is visible to anyone who may open the section. An unclaimed rack
    is not a secret; it is a rack somebody has not got round to filing, and hiding it would make
    the inventory unusable in exactly the installation that has not finished entering it — which
    is every installation, on day one.
    """
    if allowed is None:
        return True
    org = str(org_uid or '')
    return not org or org in allowed
