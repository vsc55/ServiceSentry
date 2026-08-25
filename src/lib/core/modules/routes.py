#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module routes — the modules domain HTTP surface:

* config CRUD + check state + on-demand run under ``/api/v1/modules/*``; and
* the per-watchful-module action dispatch ``/api/v1/modules/watchfuls/<module>/<action>`` (test/probe/
  discover/MIB…).

What they call is Flask-free and lives one concept per module: :mod:`~lib.core.modules.service`
(the config document — what may be seen, whether it is well formed, what the UI is built from),
:mod:`~lib.core.modules.items` (an item's identity), :mod:`~lib.core.modules.authz` (may this
save touch this item), :mod:`~lib.core.modules.provisioning` and
:mod:`~lib.core.modules.actions`. These routes own request parsing, secret restore/masking,
dynamic dispatch, persistence and audit.

Routes registered by this file:

    GET      /api/v1/modules                            modules the user may view (masked)
    PUT      /api/v1/modules                            overwrite the module configuration
    GET      /api/v1/modules/status                     current check state (read-only)
    DELETE   /api/v1/modules/status                     clear the check-state table
    POST     /api/v1/modules/checks/run                 run module checks on demand
    GET      /api/v1/modules/overview                   slim shared Overview snapshot
    GET      /api/v1/modules/page/<module_name>          data for a module-contributed section
    GET,POST /api/v1/modules/watchfuls/<module_name>/<action>   run a watchful module's declared action
"""

import importlib
import os
import re
import sys

from flask import jsonify, request, session

from lib.config.spec import CFG_BY_PATH
from lib.security import secret_manager

from lib.core.modules import actions as modules_actions
from lib.core.modules import authz as modules_authz
from lib.core.modules import items as modules_items
from lib.core.modules import provisioning as modules_prov
from lib.core.modules import service as modules_svc
from lib.core.users.service import AdminOpError
from lib.core.permissions import service as perms_svc


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
        # Units were relabelled (GB -> GiB) without any number changing. Migrated on the way
        # out so a dropdown never shows a value it does not offer: a select whose value is
        # absent from its options displays the first one, and saving the item would then turn
        # a 100 GB threshold into 100 MiB.
        modules_svc.normalize_unit_fields(all_data)
        if 'modules_view' in perms:
            return jsonify(secret_manager.mask_sensitive(all_data, wa._secret_keys))
        visible = modules_svc.visible_modules(all_data, perms)
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
        # Reject immediately when the user has no write permission of any kind.
        if not modules_authz.has_any_module_write(perms):
            return jsonify({'error': wa._t('access_denied')}), 403
        data, err = wa._require_json()
        if err:
            return err
        old_data = wa._load_modules()
        try:
            modules_svc.validate_modules_shape(data)
            # Restore masked secrets BEFORE authorization so an unchanged item with a
            # masked secret is not seen as "modified" (which would over-require edit).
            secret_manager.restore_sensitive(data, old_data, keys=wa._secret_keys)
            # Items bound to a credential keep no inline user/secret (cleared after
            # the restore above so a stale value can't be persisted/restored).
            modules_prov.strip_credential_fields(data, wa._modules_dir)
            if not has_global_edit:
                modules_authz.authorize_modules_save(old_data, data, perms)
        except AdminOpError as e:
            code = 403 if e.key == 'access_denied' else 400
            return jsonify({'error': wa._t(e.key, *e.args)}), code
        modules_items.ensure_item_uids(data)     # generate stable UIDs for new items
        # Read the duplicates BEFORE re-keying resolves them: afterwards there is nothing to
        # see. A repeated uid used to cost an item its existence (the re-key builds a dict
        # keyed by uid, so the second write replaced the first); it no longer does, but a
        # duplicate should never arrive, and knowing one did — with the module and the uid —
        # is the difference between finding its cause and guessing at it.
        dup_uids = modules_items.duplicate_item_uids(data)
        modules_items.rekey_items_by_uid(data)   # keep each item's dict key == its UID
        # Taken AFTER the re-key, so a clone is recorded under the uid it will actually be
        # stored with, and taken rather than read — the mark answers a question about this
        # write, and persisting it would turn it into a permanent property of the item.
        clone_marks = modules_items.take_clone_marks(data)
        # Generic: provision/link a host for any item that declares one
        # (__provision_host__ in its schema) — so address modules (ping/web/
        # ssl_cert) can monitor that endpoint. Module-agnostic (discovery-driven).
        provisioned = modules_prov.sync_provisioned_hosts(
            getattr(wa, '_hosts_store', None), getattr(wa, '_modules_dir', None),
            data, session.get('username', 'system'))
        if wa._save_modules(data):
            changes = wa._diff_dicts(
                old_data, data, sensitive=wa._sensitive_fields,
            )
            # The duplicate goes in the SAME entry as the change that carried it, because
            # that is the record someone will be reading when they ask where an item went.
            # As a row in the change list, not text appended to it: `_diff_dicts` returns
            # `[{field, old, new}]`, so concatenating a string raised TypeError — AFTER the
            # save had already succeeded and BEFORE this audit line ran. The result was the
            # worst shape a bug can take: the item stored, "save failed" on screen, the Save
            # button still lit, and nothing in the audit to say either had happened.
            if dup_uids:
                changes = list(changes or []) + [{
                    'field': 'duplicate item uid(s)',
                    'old': '', 'new': ', '.join(dup_uids),
                }]
            # Every item that APPEARED, and whether it was typed or copied. _diff_dicts
            # reports the new item's fields either way, which is the one distinction somebody
            # looking at two near-identical rows actually needs. Discovery supplies the field
            # each module calls its name, so the entry reads as names rather than uids.
            origins = modules_items.item_origin_rows(
                old_data, data, clone_marks,
                modules_items.item_schemas(getattr(wa, '_modules_dir', None)))
            if origins:
                changes = list(changes or []) + origins
            # Only when something actually changed. A PUT that stores what was already there
            # is a no-op, and an entry saying "Modules saved" with nothing under it is worse
            # than no entry: the audit is read to answer "what changed and when", and a row
            # that answers "nothing" still costs the reader a click to find that out — and
            # invites the conclusion that a change was made and lost. The duplicate note
            # counts as content in its own right: it says something happened even when no
            # field moved.
            if changes:
                wa._audit('modules_saved', detail=changes)
            # A module or a cluster item that just disappeared leaves its scoped keys
            # behind. Module names, unlike UIDs, CAN come back — which is exactly why they
            # are purged: a stale module.<name>.edit would silently apply to whatever is
            # called that next, and a grant nobody remembers granting is the bad direction.
            gone_modules = [m for m in old_data if m not in data]
            if gone_modules:
                wa._purge_scoped_permissions('module', gone_modules)
            gone_clusters = (perms_svc.cluster_item_uids(old_data)
                             - perms_svc.cluster_item_uids(data))
            if gone_clusters:
                wa._purge_scoped_permissions('cluster', sorted(gone_clusters))
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
    @wa._perm_required('checks_delete')
    def api_clear_status():
        """Empty the current check-state table so monitoring starts clean.

        Its own permission, held by no built-in role. It used to ride on ``checks_run``,
        which `editor` holds and which means "may operate monitoring" — a fair pairing while
        the button sat on the Status toolbar next to "run now", and the wrong one once it
        moved in beside the data wipes: running a check and erasing what every check reported
        are different acts, and the gate has to be on the endpoint rather than on the button,
        which is only where it is offered.
        """
        store = getattr(wa, '_check_state_store', None)
        # Counted BEFORE the delete: afterwards there is nothing left to count, and "state
        # cleared" on its own records that something happened rather than what. The gap
        # between clearing four rows and four thousand is the entire question anyone has when
        # they find this entry later.
        rows = store.count() if store else 0
        ok = bool(store and store.clear())
        wa._audit('status_cleared', detail={'ok': ok, 'rows_deleted': rows if ok else 0})
        return jsonify({'ok': ok, 'rows_deleted': rows if ok else 0})

    @app.route('/api/v1/modules/checks/run', methods=['POST'])
    @checks_run_req
    def api_run_checks():
        """Run module checks on demand.

        Accepts a JSON body with ``{"modules": [...]}`` to run specific modules, or
        ``{"modules": "all"}`` to run every enabled module.  Returns the result dict
        keyed by module.  The check engine itself lives in the monitoring service
        (``wa._run_checks``); this is the modules-domain HTTP surface for it, alongside
        ``/api/v1/modules/status``."""
        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 500
        if not wa._check_lock.acquire(blocking=False):
            return jsonify({'error': wa._t('checks_already_running')}), 409
        try:
            data = wa._optional_json()
            requested = data.get('modules', 'all')
            results, errors = wa._run_checks(requested)
            wa._audit('checks_run', detail={
                'requested': requested,
                'ok': list(results.keys()),
                'errors': errors,
            })
            return jsonify({'ok': True, 'results': results, 'errors': errors})
        finally:
            wa._check_lock.release()

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
        module_widgets = modules_svc.build_module_widgets(
            wa._modules_dir, status_raw, modules_raw, session.get('lang', wa._DEFAULT_LANG))
        from lib.core.roles.overview_widget import role_meta  # noqa: PLC0415
        _resp = {'module_widgets': module_widgets}
        _resp.update(role_meta(wa))
        return jsonify(_resp)

    # NOTE: the overview *layout* endpoints (/api/v1/overview/default-layout,
    # /reset-factory) moved to lib.core.overview.routes — this modules register keeps
    # only /api/v1/modules/overview (the slim shared snapshot, above).

    @app.route('/api/v1/modules/page/<module_name>', methods=['GET'])
    @wa._perm_required('modules_view')
    def api_module_page(module_name):
        """Data for a module-contributed SECTION (a module declaring ``__page__``).

        The CACHED half: the monitor's last results through the module's ``page_data``
        hook, so the section paints instantly and costs no upstream API call.  Refreshing
        live is a normal watchful action the module declares and serves itself.

        404 for a module that claims no page — that check is what stops this becoming a
        generic "run any module hook" hole.
        """
        if not re.match(r'^[a-z][a-z0-9_]*$', module_name or ''):
            return jsonify({'error': 'bad module'}), 400
        from lib.modules.discovery.pages import module_pages_catalog  # noqa: PLC0415
        if not any(p['module'] == module_name for p in module_pages_catalog(wa._modules_dir)):
            return jsonify({'error': 'no such page'}), 404
        data = modules_svc.build_module_page(
            wa._modules_dir, module_name, wa._read_check_status(), wa._load_modules(),
            session.get('lang', wa._DEFAULT_LANG))
        return jsonify({'module': module_name, 'data': data})

    # --- API: per-watchful-module action dispatch ----------------

    modules_view_req = wa._perm_required('modules_view')

    @app.route('/api/v1/modules/watchfuls/<module_name>/<action>', methods=['GET', 'POST'])
    @modules_view_req
    def api_watchful_action(module_name, action):
        """Dynamically dispatch a per-module ``Watchful.<action>`` (test/probe/discover/MIB…).
        Read-only actions need only ``modules_view`` (the decorator); state-changing ones need
        per-module edit.  The Flask-free config resolution lives in modules.service."""
        if not re.match(r'^[a-z][a-z0-9_]*$', module_name):
            return jsonify({'error': wa._t('invalid_module_name')}), 400
        if not re.match(r'^[a-z][a-z0-9_]*$', action):
            return jsonify({'error': wa._t('invalid_action_name')}), 400

        if not wa._modules_dir:
            return jsonify({'error': wa._t('checks_no_modules_dir')}), 404

        parent = os.path.dirname(wa._modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        try:
            mod = importlib.import_module(f'watchfuls.{module_name}')
        except ImportError:
            return jsonify({'error': wa._t('module_not_found')}), 404

        cls = getattr(mod, 'Watchful', None)
        if cls is None:
            return jsonify({'error': wa._t('module_not_found')}), 404

        if action not in cls.WATCHFUL_ACTIONS:
            return jsonify({'error': wa._t('action_not_supported')}), 404

        method = getattr(cls, action, None)
        if method is None:
            return jsonify({'error': wa._t('action_not_found')}), 404

        # Access control: read-only actions need only modules_view (already enforced by the
        # decorator); any state-changing action (upload/delete MIB, import-from-URL, compile,
        # build index, …) requires edit rights.
        _read_only = action in getattr(cls, 'READ_ONLY_ACTIONS', set())
        if not _read_only and not wa._has_module_permission(module_name, 'edit'):
            return jsonify({'error': wa._t('insufficient_permissions')}), 403

        try:
            if request.method == 'POST':
                config = request.get_json(silent=True) or {}
                # Strip any __dunder__ keys the client may have sent — these are internal
                # control fields and must never be client-controllable.
                for _k in [k for k in config if k.startswith('__') and k.endswith('__')]:
                    del config[_k]
                # Fill anything the caller did not send from the stored item (a caller with
                # no form knows only the key), then restore the check's own masked secrets
                # from the stored config, so an action run after a reload (the UI only holds
                # the masked placeholder) authenticates. Client values win in both.
                modules_actions.fill_from_stored_item(wa, module_name, config)
                modules_actions.restore_action_secrets(wa, module_name, config)
                # Inject server-side context after stripping client values so the server value
                # always wins regardless of what the client sent.
                config['__var_dir__'] = wa._var_dir or ''
                # Shared DB connector, for modules that use their own tables. Not client-set.
                config['__connector__'] = getattr(wa, '_db_connector', None)
                # Who is asking. A module that keeps a history of what people did to its data
                # has to be able to say whose change it was, and the audit log answers that
                # question somewhere else entirely — one row per action, not per record.
                config['__user__'] = session.get('username', '')
                # Host-aware discovery: resolve the bound host (address + SSH, server-side) so
                # the action can run on it (local or over SSH).
                host_ctx = modules_actions.resolve_host_ctx(wa, config)
                if host_ctx is not None:
                    config['__host__'] = host_ctx
                    # Fill the module's connection fields (address + SSH) from the bound host so
                    # actions like datastore's list_databases work on a host-bound check.
                    modules_actions.merge_host_conn(wa, module_name, config, host_ctx)
                # A referenced credential supplies the identity — overlay it last so it wins.
                modules_actions.apply_cred_to_config(wa, config)
                # …and again for the items INSIDE the config. A discovery scoped to a parent
                # item posts that item nested under its collection, which is where its
                # `host_uid` and `cred_uid` live: resolving only the top level handed the
                # action an item with no address and no identity.
                modules_actions.apply_item_identities(wa, module_name, config)
                result = method(config)
            else:
                result = method()
            # Build audit entry via module hooks (keeps the route handler generic).
            _res = result if isinstance(result, dict) else {}
            if not _read_only:
                _audit_fn = getattr(cls, 'audit_detail', None)
                if callable(_audit_fn):
                    _extra = _audit_fn(action, _res)
                else:
                    _extra = {'ok': _res.get('ok', True), 'name': f'{module_name} / {action}'}
                if _extra is not None:
                    # The hook decides WHAT is worth recording; how much of it one entry
                    # may hold is not the module's call, and leaving it to each of them is
                    # how twenty modules end up with twenty different ceilings.
                    _extra = modules_actions.cap_audit_lists(
                        _extra, getattr(wa, '_AUDIT_DETAIL_MAX_ITEMS',
                                        CFG_BY_PATH['web_admin|audit_detail_max_items'].default))
                    wa._audit('watchful_action', detail={
                        'module': module_name, 'action': action, **_extra,
                    })
            return jsonify(result)
        except Exception as exc:
            wa._audit('watchful_action', detail={
                'module': module_name, 'action': action, 'ok': False, 'message': str(exc),
            })
            return jsonify({'ok': False, 'message': str(exc)}), 500
