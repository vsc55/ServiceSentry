#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assisted migration from inline per-module connections to shared hosts.

Scans the module configuration for items (snmp servers, ping/datastore/… list
entries)
whose connection is declared inline, groups the ones that point at the same
server, and proposes a single Host per group — so the same connection +
credentials defined N times across modules collapses into one reusable host.

Two functions, both pure (no I/O), so they're easy to test:

* :func:`build_migration_plan` → a reviewable proposal (candidate hosts +
  their member items).  Grouping is *safe*: items merge into a candidate only
  when they share an address AND don't disagree on any shared protocol's
  credentials, so a candidate never has ambiguous credentials.  Profiles from
  different protocols on the same address are aggregated (e.g. an SNMP server +
  a ping target + a DB on one host → one host with snmp/db profiles).

* :func:`apply_to_modules` → given the candidates the user accepted (each with a
  freshly created host uid), rewrite the member items: set ``host_uid`` and drop
  the now-host-owned connection fields, keeping the check-specific fields.

The route layer turns a plan into hosts (via HostsStore) and persists the
rewritten module configuration.
"""

from __future__ import annotations

import hashlib

from lib.hosts.profiles import module_host_fields, module_host_specs

_EMPTY = (None, '', False)


def _bare(module_key: str) -> str:
    """'watchfuls.snmp' → 'snmp' (module config keys may carry the package prefix)."""
    return module_key.split('.')[-1]


def _specs_by_module(watchfuls_dir):
    """{bare_module: [(protocol, address_field, [field names])]} from each
    module's own ``__host_profile__`` (so datastore's ssh tunnel is preserved)."""
    return module_host_specs(watchfuls_dir)


def _connection_collection(mod_cfg: dict, conn_fields: set) -> str | None:
    """The module's section whose items hold the connection fields (e.g. snmp
    'servers', ping 'list')."""
    for sname, sval in mod_cfg.items():
        if sname.startswith('__') or not isinstance(sval, dict):
            continue
        if any(isinstance(it, dict) and (conn_fields & set(it)) for it in sval.values()):
            return sname
    return None


def _item_profiles(item: dict, specs: list) -> tuple[str, dict]:
    """Return (address, {protocol: {field: value}}) for one item.

    The address comes from the first spec that defines an ``address_field``;
    each protocol's profile excludes that address field (the host owns it) and
    drops empty values.  Protocols with no remaining fields yield ``{}``.
    """
    address = ''
    profiles: dict = {}
    for proto, addr_f, fields in specs:
        if addr_f and not address and item.get(addr_f) not in _EMPTY:
            address = str(item[addr_f]).strip()
        prof = {f: item[f] for f in fields
                if f != addr_f and f in item and item.get(f) not in _EMPTY}
        profiles[proto] = prof
    return address, profiles


def _compatible(existing: dict, new: dict) -> bool:
    """True if two protocol→creds maps don't disagree on any shared protocol
    that both populate with non-empty credentials."""
    for proto, prof in new.items():
        if not prof:
            continue
        cur = existing.get(proto)
        if cur and cur != prof:
            return False
    return True


def _merge_profiles(into: dict, new: dict) -> None:
    for proto, prof in new.items():
        if prof and not into.get(proto):
            into[proto] = dict(prof)


def build_migration_plan(modules_data: dict, watchfuls_dir: str | None = None) -> dict:
    """Return ``{'candidates': [...], 'total_items': N}``.

    Each candidate: ``{address, suggested_name, profiles, protocols, members,
    modules, is_duplicate}``.  ``members`` are ``{module, collection, key}``
    references into the module configuration.  ``is_duplicate`` is True when the candidate
    groups more than one item (the dedup wins).
    """
    by_mod = _specs_by_module(watchfuls_dir)
    candidates: list = []
    total_items = 0

    for mod_key, mod_cfg in (modules_data or {}).items():
        specs = by_mod.get(_bare(mod_key))
        if not specs or not isinstance(mod_cfg, dict):
            continue
        conn_fields = {f for _, _, fields in specs for f in fields}
        coll = _connection_collection(mod_cfg, conn_fields)
        if not coll:
            continue
        for ikey, item in mod_cfg[coll].items():
            if not isinstance(item, dict) or item.get('host_uid'):
                continue  # already bound or not an item
            address, profiles = _item_profiles(item, specs)
            if not address:
                continue  # nothing to key on
            total_items += 1
            member = {'module': mod_key, 'collection': coll, 'key': ikey}
            # Greedily place into a compatible same-address candidate.
            placed = False
            for cand in candidates:
                if cand['_addr_key'] == address.lower() and _compatible(cand['profiles'], profiles):
                    _merge_profiles(cand['profiles'], profiles)
                    cand['members'].append(member)
                    placed = True
                    break
            if not placed:
                candidates.append({
                    '_addr_key':      address.lower(),
                    'address':        address,
                    'suggested_name': ikey,
                    'profiles':       {p: dict(v) for p, v in profiles.items() if v},
                    'members':        [member],
                })

    out = []
    for c in candidates:
        modules = sorted({_bare(m['module']) for m in c['members']})
        # Stable id from the member set so the apply step can match a candidate
        # even though grouping is order-dependent (no reliance on list index).
        sig = ';'.join(sorted(f"{m['module']}|{m['collection']}|{m['key']}" for m in c['members']))
        cid = hashlib.sha1(sig.encode()).hexdigest()[:12]
        out.append({
            'id':             cid,
            'address':        c['address'],
            'suggested_name': c['suggested_name'],
            'profiles':       c['profiles'],
            'protocols':      sorted(c['profiles'].keys()),
            'members':        c['members'],
            'modules':        modules,
            'is_duplicate':   len(c['members']) > 1,
        })
    # Duplicates first, then by address.
    out.sort(key=lambda c: (not c['is_duplicate'], c['address'].lower()))
    return {'candidates': out, 'total_items': total_items}


def apply_to_modules(modules_data: dict, applied: list,
                     watchfuls_dir: str | None = None) -> dict:
    """Rewrite *modules_data* in place for accepted candidates.

    *applied* = ``[{'uid': <host uid>, 'members': [{module, collection, key}]}]``.
    For each member item: set ``host_uid`` and remove the connection fields the
    host now owns (per the module's ``__host_profile__``), keeping check fields,
    ``enabled``, ``uid`` and any sub-collections (e.g. SNMP ``checks``).
    Returns the same dict for convenience.
    """
    host_fields = module_host_fields(watchfuls_dir)
    for entry in applied or []:
        uid = entry.get('uid')
        if not uid:
            continue
        for m in entry.get('members', []):
            mod_cfg = modules_data.get(m['module'])
            if not isinstance(mod_cfg, dict):
                continue
            coll = mod_cfg.get(m['collection'])
            if not isinstance(coll, dict):
                continue
            item = coll.get(m['key'])
            if not isinstance(item, dict):
                continue
            for f in host_fields.get(_bare(m['module']), []):
                item.pop(f, None)
            item['host_uid'] = uid
    return modules_data
