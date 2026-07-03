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

from ...constants import BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS


def _build_module_widgets(wa, status_raw: dict, modules_raw: dict, lang: str) -> dict:
    """Generic Overview-widget data: for every module declaring
    ``__overview_widget__``, call its ``Watchful.overview_widget(items, status,
    lang)`` hook and collect the result.  The core stays module-agnostic — all
    domain logic/strings come from the module."""
    out: dict = {}
    try:
        from lib.modules.overview_widgets import overview_widgets_catalog  # noqa: PLC0415
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
    from ..hosts._helpers import _create_unique_host  # noqa: PLC0415
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
        from lib.modules.credential_schemas import credential_schemas  # noqa: PLC0415
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
        """Return a summary snapshot for the overview dashboard."""
        # Current check state (read first so modules can reference per-module counts)
        status_raw: dict = wa._read_check_status()

        def _mod_checks(name: str) -> dict:
            mc = status_raw.get(name, {})
            if not isinstance(mc, dict):
                return {'total': 0, 'ok': 0, 'error': 0, 'warning': 0}
            tot = len(mc)
            ok = sum(1 for v in mc.values() if isinstance(v, dict) and v.get('status') is True)
            warn = sum(1 for v in mc.values() if isinstance(v, dict)
                       and v.get('status') is False and (v.get('severity') or '') == 'warning')
            err = sum(1 for v in mc.values() if isinstance(v, dict)
                      and v.get('status') is False and (v.get('severity') or '') != 'warning')
            return {'total': tot, 'ok': ok, 'error': err, 'warning': warn}

        # Modules summary
        modules_raw = wa._load_modules()
        modules_list = []
        for name, cfg in modules_raw.items():
            if not isinstance(cfg, dict):
                continue
            enabled = cfg.get('enabled', False)
            items_obj = cfg.get('list')
            items_count = len(items_obj) if isinstance(items_obj, dict) else 0
            modules_list.append({
                'name':    name,
                'enabled': bool(enabled),
                'items':   items_count,
                'checks':  _mod_checks(name),
            })

        # Aggregate status counts
        total_checks = sum(m['checks']['total']            for m in modules_list)
        checks_ok    = sum(m['checks']['ok']               for m in modules_list)
        checks_err   = sum(m['checks']['error']            for m in modules_list)
        checks_warn  = sum(m['checks'].get('warning', 0)   for m in modules_list)

        # Sessions summary
        active_sessions = len(wa._sessions)
        _uid_to_name    = {d.get('uid', ''): u for u, d in wa._users.items()}
        session_users   = list({
            _uid_to_name.get(s.get('user_uid', ''), s.get('user_uid', ''))
            for s in wa._sessions.values()
        })
        # Per-session detail for the table widget (admin-only on the frontend).
        sessions_list = []
        for _s in wa._sessions.values():
            if not isinstance(_s, dict):
                continue
            sessions_list.append({
                'user':      _uid_to_name.get(_s.get('user_uid', ''), _s.get('user_uid', '')),
                'ip':        _s.get('ip', ''),
                'agent':     _s.get('user_agent', ''),
                'created':   _s.get('created', ''),
                'last_seen': _s.get('last_seen', ''),
            })
        sessions_list.sort(key=lambda x: str(x.get('last_seen') or ''), reverse=True)
        # Breakdown of active sessions by the role of their user (one count per
        # session, so it tallies with the active-sessions total).
        sessions_by_role: dict[str, int] = {}
        for _s in wa._sessions.values():
            if not isinstance(_s, dict):
                continue
            _uname = _uid_to_name.get(_s.get('user_uid', ''))
            _u = wa._users.get(_uname) if _uname else None
            if not isinstance(_u, dict):
                continue
            _r = _u.get('role', '')
            _r_uid = (wa._role_name_to_uid(_r) if not wa._is_uid(_r) else _r) \
                or BUILTIN_ROLE_UIDS.get('viewer', '')
            if _r_uid:
                sessions_by_role[_r_uid] = sessions_by_role.get(_r_uid, 0) + 1

        # Users summary
        total_users = len(wa._users)
        users_by_role: dict[str, int] = {}
        _viewer_uid = BUILTIN_ROLE_UIDS.get('viewer', '')
        for u in wa._users.values():
            r = u.get('role', '')
            r_uid = (wa._role_name_to_uid(r) if not wa._is_uid(r) else r) or _viewer_uid
            users_by_role[r_uid] = users_by_role.get(r_uid, 0) + 1

        # Groups summary — total, members, and a breakdown of how many groups
        # carry each role (mirrors the users-by-role breakdown). A group may
        # hold several roles, so it counts toward each one it has.
        total_groups = len(wa._groups)
        total_group_members = sum(
            len(g.get('members', [])) for g in wa._groups.values() if isinstance(g, dict)
        )
        groups_by_role: dict[str, int] = {}
        for g in wa._groups.values():
            if not isinstance(g, dict):
                continue
            for r in g.get('roles', []) or []:
                r_uid = (wa._role_name_to_uid(r) if not wa._is_uid(r) else r) or r
                if r_uid:
                    groups_by_role[r_uid] = groups_by_role.get(r_uid, 0) + 1

        # Roles summary
        builtin_roles = len(BUILTIN_ROLE_PERMISSIONS)
        custom_roles = len(wa._custom_roles)

        # uid → display name for every role, so the users/groups/sessions by-role
        # breakdowns resolve names even for a viewer without roles_view (the
        # frontend's rolesData needs roles_view; role names aren't sensitive).
        # role_names → display name; role_keys → builtin key ('admin'/'viewer'/…)
        # so the frontend can colour the badge without roles_view (custom = '').
        role_names: dict[str, str] = {}
        role_keys: dict[str, str] = {}
        for _k in BUILTIN_ROLE_PERMISSIONS:
            _u = BUILTIN_ROLE_UIDS.get(_k, '')
            if not _u:
                continue
            _ov = wa._builtin_role_overrides.get(_u, {})
            role_names[_u] = _ov.get('name') or wa._builtin_role_names.get(_k, _k.title())
            role_keys[_u] = _k
        for _u, _rd in wa._custom_roles.items():
            if isinstance(_rd, dict):
                role_names[_u] = _rd.get('name', _u)
                role_keys[_u] = ''

        # Last audit events
        last_events = list(reversed(wa._audit_log))[:10]

        # Servers (host registry): total + status breakdown + a per-server list
        # (name, status, bound-check count, modules active/total) for the table.
        servers_total = 0
        servers_status = {'ok': 0, 'error': 0, 'warning': 0, 'maintenance': 0}
        servers_list = []
        _host_name: dict = {}     # uid -> display name (reused below)
        _hstore = getattr(wa, '_hosts_store', None)
        if _hstore is not None:
            try:
                from ..hosts import _host_statuses, _host_bound_modules  # noqa: PLC0415
                _hosts = _hstore.list(decrypt=False) or []
                _hstatuses = _host_statuses(wa)
                _hbound = _host_bound_modules(wa)
                # Enabled bound-check tally per host (from the module configuration), with
                # OK/error breakdown pulled from the status file — same shape as
                # the per-module ``checks`` object so the table can reuse it.
                _hchecks: dict = {}
                for _mn, _mc in modules_raw.items():
                    if not isinstance(_mc, dict):
                        continue
                    _mstatus = status_raw.get(_mn, {})
                    if not isinstance(_mstatus, dict):
                        _mstatus = {}
                    for _coll, _items in _mc.items():
                        if _coll.startswith('__') or not isinstance(_items, dict):
                            continue
                        for _ikey, _it in _items.items():
                            if not (isinstance(_it, dict) and _it.get('host_uid')
                                    and _it.get('enabled') is not False):
                                continue
                            _c = _hchecks.setdefault(
                                _it['host_uid'], {'total': 0, 'ok': 0, 'error': 0, 'warning': 0})
                            _c['total'] += 1
                            _sv = _mstatus.get(_ikey)
                            if isinstance(_sv, dict):
                                if _sv.get('status') is True:
                                    _c['ok'] += 1
                                elif _sv.get('status') is False:
                                    if (_sv.get('severity') or '') == 'warning':
                                        _c['warning'] += 1
                                    else:
                                        _c['error'] += 1
                servers_total = len(_hosts)
                for _h in _hosts:
                    _uid = _h.get('uid')
                    _host_name[_uid] = _h.get('name', '')
                    if _h.get('maintenance'):
                        servers_status['maintenance'] += 1
                    else:
                        _st = _hstatuses.get(_uid, '')
                        if _st in servers_status:
                            servers_status[_st] += 1
                    _mods = _hbound.get(_uid, {})
                    _all_m = set(_h.get('modules') or []) | set(_mods)
                    servers_list.append({
                        'uid': _uid, 'name': _h.get('name', ''),
                        'maintenance': bool(_h.get('maintenance')),
                        'status': _hstatuses.get(_uid, ''),
                        'checks': _hchecks.get(_uid, {'total': 0, 'ok': 0, 'error': 0, 'warning': 0}),
                        'modules_total': len(_all_m),
                        'modules_active': sum(1 for _m in _all_m if _mods.get(_m)),
                    })
                servers_list.sort(key=lambda s: str(s.get('name') or '').lower())
            except Exception:  # pylint: disable=broad-except
                pass

        # Active issues: every check currently reporting status False. Display
        # name mirrors the public status page (other_data.name > item label >
        # raw key); host resolved from the bound item's host_uid.
        failing_checks = []
        try:
            for _mn, _mstatus in status_raw.items():
                if not isinstance(_mstatus, dict):
                    continue
                _mcfg = modules_raw.get(_mn)
                _mcfg = _mcfg if isinstance(_mcfg, dict) else {}
                _labels, _hosts_of = {}, {}
                for _coll, _items in _mcfg.items():
                    if _coll.startswith('__') or not isinstance(_items, dict):
                        continue
                    for _k, _it in _items.items():
                        if not isinstance(_it, dict):
                            continue
                        _lbl = str(_it.get('label') or '').strip()
                        if _lbl:
                            _labels[_k] = _lbl
                        if _it.get('host_uid'):
                            _hosts_of[_k] = _it['host_uid']
                for _ck, _info in _mstatus.items():
                    if not (isinstance(_info, dict) and _info.get('status') is False):
                        continue
                    _extra = _info.get('other_data')
                    _extra = _extra if isinstance(_extra, dict) else {}
                    # Composite '<item>/<metric>' keys (e.g. proxmox '<uid>/node/pve04')
                    # resolve the leading item segment to its label and keep the
                    # metric → '<label> / node/pve04', so no opaque UID leaks.
                    _head = _ck.split('/', 1)[0] if '/' in _ck else _ck
                    _disp = _extra.get('name') or _labels.get(_ck)
                    if not _disp and '/' in _ck and _labels.get(_head):
                        _disp = f'{_labels[_head]} / {_ck.split("/", 1)[1]}'
                    _disp = _disp or _ck
                    _huid = _hosts_of.get(_ck) or _hosts_of.get(_head, '')
                    failing_checks.append({
                        'module': _mn,
                        'check':  _disp,
                        'host':   _host_name.get(_huid, '') if _huid else '',
                    })
            failing_checks.sort(
                key=lambda x: (str(x['module']).lower(), str(x['check']).lower()))
        except Exception:  # pylint: disable=broad-except
            pass

        # Recent failed logins (security): last entries from the audit log.
        failed_logins = [
            {'ts': e.get('ts', ''), 'user': e.get('user', ''),
             'ip': e.get('ip', ''), 'detail': e.get('detail', '')}
            for e in reversed(wa._audit_log)
            if isinstance(e, dict) and e.get('event') == 'login_failed'
        ][:15]

        # Webhooks: how many are configured / enabled.
        webhooks_total = webhooks_enabled = 0
        try:
            _wh = wa._load_webhooks()
            if isinstance(_wh, list):
                webhooks_total = len(_wh)
                webhooks_enabled = sum(
                    1 for w in _wh if isinstance(w, dict) and w.get('enabled', True))
        except Exception:  # pylint: disable=broad-except
            pass

        # Reusable credentials: how many are defined, by type / enabled. Only
        # non-sensitive metadata (count + type), never the secret values.
        cred_total = cred_enabled = 0
        cred_by_type: dict = {}
        try:
            _cstore = getattr(wa, '_credentials_store', None)
            if _cstore is not None:
                for _c in (_cstore.list(decrypt=False) or []):
                    if not isinstance(_c, dict):
                        continue
                    cred_total += 1
                    if _c.get('enabled') is not False:
                        cred_enabled += 1
                    _ct = str(_c.get('ctype') or '').strip() or 'ssh'
                    cred_by_type[_ct] = cred_by_type.get(_ct, 0) + 1
        except Exception:  # pylint: disable=broad-except
            pass

        # Monitoring coverage: share of servers with at least one active check.
        hosts_monitored = sum(
            1 for s in servers_list if (s.get('checks') or {}).get('total', 0) > 0)
        coverage_pct = round(100 * hosts_monitored / servers_total) if servers_total else 0

        # Syslog summary — latest messages + total + severity breakdown, only when
        # the user may view it (feeds both the table and counter widgets).
        syslog_recent, syslog_total, syslog_by_sev = [], 0, []
        try:
            if 'syslog_view' in wa._get_session_permissions():
                _sstore = getattr(wa, '_syslog_store', None)
                if _sstore is not None:
                    syslog_recent = _sstore.query(limit=15)
                    _sstats = _sstore.stats(top=1)
                    syslog_total = _sstats.get('total', 0)
                    syslog_by_sev = _sstats.get('by_severity', [])
        except Exception:  # pylint: disable=broad-except
            syslog_recent, syslog_total, syslog_by_sev = [], 0, []

        # Event-notification rules summary — total/enabled + notifications logged,
        # only when the user may view the events feature (feeds the counter widget).
        events_total, events_enabled, events_by_source, notif_total = 0, 0, {}, 0
        try:
            if 'events_view' in wa._get_session_permissions():
                _erstore = getattr(wa, '_event_rules_store', None)
                if _erstore is not None:
                    _rules = _erstore.list()
                    events_total = len(_rules)
                    events_enabled = sum(1 for r in _rules if r.get('enabled'))
                    for r in _rules:
                        _src = r.get('source') or 'audit'
                        events_by_source[_src] = events_by_source.get(_src, 0) + 1
                _nlstore = getattr(wa, '_notification_log_store', None)
                if _nlstore is not None:
                    notif_total = _nlstore.count()
        except Exception:  # pylint: disable=broad-except
            events_total, events_enabled, events_by_source, notif_total = 0, 0, {}, 0

        # Module-contributed Overview widgets: each declaring module computes its
        # OWN data via Watchful.overview_widget(items, status, lang) — nothing
        # module-specific lives in the core.  Result shape: {entries, aggregate}.
        module_widgets = _build_module_widgets(wa, status_raw, modules_raw,
                                               session.get('lang', wa._default_lang))

        return jsonify({
            'modules': modules_list,
            'module_widgets': module_widgets,
            'syslog': {'total': syslog_total, 'recent': syslog_recent,
                       'by_severity': syslog_by_sev},
            'status': {
                'total': total_checks,
                'ok': checks_ok,
                'error': checks_err,
                'warning': checks_warn,
            },
            'servers': {
                'total': servers_total,
                'status': servers_status,
                'list': servers_list,
            },
            'sessions': {
                'active': active_sessions,
                'users': session_users,
                'list': sessions_list,
                'by_role': sessions_by_role,
            },
            'users': {
                'total': total_users,
                'by_role': users_by_role,
            },
            'groups': {
                'total': total_groups,
                'members': total_group_members,
                'by_role': groups_by_role,
            },
            'roles': {
                'total': builtin_roles + custom_roles,
                'builtin': builtin_roles,
                'custom': custom_roles,
            },
            'role_names': role_names,
            'role_keys': role_keys,
            'webhooks': {
                'total': webhooks_total,
                'enabled': webhooks_enabled,
            },
            'events': {
                'total': events_total,
                'enabled': events_enabled,
                'by_source': events_by_source,
                'notifications': notif_total,
            },
            'credentials': {
                'total': cred_total,
                'enabled': cred_enabled,
                'by_type': cred_by_type,
            },
            'coverage': {
                'hosts_total': servers_total,
                'hosts_monitored': hosts_monitored,
                'pct': coverage_pct,
            },
            'failing_checks': failing_checks,
            'failed_logins': failed_logins,
            'last_events': last_events,
        })

    # --- API: org-wide default dashboard layout ------------------
    @app.route('/api/v1/overview/default-layout', methods=['GET'])
    @overview_view_req
    def api_get_default_layout():
        """Org-wide default dashboard layout, applied to users who have not
        customised theirs. Empty ⇒ the frontend falls back to its built-in layout."""
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        return jsonify((cfg.get('overview') or {}).get('default_layout') or [])

    overview_setdef_req = wa._perm_required('overview_set_default')

    @app.route('/api/v1/overview/default-layout', methods=['PUT'])
    @overview_setdef_req
    def api_set_default_layout():
        """Save the posted layout as the org-wide default (config.overview).

        Gated by the dedicated ``overview_set_default`` permission — it changes
        the default for *every* user, beyond editing one's own dashboard."""
        data, err = wa._require_json()
        if err:
            return err
        widgets = data.get('layout')
        if not isinstance(widgets, list):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        layout = [
            {
                'id':     str(w.get('id', '')),
                'cols':   int(w.get('cols') or 2),
                'h':      w.get('h', 'auto'),
                'hidden': bool(w.get('hidden')),
            }
            for w in widgets if isinstance(w, dict) and w.get('id')
        ]
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        cfg.setdefault('overview', {})['default_layout'] = layout
        ok = wa._write_config(cfg)
        wa._audit('overview_default_layout_set', detail={
            'widgets': len(layout),
            'visible': [w['id'] for w in layout if not w.get('hidden')],
        })
        return jsonify({'ok': bool(ok)})

    overview_resetfac_req = wa._perm_required('overview_reset_factory')

    @app.route('/api/v1/overview/reset-factory', methods=['POST'])
    @overview_resetfac_req
    def api_reset_factory_layout():
        """Reset the caller's own dashboard to the factory built-in layout,
        persisted to their account — audited as a permission-gated action."""
        data, err = wa._require_json()
        if err:
            return err
        widgets = data.get('layout')
        layout = [
            {
                'id':     str(w.get('id', '')),
                'cols':   int(w.get('cols') or 2),
                'h':      w.get('h', 'auto'),
                'hidden': bool(w.get('hidden')),
            }
            for w in (widgets if isinstance(widgets, list) else [])
            if isinstance(w, dict) and w.get('id')
        ]
        user = wa._users.get(session.get('username', ''))
        if user is not None:
            user['dashboard_layout'] = layout
            wa._persist_users()
        wa._audit('overview_reset_factory', detail={
            'widgets': len(layout),
            'visible': [w['id'] for w in layout if not w.get('hidden')],
        })
        return jsonify({'ok': True})
