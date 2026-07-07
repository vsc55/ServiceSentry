#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module routes: /api/v1/modules (GET, PUT), /api/v1/modules/status, /api/v1/modules/overview."""

import importlib
import json
import os
import re
import sys
import uuid

from flask import jsonify, session

from lib.security import secret_manager

from lib.core.permissions import BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS


def _build_module_widgets(wa, status_raw: dict, modules_raw: dict, lang: str) -> dict:
    """Generic Overview-widget data: for every module declaring
    ``__overview_widget__``, call its ``Watchful.overview_widget(items, status,
    lang)`` hook and collect the result.  The core stays module-agnostic — all
    domain logic/strings come from the module."""
    out: dict = {}
    try:
        from lib.modules.discovery.overview_widgets import overview_widgets_catalog  # noqa: PLC0415
        catalog = overview_widgets_catalog(wa._modules_dir)
    except Exception:  # pylint: disable=broad-except
        return out
    if not catalog:
        return out
    parent = os.path.dirname(wa._modules_dir or '')
    if parent and parent not in sys.path:
        sys.path.insert(0, parent)
    for mod_name in catalog:
        try:
            status = next((status_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                           if isinstance(status_raw.get(k), dict)), {})
            cfg = next((modules_raw[k] for k in (f'watchfuls.{mod_name}', mod_name)
                        if isinstance(modules_raw.get(k), dict)), {})
            items = cfg.get('list') if isinstance(cfg.get('list'), dict) else {}
            cls = getattr(importlib.import_module(f'watchfuls.{mod_name}'), 'Watchful', None)
            fn = getattr(cls, 'overview_widget', None)
            if callable(fn):
                out[mod_name] = fn(items, status, lang) or {}
        except Exception:  # pylint: disable=broad-except
            continue
    return out

# Canonical UUID form, used to tell an opaque item key from a human-given one.
_UUID_RE = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def _is_item_collection(v) -> bool:
    """A module section holding items (``list``/``servers``/…) is dict-valued;
    module-level fields (enabled, threads, timeout, …) are scalars (bool/int),
    never dicts.  Items inside may be dicts or a bool shorthand
    (``"1.2.3.4": false`` = disabled), so the value *type* of items is not used
    to classify the section — only the section being a dict matters."""
    return isinstance(v, dict)


def _item_host_uid(o, n) -> str:
    """Host UID of an item from its new or old value (items can be non-dict
    bool shorthands, which carry no host binding)."""
    for it in (n, o):
        if isinstance(it, dict):
            hu = str(it.get('host_uid') or '').strip()
            if hu:
                return hu
    return ''


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
    _g = {'view': 'servers_view', 'add': 'servers_add',
          'edit': 'servers_edit', 'delete': 'servers_delete'}
    if _g.get(action) in perms:
        return True
    return bool(host_uid) and f'server.{host_uid}.{action}' in perms


def _authorize_module_write(name: str, old_mod, new_mod, perms) -> bool:
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
        old_s = {k: v for k, v in old_mod.items() if not _is_item_collection(v)}
        new_s = {k: v for k, v in new_mod.items() if not _is_item_collection(v)}
        for k in set(old_s) | set(new_s):
            if old_s.get(k) != new_s.get(k):
                return False

    # Authorize each added/removed/modified item by its host binding.
    coll_names = {k for k, v in old_mod.items() if _is_item_collection(v)} \
               | {k for k, v in new_mod.items() if _is_item_collection(v)}
    saw_change = False
    for coll in coll_names:
        old_items = old_mod.get(coll) if _is_item_collection(old_mod.get(coll)) else {}
        new_items = new_mod.get(coll) if _is_item_collection(new_mod.get(coll)) else {}
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
            hu = _item_host_uid(o, n)
            action = 'add' if o is None else 'edit'        # add new / modify|remove
            if not _server_authorized(perms, action, hu):
                return False
    # A change with no authorizable host-bound item diff (whole-module add/remove
    # with no host-bound items, or only scalar churn) is not server-authorizable.
    return saw_change


def _ensure_item_uids(data: dict) -> None:
    """Add a stable UUID to every module item that lacks one.

    Items live inside dict-valued sections of each module config (typically
    called ``list`` or ``servers``).  A UUID is generated only when absent so
    existing UIDs are never overwritten.
    """
    for module_cfg in data.values():
        if not isinstance(module_cfg, dict):
            continue
        for section_val in module_cfg.values():
            if not isinstance(section_val, dict):
                continue
            for item in section_val.values():
                if isinstance(item, dict) and 'uid' not in item:
                    item['uid'] = str(uuid.uuid4())


# Collections that hold check items, keyed by the item UID. Nested collections
# (e.g. snmp's per-server ``checks``) are re-keyed recursively.
_ITEM_COLLECTIONS = ('list', 'servers')
_NESTED_ITEM_COLLECTIONS = ('checks',)


def _rekey_collection(coll: dict) -> dict:
    """Return *coll* re-keyed so each item's dict key equals its ``uid``
    (generated when absent); recurses into nested item collections."""
    out: dict = {}
    for old_key, item in coll.items():
        if not isinstance(item, dict):
            out[old_key] = item
            continue
        uid = str(item.get('uid') or '').strip() or str(uuid.uuid4())
        item['uid'] = uid
        # Preserve a human-readable old key as the editable label, so re-keying
        # to an opaque UID never loses the name (e.g. ups items keyed by name).
        if (not str(item.get('label') or '').strip()
                and old_key != uid and not _UUID_RE.match(str(old_key))):
            item['label'] = old_key
        for sub in _NESTED_ITEM_COLLECTIONS:
            sub_val = item.get(sub)
            if isinstance(sub_val, dict) and sub_val:
                item[sub] = _rekey_collection(sub_val)
        out[uid] = item
    return out


def _rekey_items_by_uid(data: dict) -> None:
    """Re-key every check item (and nested check) by its ``uid`` in place.

    Makes the item's dict key equal its UID so each watchful's result key (the
    dict key it iterates) is the stable UID — the canonical relation used by
    status.json / check_state / history.
    """
    for module_cfg in data.values():
        if not isinstance(module_cfg, dict):
            continue
        for coll_name in _ITEM_COLLECTIONS:
            coll = module_cfg.get(coll_name)
            if isinstance(coll, dict) and coll:
                module_cfg[coll_name] = _rekey_collection(coll)


def _provision_host_decl(modules_dir, module_name: str) -> dict | None:
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


def _sync_provisioned_hosts(wa, data: dict, actor: str) -> list:
    """Auto-provision/link a host for every item that declares one (in place).

    Fully generic: driven by each module's ``__provision_host__`` schema
    declaration (see :func:`_provision_host_decl`) — the core knows nothing about
    any specific module.  A module declares that its items provision a host from
    one of their address fields (a stable/floating endpoint address); this
    ensures a linked host (``address == that field``) and stamps its uid on the
    item's ``link_field``, syncing the address when it changes.  Modelling the
    endpoint as a host lets any address module (ping/web/ssl_cert…) monitor it via
    the normal host binding.

    Idempotent: an item already linked (``link_field`` set) is reused by uid; an
    unlinked item first tries to ADOPT an existing host with the same deterministic
    name before creating one — so re-saving (before the new link round-trips to the
    client) never spawns duplicate hosts.

    Returns the list of links established this call
    (``[{module, collection, item, field, uid}]``) so the caller can round-trip
    them to the client (which holds no ``link_field`` for a just-created host).

    Runs server-side with system rights, so a user who may edit the item but not
    servers can still provision it.  Best-effort: failures are swallowed so they
    never block saving the config.
    """
    store = getattr(wa, '_hosts_store', None)
    modules_dir = getattr(wa, '_modules_dir', None)
    if store is None or not modules_dir:
        return []
    from ..hosts.routes._helpers import _create_unique_host  # noqa: PLC0415
    assignments: list = []
    for mod_key, mod_cfg in data.items():
        if not isinstance(mod_cfg, dict):
            continue
        decl = _provision_host_decl(modules_dir, str(mod_key).split('.')[-1])
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
                host = store.get(uid) if uid else None
                if host:
                    if str(host.get('address') or '').strip() != addr:
                        store.update(uid, {**host, 'address': addr}, actor=actor)
                    continue
                hostname = name_tpl.format(label=item.get('label') or key, key=key)
                # Adopt an existing host with this deterministic name instead of
                # creating a duplicate (idempotent across re-saves / stale clients).
                existing = None
                try:
                    existing = store.get_by_name(hostname)
                except Exception:  # pylint: disable=broad-except
                    existing = None
                if existing and existing.get('uid'):
                    new_uid = existing['uid']
                    if str(existing.get('address') or '').strip() != addr:
                        store.update(new_uid, {**existing, 'address': addr}, actor=actor)
                else:
                    new_uid = _create_unique_host(
                        store, hostname, {'address': addr, 'profiles': {}}, actor)
                if new_uid:
                    item[link_f] = new_uid
                    assignments.append({'module': mod_key, 'collection': coll,
                                        'item': key, 'field': link_f, 'uid': new_uid})
            except Exception:  # pylint: disable=broad-except
                continue
    return assignments


def _strip_credential_fields(wa, data):
    """For items that reference a credential (``cred_uid``), drop the module's
    inline credential fields (e.g. web's auth_user/auth_password) so a stale
    user/secret can't linger — the credential supplies them at runtime."""
    try:
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        cat = credential_schemas(wa._modules_dir)
    except Exception:  # pylint: disable=broad-except
        return
    by_module = {}
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


def register(app, wa):
    login_required = wa._login_required

    # --- API: module configuration --------------------------------

    @app.route('/api/v1/modules', methods=['GET'])
    @login_required
    def api_get_modules():
        """Return modules the current user may view.

        Users with ``modules_view`` receive the full dataset.
        Users without it receive only modules for which they hold a
        ``module.{name}.view`` per-module permission.  Returns 403 when
        no modules are accessible at all.
        """
        perms = wa._get_session_permissions()
        all_data = wa._load_modules()
        if 'modules_view' in perms:
            return jsonify(secret_manager.mask_sensitive(all_data, wa._secret_keys))
        visible = {n: c for n, c in all_data.items() if f'module.{n}.view' in perms}
        if not visible:
            return jsonify({'error': wa._t('access_denied')}), 403
        return jsonify(secret_manager.mask_sensitive(visible, wa._secret_keys))

    @app.route('/api/v1/modules', methods=['PUT'])
    @login_required
    def api_save_modules():
        """Overwrite the module configuration with the request body.

        Users with ``modules_edit`` may save any change.  Without it, each
        modified module is authorized individually: a ``module.{name}.edit``
        grants the whole module, while host-bound item changes can be authorized
        by per-server / global server permissions (server ``add`` to add a check,
        ``edit`` to modify/remove one).  New whole modules still need
        ``modules_add``; whole-module removal needs ``modules_delete``.
        """
        perms = wa._get_session_permissions()
        has_global_edit = 'modules_edit' in perms
        # Reject immediately when the user has no write permission of any kind
        # (module-level, per-module, or any server permission that can authorize
        # host-bound check changes).
        has_any_write = (
            'modules_edit' in perms or 'modules_add' in perms or 'modules_delete' in perms or
            'servers_add' in perms or 'servers_edit' in perms or
            'clusters_add' in perms or 'clusters_edit' in perms or 'clusters_delete' in perms or
            any(p.startswith('module.') and (p.endswith('.edit') or p.endswith('.add') or p.endswith('.delete'))
                for p in perms) or
            any(p.startswith('server.') and (p.endswith('.add') or p.endswith('.edit'))
                for p in perms) or
            any(p.startswith('cluster.') and (p.endswith('.add') or p.endswith('.edit') or p.endswith('.delete'))
                for p in perms)
        )
        if not has_any_write:
            return jsonify({'error': wa._t('access_denied')}), 403
        data, err = wa._require_json()
        if err:
            return err
        if not all(isinstance(v, dict) for v in data.values()):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        old_data = wa._load_modules()
        # Restore masked secrets BEFORE authorization so an unchanged item with a
        # masked secret is not seen as "modified" (which would over-require edit).
        secret_manager.restore_sensitive(data, old_data, keys=wa._secret_keys)
        # Items bound to a credential keep no inline user/secret (cleared after
        # the restore above so a stale value can't be persisted/restored).
        _strip_credential_fields(wa, data)
        if not has_global_edit:
            for name in set(old_data) | set(data):
                if not _authorize_module_write(name, old_data.get(name), data.get(name), perms):
                    return jsonify({'error': wa._t('access_denied')}), 403
        _ensure_item_uids(data)     # generate stable UIDs for new items
        _rekey_items_by_uid(data)   # keep each item's dict key == its UID
        # Generic: provision/link a host for any item that declares one
        # (__provision_host__ in its schema) — so address modules (ping/web/
        # ssl_cert) can monitor that endpoint. Module-agnostic (discovery-driven).
        provisioned = _sync_provisioned_hosts(wa, data, session.get('username', 'system'))
        if wa._save_modules(data):
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._sensitive_fields,
            )
            wa._audit('modules_saved', detail=changes or '')
            # Round-trip any new host links so the client persists them (a later
            # save in this session then reuses the host instead of re-creating it).
            return jsonify({'ok': True, 'provisioned': provisioned})
        return jsonify({'error': wa._t('save_file_error')}), 500

    # --- API: check state (read-only) -----------------------------

    checks_view_req = wa._perm_required('checks_view', 'checks_run')

    @app.route('/api/v1/modules/status', methods=['GET'])
    @checks_view_req
    def api_get_status():
        """Return the current check state (from the check_state DB table)."""
        return jsonify(wa._read_check_status())

    checks_run_req = wa._perm_required('checks_run')

    @app.route('/api/v1/modules/status', methods=['DELETE'])
    @checks_run_req
    def api_clear_status():
        """Empty the current check-state table so monitoring starts clean."""
        store = getattr(wa, '_check_state_store', None)
        ok = bool(store and store.clear())
        wa._audit('status_cleared', detail={'ok': ok})
        return jsonify({'ok': ok})

    # --- API: overview (dashboard summary) -----------------------

    overview_view_req = wa._perm_required('overview_view')

    @app.route('/api/v1/modules/overview', methods=['GET'])
    @overview_view_req
    def api_get_overview():
        """Slim shared snapshot for the Overview dashboard.

        Every built-in card/table now fetches its own data over AJAX from
        ``/api/v1/overview/widget/<id>`` (its ``stat`` / ``rows`` provider), so this
        endpoint no longer aggregates per-widget content.  It returns only what is truly
        shared across the dashboard:

        * ``module_widgets`` — the watchful-module-contributed Overview widgets, each
          computing its own data via ``Watchful.overview_widget``; and
        * ``role_names`` / ``role_keys`` — shared role metadata so the users/groups/
          sessions by-role badges resolve names regardless of ``roles_view``.
        """
        status_raw = wa._read_check_status()
        modules_raw = wa._load_modules()
        module_widgets = _build_module_widgets(wa, status_raw, modules_raw,
                                               session.get('lang', wa._default_lang))
        from lib.core.roles.overview_widget import role_meta  # noqa: PLC0415
        _resp = {'module_widgets': module_widgets}
        _resp.update(role_meta(wa))
        return jsonify(_resp)

    # NOTE: the overview *layout* endpoints (/api/v1/overview/default-layout,
    # /reset-factory) moved to lib.core.overview.routes — this modules register keeps
    # only /api/v1/modules/overview (the slim shared snapshot, above).
