#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Credentials kept out of the payload, and the hosts a module declares.

Two halves of the same boundary. On the way OUT, a module's stored credential fields are
stripped so the browser never holds one. On the way IN, a module that declares
``__provision_host__`` gets the host it describes created or updated in the hosts domain —
which is the one thing in this package that WRITES somewhere else, and its store is injected
explicitly so the side effect is in the signature rather than hidden behind ``wa``.
"""

from __future__ import annotations

import json
import os


# ── credential / provisioning helpers ────────────────────────────────────────────
def strip_credential_fields(data: dict, modules_dir: str) -> None:
    """For items that reference a credential (``cred_uid``), drop the module's inline
    credential fields (e.g. web's auth_user/auth_password) so a stale user/secret can't
    linger — the credential supplies them at runtime.  Driven by discovery (per-module
    credential schemas), so it stays module-agnostic."""
    try:
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        cat = credential_schemas(modules_dir)
    except Exception:  # pylint: disable=broad-except
        return
    by_module: dict = {}
    for spec in cat.values():
        mod = spec.get('module')
        if mod and mod != '__core__':
            by_module.setdefault(mod, set()).update(
                f['name'] for f in (spec.get('fields') or []))
    if not by_module:
        return
    for mod_key, mod_cfg in data.items():
        if not isinstance(mod_cfg, dict):
            continue
        fields = by_module.get(mod_key.split('.')[-1])
        if not fields:
            continue
        for coll, items in mod_cfg.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for item in items.values():
                if isinstance(item, dict) and str(item.get('cred_uid') or '').strip():
                    for f in fields:
                        item.pop(f, None)


def provision_host_decl(modules_dir: str, module_name: str) -> dict | None:
    """A module's ``__provision_host__`` declaration, if any (from schema.json).

    Generic, module-agnostic: a module may declare — in a collection's schema —
    that each item provisions a linked host from one of its address fields::

        "__provision_host__": {"address_field": "endpoint", "link_field": "endpoint_host_uid",
                               "name_template": "Endpoint: {label}", "collection": "list"}

    The core reads this by discovery; nothing here is specific to any module."""
    if not modules_dir or not module_name:
        return None
    try:
        path = os.path.join(modules_dir, module_name, 'schema.json')
        with open(path, encoding='utf-8') as fh:
            schema = json.load(fh)
    except (OSError, ValueError):
        return None
    for coll in schema.values():
        if isinstance(coll, dict) and isinstance(coll.get('__provision_host__'), dict):
            decl = dict(coll['__provision_host__'])
            decl.setdefault('collection', 'list')
            return decl
    return None


def sync_provisioned_hosts(hosts_store, modules_dir: str, data: dict, actor: str) -> list:
    """Auto-provision/link a host for every module item that declares one (mutates *data*
    in place).  **Writes** to *hosts_store* (the one persisting function here — the store is
    injected explicitly, not reached through ``wa``).

    Fully generic: driven by each module's ``__provision_host__`` schema declaration
    (see :func:`provision_host_decl`) — the core knows nothing about any specific module.  A
    module declares that its items provision a host from one of their address fields (a
    stable/floating endpoint address); this ensures a linked host (``address == that field``)
    and stamps its uid on the item's ``link_field``, syncing the address when it changes.
    Modelling the endpoint as a host lets any address module (ping/web/ssl_cert…) monitor it
    via the normal host binding.

    Idempotent: an item already linked (``link_field`` set) is reused by uid; an unlinked
    item first tries to ADOPT an existing host with the same deterministic name before
    creating one — so re-saving (before the new link round-trips to the client) never spawns
    duplicate hosts.

    Returns the list of links established this call
    (``[{module, collection, item, field, uid}]``) so the caller can round-trip them to the
    client (which holds no ``link_field`` for a just-created host).  Best-effort: failures are
    swallowed so they never block saving the config."""
    if hosts_store is None or not modules_dir:
        return []
    from lib.core.hosts.service import _create_unique_host  # noqa: PLC0415
    assignments: list = []
    for mod_key, mod_cfg in data.items():
        if not isinstance(mod_cfg, dict):
            continue
        decl = provision_host_decl(modules_dir, str(mod_key).split('.')[-1])
        if not decl:
            continue
        addr_f, link_f = decl.get('address_field'), decl.get('link_field')
        coll = decl.get('collection') or 'list'
        items = mod_cfg.get(coll)
        if not (addr_f and link_f and isinstance(items, dict)):
            continue
        name_tpl = decl.get('name_template') or (str(addr_f) + ': {label}')
        for key, item in items.items():
            if not isinstance(item, dict):
                continue
            addr = str(item.get(addr_f) or '').strip()
            if not addr:
                continue
            uid = str(item.get(link_f) or '').strip()
            try:
                host = hosts_store.get(uid) if uid else None
                if host:
                    if str(host.get('address') or '').strip() != addr:
                        hosts_store.update(uid, {**host, 'address': addr}, actor=actor)
                    continue
                hostname = name_tpl.format(label=item.get('label') or key, key=key)
                # Adopt an existing host with this deterministic name instead of
                # creating a duplicate (idempotent across re-saves / stale clients).
                existing = None
                try:
                    existing = hosts_store.get_by_name(hostname)
                except Exception:  # pylint: disable=broad-except
                    existing = None
                if existing and existing.get('uid'):
                    new_uid = existing['uid']
                    if str(existing.get('address') or '').strip() != addr:
                        hosts_store.update(new_uid, {**existing, 'address': addr}, actor=actor)
                else:
                    new_uid = _create_unique_host(
                        hosts_store, hostname, {'address': addr, 'profiles': {}}, actor)
                if new_uid:
                    item[link_f] = new_uid
                    assignments.append({'module': mod_key, 'collection': coll,
                                        'item': key, 'field': link_f, 'uid': new_uid})
            except Exception:  # pylint: disable=broad-except
                continue
    return assignments
