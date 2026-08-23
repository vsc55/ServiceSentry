#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""May this save touch this item?

The module save is the one write in the panel that crosses domains: a check belongs to a
module, but it is bound to a HOST or a CLUSTER, and the person editing it may hold the
permission for one and not the other. So "who may write here" cannot be answered by the module
flag alone, and answering it wrong is an authorisation bug rather than a bad screen.

Its own module for that reason: a rule about who may write what should be findable by the name
of the file it is in. It was the middle of a 787-line one.

Flask-free: it is given the permission set and the two payloads, and it raises on a violation.
"""

from __future__ import annotations

from lib.core.users.service import AdminOpError

from .items import is_item_collection


def has_any_module_write(perms) -> bool:
    """True if *perms* carry any write capability that could authorize a module save —
    module-level, per-module, or a server/cluster permission that can authorize a
    host-bound check change.  Used to reject a no-write user before parsing the body."""
    return (
        'modules_edit' in perms or 'modules_add' in perms or 'modules_delete' in perms or
        'devices_add' in perms or 'devices_edit' in perms or
        'clusters_add' in perms or 'clusters_edit' in perms or 'clusters_delete' in perms or
        any(p.startswith('module.') and (p.endswith('.edit') or p.endswith('.add') or p.endswith('.delete'))
            for p in perms) or
        any(p.startswith('server.') and (p.endswith('.add') or p.endswith('.edit'))
            for p in perms) or
        any(p.startswith('cluster.') and (p.endswith('.add') or p.endswith('.edit') or p.endswith('.delete'))
            for p in perms)
    )


def _item_host_uid(it) -> str:
    """The host binding of ONE side of an item change (items can be non-dict shorthands).

    Deliberately not :func:`items.item_host_uid`, which answers for the pair and prefers the
    new value: authorising a rebind needs the two bindings apart, not whichever exists.
    """
    return str(it.get('host_uid') or '').strip() if isinstance(it, dict) else ''


def _is_cluster_item(o, n) -> bool:
    """A cluster item is a multi-host-bound check — it carries ``host_uids`` (a
    list), unlike an ordinary single-bound (``host_uid``) or unbound check."""
    for it in (n, o):
        if isinstance(it, dict) and isinstance(it.get('host_uids'), list):
            return True
    return False


def _cluster_authorized(perms, action: str, uid: str = '') -> bool:
    """True if *perms* authorize *action* (add/edit/delete) on a cluster — via the
    global ``clusters_*`` flag or a per-cluster ``cluster.{uid}.{action}`` override."""
    if {'add': 'clusters_add', 'edit': 'clusters_edit',
            'delete': 'clusters_delete'}.get(action) in perms:
        return True
    return bool(uid) and f'cluster.{uid}.{action}' in perms


def _server_authorized(perms, action: str, host_uid: str) -> bool:
    """True if *perms* authorize *action* on server *host_uid* — via the global
    ``servers_*`` flag or a per-server ``server.{uid}.{action}`` override."""
    _g = {'view': 'devices_view', 'add': 'devices_add',
          'edit': 'devices_edit', 'delete': 'devices_delete'}
    if _g.get(action) in perms:
        return True
    return bool(host_uid) and f'server.{host_uid}.{action}' in perms


def authorize_module_write(name: str, old_mod, new_mod, perms) -> bool:
    """Authorize a change to module *name* for a user lacking global module-write.

    Host-bound item changes (items carrying ``host_uid``) may be authorized by
    per-server / global server permissions: adding an item needs server ``add``,
    modifying or removing one needs server ``edit``.  Module-level scalar changes
    and non-host-bound items still require the module permissions.
    """
    if old_mod == new_mod:
        return True
    if f'module.{name}.edit' in perms:
        return True
    is_new = old_mod is None
    is_removed = new_mod is None
    if is_new and 'modules_add' in perms:
        return True
    if is_removed and 'modules_delete' in perms:
        return True

    old_mod = old_mod if isinstance(old_mod, dict) else {}
    new_mod = new_mod if isinstance(new_mod, dict) else {}

    # Module-level (non-collection) scalar changes require module edit — except on
    # a brand-new module being scaffolded purely to hold host-bound items.
    if not is_new:
        old_s = {k: v for k, v in old_mod.items() if not is_item_collection(v)}
        new_s = {k: v for k, v in new_mod.items() if not is_item_collection(v)}
        for k in set(old_s) | set(new_s):
            if old_s.get(k) != new_s.get(k):
                return False

    # Authorize each added/removed/modified item by its host binding.
    coll_names = ({k for k, v in old_mod.items() if is_item_collection(v)}
                  | {k for k, v in new_mod.items() if is_item_collection(v)})
    saw_change = False
    for coll in coll_names:
        old_items = old_mod.get(coll) if is_item_collection(old_mod.get(coll)) else {}
        new_items = new_mod.get(coll) if is_item_collection(new_mod.get(coll)) else {}
        for ik in set(old_items) | set(new_items):
            o, n = old_items.get(ik), new_items.get(ik)
            if o == n:
                continue
            saw_change = True
            if _is_cluster_item(o, n):
                # Multi-bind cluster check → its own clusters_* permissions (or a
                # per-cluster cluster.{uid}.{action} override), with a distinct
                # delete (removal) action.
                c_action = 'add' if o is None else ('delete' if n is None else 'edit')
                cl_uid = ((n or {}).get('uid') if isinstance(n, dict) else None) \
                    or ((o or {}).get('uid') if isinstance(o, dict) else None) or ik
                if not _cluster_authorized(perms, c_action, cl_uid):
                    return False
                continue
            # BOTH bindings, when there are two. A modification that moves a check from
            # one host to another is an edit of the host it is taken FROM as much as of the
            # one it lands on, and authorising only the destination let a `server.<mine>.edit`
            # holder rebind any other host's check onto their own — which takes the check off
            # that host. The permission exists to confine them to their host; this was the
            # one write that reached outside it. (Verified: the same edit made in place is
            # refused, so only the rebind got through.)
            old_hu, new_hu = _item_host_uid(o), _item_host_uid(n)
            if o is None:
                if not _server_authorized(perms, 'add', new_hu):
                    return False
            elif n is None:
                if not _server_authorized(perms, 'edit', old_hu):
                    return False
            else:
                if not _server_authorized(perms, 'edit', old_hu):
                    return False
                if new_hu != old_hu and not _server_authorized(perms, 'edit', new_hu):
                    return False
    # A change with no authorizable host-bound item diff (whole-module add/remove
    # with no host-bound items, or only scalar churn) is not server-authorizable.
    return saw_change


def authorize_modules_save(old_data: dict, data: dict, perms) -> None:
    """Authorize every changed module individually (for a user without global
    ``modules_edit``). Raises :class:`AdminOpError` (``access_denied``) on the first
    unauthorized change."""
    for name in set(old_data) | set(data):
        if not authorize_module_write(name, old_data.get(name), data.get(name), perms):
            raise AdminOpError('access_denied')
