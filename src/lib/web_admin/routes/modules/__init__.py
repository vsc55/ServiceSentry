#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module routes: /api/v1/modules (GET, PUT), /api/v1/modules/status, /api/v1/modules/overview."""

import os
import uuid

from flask import jsonify

from lib import secret_manager

from lib.config import ConfigControl
from ...constants import BUILTIN_ROLE_PERMISSIONS, BUILTIN_ROLE_UIDS


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


def register(app, wa):
    login_required = wa._login_required

    # --- API: modules.json ----------------------------------------

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
        all_data = wa._read_config_file(wa._MODULES_FILE)
        if 'modules_view' in perms:
            return jsonify(secret_manager.mask_sensitive(all_data, wa._secret_keys))
        visible = {n: c for n, c in all_data.items() if f'module.{n}.view' in perms}
        if not visible:
            return jsonify({'error': wa._t('access_denied')}), 403
        return jsonify(secret_manager.mask_sensitive(visible, wa._secret_keys))

    @app.route('/api/v1/modules', methods=['PUT'])
    @login_required
    def api_save_modules():
        """Overwrite ``modules.json`` with the request body.

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
            any(p.startswith('module.') and (p.endswith('.edit') or p.endswith('.add') or p.endswith('.delete'))
                for p in perms) or
            any(p.startswith('server.') and (p.endswith('.add') or p.endswith('.edit'))
                for p in perms)
        )
        if not has_any_write:
            return jsonify({'error': wa._t('access_denied')}), 403
        data, err = wa._require_json()
        if err:
            return err
        if not all(isinstance(v, dict) for v in data.values()):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        old_data = wa._read_config_file(wa._MODULES_FILE)
        # Restore masked secrets BEFORE authorization so an unchanged item with a
        # masked secret is not seen as "modified" (which would over-require edit).
        secret_manager.restore_sensitive(data, old_data, keys=wa._secret_keys)
        if not has_global_edit:
            for name in set(old_data) | set(data):
                if not _authorize_module_write(name, old_data.get(name), data.get(name), perms):
                    return jsonify({'error': wa._t('access_denied')}), 403
        _ensure_item_uids(data)   # generate stable UIDs for new items
        if wa._save_config_file(wa._MODULES_FILE, data):
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._sensitive_fields,
            )
            wa._audit('modules_saved', detail=changes or '')
            return jsonify({'ok': True})
        return jsonify({'error': wa._t('save_file_error')}), 500

    # --- API: status.json (read-only) -----------------------------

    checks_view_req = wa._perm_required('checks_view', 'checks_run')

    @app.route('/api/v1/modules/status', methods=['GET'])
    @checks_view_req
    def api_get_status():
        """Return the contents of ``status.json`` (read-only)."""
        if not wa._var_dir:
            return jsonify({})
        path = os.path.join(wa._var_dir, wa._STATUS_FILE)
        cfg = ConfigControl(path)
        data = cfg.read()
        return jsonify(data if data else {})

    # --- API: overview (dashboard summary) -----------------------

    @app.route('/api/v1/modules/overview', methods=['GET'])
    @login_required
    def api_get_overview():
        """Return a summary snapshot for the overview dashboard."""
        # Status file (read first so modules can reference per-module check counts)
        status_raw: dict = {}
        if wa._var_dir:
            path = os.path.join(wa._var_dir, wa._STATUS_FILE)
            cfg_ctrl = ConfigControl(path)
            status_raw = cfg_ctrl.read() or {}

        def _mod_checks(name: str) -> dict:
            mc = status_raw.get(name, {})
            if not isinstance(mc, dict):
                return {'total': 0, 'ok': 0, 'error': 0}
            tot = len(mc)
            ok  = sum(1 for v in mc.values() if isinstance(v, dict) and v.get('status') is True)
            err = sum(1 for v in mc.values() if isinstance(v, dict) and v.get('status') is False)
            return {'total': tot, 'ok': ok, 'error': err}

        # Modules summary
        modules_raw = wa._read_config_file(wa._MODULES_FILE)
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
        total_checks = sum(m['checks']['total'] for m in modules_list)
        checks_ok    = sum(m['checks']['ok']    for m in modules_list)
        checks_err   = sum(m['checks']['error'] for m in modules_list)

        # Sessions summary
        active_sessions = len(wa._sessions)
        _uid_to_name    = {d.get('uid', ''): u for u, d in wa._users.items()}
        session_users   = list({
            _uid_to_name.get(s.get('user_uid', ''), s.get('user_uid', ''))
            for s in wa._sessions.values()
        })

        # Users summary
        total_users = len(wa._users)
        users_by_role: dict[str, int] = {}
        _viewer_uid = BUILTIN_ROLE_UIDS.get('viewer', '')
        for u in wa._users.values():
            r = u.get('role', '')
            r_uid = (wa._role_name_to_uid(r) if not wa._is_uid(r) else r) or _viewer_uid
            users_by_role[r_uid] = users_by_role.get(r_uid, 0) + 1

        # Groups summary
        total_groups = len(wa._groups)
        total_group_members = sum(
            len(g.get('members', [])) for g in wa._groups.values() if isinstance(g, dict)
        )

        # Roles summary
        builtin_roles = len(BUILTIN_ROLE_PERMISSIONS)
        custom_roles = len(wa._custom_roles)

        # Last audit events
        last_events = list(reversed(wa._audit_log))[:10]

        return jsonify({
            'modules': modules_list,
            'status': {
                'total': total_checks,
                'ok': checks_ok,
                'error': checks_err,
            },
            'sessions': {
                'active': active_sessions,
                'users': session_users,
            },
            'users': {
                'total': total_users,
                'by_role': users_by_role,
            },
            'groups': {
                'total': total_groups,
                'members': total_group_members,
            },
            'roles': {
                'total': builtin_roles + custom_roles,
                'builtin': builtin_roles,
                'custom': custom_roles,
            },
            'last_events': last_events,
        })
