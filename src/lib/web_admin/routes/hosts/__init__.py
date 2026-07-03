#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host registry CRUD routes: /api/v1/hosts (GET, POST), /api/v1/hosts/<uid> (PUT, DELETE).

A host carries an address plus per-protocol connection profiles (ssh, snmp, db,
http...) that watchful modules reuse, so a server connection is defined once.
Secret values inside profiles are masked on read and restored on write.

The test endpoints live in tests.py, the assisted migration in migrate.py and the
shared helpers in _helpers.py.
"""

import copy
import json
import os
import re
import uuid

from flask import jsonify, request, session

from lib.security import secret_manager

from . import tests, migrate
from ._helpers import (
    SYSTEM_USER, _MOD_RE, _HOST_EDIT_FIELDS,
    _coll_meta, _format_item_label, _delete_host_checks, _clone_host_checks,
    _only_modules_growth, _bare, _probe_host_record, _restore_check_secrets,
    _apply_check_cred, _checks_for_host, _host_statuses, _host_bound_modules,
    _create_unique_host,
)


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_hosts_store', None)

    @app.route('/api/v1/hosts', methods=['GET'])
    @login_required
    def api_get_hosts():
        """List hosts the current user may view (secrets masked).

        Users with the global ``servers_view`` see every host; otherwise only
        hosts for which they hold a ``server.{uid}.view`` per-server permission.
        """
        perms = wa._get_session_permissions()
        has_global_view = 'servers_view' in perms
        has_any_view = has_global_view or any(
            p.startswith('server.') and p.endswith('.view') for p in perms)
        if not has_any_view:
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'hosts': []})
        hosts = secret_manager.mask_sensitive(store.list(decrypt=True), wa._secret_keys)
        if not has_global_view:
            hosts = [h for h in hosts if f"server.{h.get('uid')}.view" in perms]
        statuses = _host_statuses(wa)
        bound = _host_bound_modules(wa)
        for h in hosts:
            uid = h.get('uid')
            h['status'] = statuses.get(uid, '')
            mods = bound.get(uid, {})
            # Total = modules the host carries (its saved list ∪ any with a bound
            # check); active = those with at least one enabled check.
            total = set(h.get('modules') or []) | set(mods)
            h['modules_total'] = len(total)
            h['modules_active'] = sum(1 for m in total if mods.get(m))
        return jsonify({'hosts': hosts})

    @app.route('/api/v1/hosts/<uid>/status', methods=['GET'])
    @login_required
    def api_host_status(uid):
        """Latest recorded results (from the daemon's status.json) for every
        check bound to this host — shown in the server modal's "Latest data" tab.

        Each entry: ``{module, key, name, ok, message, data, ts}``.  Derived keys
        (e.g. ram_swap ``<uid>_ram``) are matched to their base bound item.
        """
        if not wa._has_server_permission(uid, 'view'):
            return jsonify({'error': wa._t('access_denied')}), 403
        # Bound items per bare module: {bare: {item_key: label}}.
        bound: dict = {}
        for (bare, _coll), items in _checks_for_host(wa, uid).items():
            for k, item in items.items():
                bound.setdefault(bare, {})[k] = str((item or {}).get('label') or '').strip()
        # Current live state (from the check_state DB table).
        status_raw = wa._read_check_status()
        # Index the history once, grouped by bare module, for the fallback when a
        # check has no live status (e.g. the host is in maintenance, so its live
        # records were purged).
        hist_by_mod: dict = {}
        hist_store = getattr(wa, '_history', None)
        if hist_store is not None:
            try:
                for s in hist_store.get_index():
                    hist_by_mod.setdefault(s.get('module'), []).append(s)
            except Exception:  # pylint: disable=broad-except
                pass

        def _matches(skey, keys):
            """Map a (possibly derived) result key to its bound base item key."""
            base = skey if skey in keys else skey.rsplit('_', 1)[0]
            return base if base in keys else None

        results = []
        for bare, keys in bound.items():
            covered = set()
            # 1) Live values from status.json.
            mod_status = status_raw.get(bare)
            if not isinstance(mod_status, dict):
                mod_status = status_raw.get(f'watchfuls.{bare}')
            if isinstance(mod_status, dict):
                for skey, info in mod_status.items():
                    if not isinstance(info, dict):
                        continue
                    base = _matches(skey, keys)
                    if base is None:
                        continue
                    data = info.get('other_data') if isinstance(info.get('other_data'), dict) else {}
                    name = str(data.get('name') or '').strip() or keys.get(base) or skey
                    ok = info.get('status') is True
                    sev = (info.get('severity') or '').lower()
                    results.append({
                        'module': bare, 'key': skey, 'name': name,
                        'ok': ok,
                        'level': 'ok' if ok else ('warning' if sev == 'warning' else 'error'),
                        'message': info.get('message', ''),
                        'data': data, 'ts': info.get('ts', ''),
                        'source': 'live',
                    })
                    covered.add(skey)
            # 2) History fallback for series with no live value.
            for s in hist_by_mod.get(bare, []):
                skey = s.get('key')
                if skey in covered:
                    continue
                base = _matches(skey, keys)
                if base is None:
                    continue
                data = s.get('last_data') if isinstance(s.get('last_data'), dict) else {}
                name = str(data.get('name') or '').strip() or keys.get(base) or skey
                _ok = s.get('last_status') is True
                results.append({
                    'module': bare, 'key': skey, 'name': name,
                    'ok': _ok,
                    'level': 'ok' if _ok else 'error',   # history keeps no severity
                    'message': data.get('message', '') if isinstance(data, dict) else '',
                    'data': data, 'ts': s.get('last_ts', ''),
                    'source': 'history',
                })
                covered.add(skey)
        results.sort(key=lambda r: (r['module'], r['name']))
        return jsonify({'results': results})

    @app.route('/api/v1/hosts', methods=['POST'])
    @login_required
    def api_create_host():
        """Create a host."""
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        data, err = wa._require_json()
        if err:
            return err
        if not str(data.get('name') or '').strip():
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        uid = store.create(data, actor=session.get('username', SYSTEM_USER))
        if not uid:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        wa._audit('host_created', detail={
            'uid': uid, 'name': data.get('name'),
            'address': data.get('address', ''),
            'kind': data.get('kind', 'local'),
            'os': data.get('os', 'auto'),
            'maintenance': bool(data.get('maintenance')),
            'profiles': sorted((data.get('profiles') or {}).keys()),
        })
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/hosts/<uid>/clone', methods=['POST'])
    @login_required
    def api_clone_host(uid):
        """Clone a host: duplicate the stored host (all profiles + secrets) under a
        NEW uid, overriding name/address from the request.  The source is read
        DECRYPTED and re-created, so inline profile secrets (ssh_password,
        ssh_key_string…) are preserved (and re-encrypted) instead of being lost as
        they would in a client-side copy of the masked data."""
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        src = store.get(uid, decrypt=True)
        if src is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        body, err = wa._require_json()
        if err:
            return err
        data = copy.deepcopy(src)              # deep copy: we mutate nested profiles
        data.pop('uid', None)
        data['name'] = str((body or {}).get('name') or '').strip() \
            or f"{src.get('name', '')} (copia)"
        if 'address' in (body or {}):
            data['address'] = str(body.get('address') or '').strip()
        # A clone is a DIFFERENT machine → let the OS auto-detect rather than
        # inheriting the source's (possibly wrong) value.
        data['os'] = 'auto'
        # The per-node cluster identity (which node this host IS — proxmox's node
        # name, keepalived's priority, …) is unique to the machine; a clone is a
        # different node, so blank it. Strip the legacy 'node' plus every module's
        # declared per-node field (__member_field__), discovered — not hardcoded.
        from lib.hosts.profiles import module_member_fields  # noqa: PLC0415
        _strip = {'node'} | set(module_member_fields(wa._modules_dir).values())
        for _prof in (data.get('profiles') or {}).values():
            if isinstance(_prof, dict):
                for _k in _strip:
                    _prof.pop(_k, None)
        if not data['name']:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        new_uid = store.create(data, actor=session.get('username', SYSTEM_USER))
        if not new_uid:
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        # Duplicate the source host's module checks onto the clone.  When the
        # client sends a ``checks`` list, only those item keys are cloned (the
        # user picked them in the modal); absent → clone all.
        _sel = (body or {}).get('checks')
        only_keys = set(str(k) for k in _sel) if isinstance(_sel, list) else None
        checks_cloned = _clone_host_checks(wa, uid, new_uid, label=data['name'],
                                           only_keys=only_keys)
        wa._audit('host_cloned', detail={
            'uid': new_uid, 'source_uid': uid, 'name': data['name'],
            'address': data.get('address', ''), 'checks_cloned': checks_cloned,
        })
        return jsonify({'ok': True, 'uid': new_uid, 'checks_cloned': checks_cloned})

    @app.route('/api/v1/hosts/<uid>', methods=['PUT'])
    @login_required
    def api_update_host(uid):
        """Update a host.  Masked (null/'') secrets are restored from the
        stored value so the client never has to resend them."""
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        old = store.get(uid, decrypt=True)
        if old is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        # Restore secrets the client masked out (profiles only carry secrets).
        # Done before authorization so an unchanged profile isn't seen as edited.
        if isinstance(data.get('profiles'), dict):
            secret_manager.restore_sensitive(
                data['profiles'], old.get('profiles') or {}, keys=wa._secret_keys)
        # Full edit, or — for an 'add'-only user — a change limited to registering
        # additional monitored modules (the host's ``modules`` hint list), which
        # is how adding a check to a server touches the host record.
        if not wa._has_server_permission(uid, 'edit'):
            if not (wa._has_server_permission(uid, 'add')
                    and _only_modules_growth(old, data)):
                return jsonify({'error': wa._t('access_denied')}), 403
        if not store.update(uid, data, actor=session.get('username', SYSTEM_USER)):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        # Field-level diff (secrets masked) — same convention as config/modules.
        _diffable = ('name', 'address', 'kind', 'os', 'maintenance', 'tags',
                     'description', 'profiles', 'modules')
        changes = wa._diff_dicts(
            {k: old.get(k) for k in _diffable},
            {k: data.get(k) for k in _diffable},
            sensitive=wa._secret_keys,
        )
        wa._audit('host_updated', detail={
            'uid': uid, 'name': data.get('name'), 'changes': changes,
        })
        return jsonify({'ok': True})

    tests.register(app, wa)

    @app.route('/api/v1/hosts/<uid>', methods=['DELETE'])
    @login_required
    def api_delete_host(uid):
        """Delete a host."""
        if not wa._has_server_permission(uid, 'delete'):
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('host_not_found')}), 404
        old = store.get(uid, decrypt=False)
        if old is None or not store.delete(uid):
            return jsonify({'error': wa._t('host_not_found')}), 404
        # Optionally also delete the module checks bound to this host (the client
        # asks the user). Otherwise they are left (and read as inline).
        checks_deleted = 0
        if str(request.args.get('with_checks') or '').lower() in ('1', 'true', 'yes'):
            checks_deleted = _delete_host_checks(wa, uid)
        wa._audit('host_deleted', detail={
            'uid': uid, 'name': old.get('name', ''), 'address': old.get('address', ''),
            'checks_deleted': checks_deleted,
        })
        return jsonify({'ok': True, 'checks_deleted': checks_deleted})

    migrate.register(app, wa)
