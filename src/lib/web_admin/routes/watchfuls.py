#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watchful-module utility routes: /api/watchfuls/<module_name>/<action>."""

import importlib
import os
import re
import sys

from flask import jsonify, request


def _resolve_host_ctx(wa, config):
    """Build a host-context dict for host-aware discovery, or None.

    Resolved server-side so SSH secrets never come from the client: a
    ``host_uid`` is looked up in the host registry (decrypted); a brand-new
    (unsaved) host may instead pass a ``_host`` draft, whose masked secrets are
    restored from the stored host when a ``host_uid`` is also given.
    """
    from lib import os_detect  # noqa: PLC0415

    def _ctx(address, kind, os_, ssh):
        os_ = str(os_ or 'auto').strip().lower()
        if os_ == 'auto':
            os_ = os_detect.local_os() if kind != 'remote' else 'linux'
        return {'address': address or '', 'kind': kind or 'local', 'os': os_, 'ssh': ssh or {}}

    store = getattr(wa, '_hosts_store', None)
    uid = str(config.get('host_uid') or '').strip()
    stored = store.get(uid, decrypt=True) if (store and uid) else None
    draft = config.get('_host') if isinstance(config.get('_host'), dict) else None

    if draft:
        ssh = dict((draft.get('profiles') or {}).get('ssh') or draft.get('ssh') or {})
        if stored:  # restore secrets the client masked out
            stored_ssh = (stored.get('profiles') or {}).get('ssh') or {}
            for k in ('ssh_password', 'ssh_key_string'):
                if ssh.get(k) in (None, '') and stored_ssh.get(k):
                    ssh[k] = stored_ssh[k]
        return _ctx(draft.get('address') or (stored or {}).get('address'),
                    draft.get('kind') or (stored or {}).get('kind'),
                    draft.get('os') or (stored or {}).get('os'), ssh)
    if stored:
        return _ctx(stored.get('address'), stored.get('kind'), stored.get('os'),
                    (stored.get('profiles') or {}).get('ssh') or {})
    return None


def _restore_action_secrets(wa, module, config):
    """Restore masked (null/'') secret fields in an action's *config* from the
    stored modules.json item (matched by the injected ``_item_key``), so a web
    action (e.g. datastore test_connection / list_databases) run AFTER a reload
    uses the real stored secret instead of the masked placeholder."""
    key = str(config.get('_item_key') or '').strip()
    if not key:
        return
    try:
        from lib import secret_manager  # noqa: PLC0415
        modules = wa._read_config_file(wa._MODULES_FILE) or {}
    except Exception:  # pylint: disable=broad-except
        return
    for mk in (module, f'watchfuls.{module}'):
        mod = modules.get(mk)
        if not isinstance(mod, dict):
            continue
        for coll, items in mod.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            stored = items.get(key)
            if isinstance(stored, dict):
                secret_manager.restore_sensitive(
                    config, stored, keys=getattr(wa, '_secret_keys', frozenset()))
                return


def _merge_host_conn(wa, module, config, host_ctx):
    """Populate *config*'s connection fields from the bound host (its address and
    SSH profile), mirroring ModuleBase.resolve_host — so a web action runs on a
    host-bound check whose own connection fields are empty.  An explicit value on
    the check always wins; only blank/0/missing fields are filled.

    Reads ``__host_profile__`` straight from the module schema (not
    module_host_specs, which drops address-only profiles like datastore's 'db')
    so the address_field is filled even when its ``fields`` list is empty."""
    try:
        import json as _json  # noqa: PLC0415
        base = wa._modules_dir or os.path.normpath(
            os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, 'watchfuls'))
        with open(os.path.join(base, module, 'schema.json'), encoding='utf-8') as fh:
            hp = _json.load(fh).get('__host_profile__')
    except Exception:  # pylint: disable=broad-except
        return
    specs = [hp] if isinstance(hp, dict) else (hp or [])
    address = host_ctx.get('address') or ''
    ssh = host_ctx.get('ssh') or {}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        address_field = spec.get('address_field')
        # The address_field is filled from the host address even when not listed
        # in `fields` (e.g. datastore 'host', web 'url' stay visible/editable) —
        # only when the check left it blank, so a per-check override wins.
        if address_field and address and config.get(address_field) in (None, '', 0):
            config[address_field] = address
        for f in (spec.get('fields') or []):
            if config.get(f) not in (None, '', 0):
                continue              # the check's own value wins
            if f in ssh:
                config[f] = ssh[f]    # ssh_* ← host SSH profile


def register(app, wa):
    modules_view_req = wa._perm_required('modules_view')

    @app.route('/api/v1/watchfuls/<module_name>/<action>', methods=['GET', 'POST'])
    @modules_view_req
    def api_watchful_action(module_name, action):
        if not re.match(r'^[a-z][a-z0-9_]*$', module_name):
            return jsonify({'error': 'Invalid module name'}), 400
        if not re.match(r'^[a-z][a-z0-9_]*$', action):
            return jsonify({'error': 'Invalid action name'}), 400

        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 404

        parent = os.path.dirname(wa._modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        try:
            mod = importlib.import_module(f'watchfuls.{module_name}')
        except ImportError:
            return jsonify({'error': 'Module not found'}), 404

        cls = getattr(mod, 'Watchful', None)
        if cls is None:
            return jsonify({'error': 'Module not found'}), 404

        if action not in cls.WATCHFUL_ACTIONS:
            return jsonify({'error': 'Action not supported'}), 404

        method = getattr(cls, action, None)
        if method is None:
            return jsonify({'error': 'Action not found'}), 404

        # Access control: read-only actions need only modules_view (already
        # enforced by the decorator); any state-changing action (upload/delete
        # MIB, import-from-URL, compile, build index, …) requires edit rights.
        _read_only = action in getattr(cls, 'READ_ONLY_ACTIONS', set())
        if not _read_only and not wa._has_module_permission(module_name, 'edit'):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        try:
            if request.method == 'POST':
                config = request.get_json(silent=True) or {}
                # Strip any __dunder__ keys the client may have sent — these are
                # internal control fields and must never be client-controllable.
                for _k in [k for k in config if k.startswith('__') and k.endswith('__')]:
                    del config[_k]
                # Restore the check's own masked secrets (e.g. a DB password) from
                # the stored config, so an action run after a reload (when the UI
                # only holds the masked placeholder) authenticates correctly.
                _restore_action_secrets(wa, module_name, config)
                # Inject server-side context after stripping client values so the
                # server value always wins regardless of what the client sent.
                config['__var_dir__'] = wa._var_dir or ''
                # Shared DB connector, for modules that use their own tables
                # (lib.db.module_tables).  Never client-controllable.
                config['__connector__'] = getattr(wa, '_db_connector', None)
                # Host-aware discovery: resolve the bound host (address + SSH,
                # server-side) so the action can run on it (local or over SSH).
                host_ctx = _resolve_host_ctx(wa, config)
                if host_ctx is not None:
                    config['__host__'] = host_ctx
                    # Fill the module's connection fields (address + SSH) from the
                    # bound host so actions like datastore's list_databases work on
                    # a host-bound check (whose host/ssh fields are empty because
                    # the value comes from the host).
                    _merge_host_conn(wa, module_name, config, host_ctx)
                result = method(config)
            else:
                result = method()
            # Build audit entry via module hooks (keeps route handler generic).
            _res = result if isinstance(result, dict) else {}
            if not _read_only:
                _audit_fn = getattr(cls, 'audit_detail', None)
                if callable(_audit_fn):
                    _extra = _audit_fn(action, _res)
                else:
                    _extra = {'ok': _res.get('ok', True), 'name': f'{module_name} / {action}'}
                if _extra is not None:
                    wa._audit('watchful_action', detail={
                        'module': module_name, 'action': action, **_extra,
                    })
            return jsonify(result)
        except Exception as exc:
            wa._audit('watchful_action', detail={
                'module': module_name, 'action': action, 'ok': False, 'message': str(exc),
            })
            return jsonify({'ok': False, 'message': str(exc)}), 500
