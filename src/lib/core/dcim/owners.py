#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whose is this, and therefore who may see it.

Two functions and one idea. Ownership is **said** at whatever level somebody knows it and
**inherited** downwards, innermost wins; so the effective owner of anything is found by walking
up the containment chain until the first thing that was said. Nothing derived is ever stored:
the day somebody re-parents a rack, a stored copy of what it used to inherit is a lie that
outlives the move.

The second half is the one with teeth. **A shared rack breaks the assumption that seeing a place
means seeing what is in it.** A holding's IT department shares a cabinet between the group's
companies; somebody from company B must see the rack, must see that U 12 is taken — otherwise
planning is impossible — and must not see whose it is or what it is called.

So a read of this domain has three outcomes per thing, not two:

* **visible** — theirs, or they hold the whole fleet;
* **opaque** — somebody else's: it EXISTS, it OCCUPIES, and that is all it says;
* **absent** — nothing, for the things that carry no useful shape.

Opaque is the one that matters and the one that is easy to get wrong in the direction of a leak.
Three rules, written here rather than in each screen:

1. An opaque item has no name, no model, no serial, no host and **no state**. What it keeps is
   its position and its size, because "U 12 to 13 are taken" is the fact that makes the cabinet
   plannable and says nothing about whose they are.
2. **Counts follow visibility.** A rack reporting "3 devices down" of which none are yours is an
   enumeration of somebody else's fleet through the back door — the same shape as the IDOR
   audit of 2026-05. What is counted is what can be seen.
3. **Free space is everybody's.** "6U free" reveals nothing about anybody and is half the reason
   this exists at all.
"""

from __future__ import annotations

#: The permission that grants every company at once. Named `_view` and not `_all` because
#: `viewer` being read-only is a NAMING invariant here — every flag that role holds ends in
#: `_view`, which is what makes "is this role read-only" answerable by looking rather than by
#: reading six manifests (tests/unit/test_wa_roles.py).
ALL_ORGS_PERM = 'dcim_all_view'

#: The per-company scope, minted the way `server.<uid>.view` is minted per device.
ORG_SCOPE = 'org.%s.view'


def owner_of(chain, said) -> str:
    """The company something belongs to, or ``''`` if nobody ever said.

    *chain* is ``[(scope, uid), …]`` innermost first — :meth:`DcimStore.chain_of` — and *said*
    is the map of declared ownerships (:meth:`DcimStore.owners_map`). Passing both in rather
    than reaching for a store is what lets a screen resolve four hundred items off two reads.
    """
    for scope, uid in chain or ():
        org = said.get((scope, uid))
        if org:
            return str(org)
    return ''


def visible_orgs(perms) -> set | None:
    """The companies a caller may see, or ``None`` for "all of them".

    ``None`` and ``set()`` are deliberately different answers: the first is a panel operator who
    holds the fleet, the second is somebody who has been granted the section and no company at
    all — who should see rooms and racks with every item opaque, rather than an error. A screen
    that treats "no companies" as "no access" locks out exactly the person the scope was
    invented for.
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
