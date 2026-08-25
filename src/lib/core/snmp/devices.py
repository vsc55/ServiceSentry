#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - SNMP: which hosts are devices worth sampling.
#
"""A device to sample is a host that carries an SNMP profile with profiles assigned.

This is the sentence that makes "SNMP is configuration on the device" true rather than
merely tidy. Until now the answer was a list of *module items*: you gave a host its
community and its device profiles, and nothing read them until a second thing — an entry in
the SNMP module pointing back at that host — was also created. The device held the
configuration; the module decided it was worth looking at.

Now the host registry answers it. A host with

  * an ``snmp`` profile, and
  * at least one device profile assigned to it,

is a device, and gets sampled. Nothing else has to exist.

What this deliberately does NOT do:

* **it does not override an explicit "off".** A module item bound to a host covers that host,
  even when disabled. Disabling it is somebody saying "not this one", and quietly resuming
  because the configuration is now stored somewhere else would be the worst kind of upgrade;
* **it does not take the maintenance decision.** The synthetic item is resolved through the
  same ``resolve_host`` a check goes through, which is where maintenance, the address and the
  credential are applied — one place, one behaviour;
* **it does not look at checks.** A device with OID checks and no profiles is a device nobody
  asked to chart, and a device with profiles and no checks is the normal case.

It returns ITEMS, not connections: ``{'host_uid': …}`` and let the resolution that already
exists fill in the rest. Building a connection here would be a second implementation of the
merge, and the two would disagree the first time either changed.
"""

from __future__ import annotations

from lib.core.hosts.resolve import HOST_RESULT_PREFIX, host_result_key

from . import profiles as _profiles

#: Result keys for host-sampled devices. The convention belongs to the host registry, not to
#: SNMP: what it says is "this result is about a host, not about a check", which is what lets
#: the Servers tab attribute it. SNMP is simply the first thing to file results that way.
#: Prefixed, so it can never collide with a module item's uid, and stable across cycles —
#: a device's counter state and its history rows are filed under it.
KEY_PREFIX = HOST_RESULT_PREFIX
device_key = host_result_key


def devices_to_sample(hosts_store, covered=(), only: str = '') -> list[tuple[str, dict]]:
    """``[(key, item)]`` for every host that is an SNMP device and is not already *covered*.

    *covered* is the set of host uids some module item already binds to — those are sampled
    through that item, which may carry settings of its own.

    *only* narrows the answer to ONE host: a collection asked for by hand is about the device
    somebody is looking at, and walking the other six to get its numbers is minutes of other
    people's equipment — and a run that cannot finish because one of them is not answering.
    The module items are narrowed by the same uid, in the module's own config resolution; this
    is the half of the fleet that has no item to narrow.

    Never raises: a registry that cannot be read means no extra devices this cycle, which is
    the same outcome as having none, and is not worth taking a monitoring cycle down for.
    """
    if hosts_store is None:
        return []
    try:
        hosts = hosts_store.list(decrypt=True)
    except Exception:  # pylint: disable=broad-except
        return []

    covered = {str(u).strip() for u in (covered or ()) if str(u).strip()}
    only = str(only or '').strip()
    out: list[tuple[str, dict]] = []
    for host in hosts or ():
        if not isinstance(host, dict):
            continue
        uid = str(host.get('uid') or '').strip()
        if not uid or uid in covered:
            continue
        if only and uid != only:
            continue
        prof = (host.get('profiles') or {}).get('snmp')
        if not isinstance(prof, dict) or not _profiles.assigned(prof):
            continue
        # The label is what a person recognises in a chart legend or an alert; the uid is
        # what keeps it the same device across a rename.
        out.append((device_key(uid), {
            'host_uid': uid,
            'enabled':  True,
            'label':    str(host.get('name') or '').strip(),
        }))
    return out
