#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host registry HTTP routes — all under /api/v1/hosts:

* CRUD: GET (list), POST (create), GET /<uid>/status, POST /<uid>/clone, PUT /<uid>, DELETE /<uid>
* test/probe: POST /test_ssh, /test_check, /test (run a check once without saving)
* assisted migration: GET /migrate/preview, POST /migrate/apply

A host carries an address plus per-protocol connection profiles (ssh, snmp, db, http…) that
watchful modules reuse, so a server connection is defined once.  Secret values inside profiles
are masked on read and restored on write.  All non-HTTP logic (check fan-out, per-host status,
probe-prep, clone-record building, migration planning) lives in :mod:`lib.core.hosts.service`
and :mod:`lib.core.hosts.migrate`; these handlers are thin HTTP glue.

Routes registered by this file:

    GET    /api/v1/hosts                      list hosts the user may view (masked)
    GET    /api/v1/hosts/<uid>/status         latest recorded results per bound check
    POST   /api/v1/hosts                      create a host
    POST   /api/v1/hosts/<uid>/clone          clone a host (profiles + secrets, new uid)
    PUT    /api/v1/hosts/<uid>                update a host (masked secrets restored)
    DELETE /api/v1/hosts/<uid>                delete a host (optionally its checks)
    POST   /api/v1/hosts/test_ssh             probe a host's SSH connection (no save)
    POST   /api/v1/hosts/test_check           run one check once (no save)
    POST   /api/v1/hosts/test                 full host test: SSH + every bound check
    GET    /api/v1/hosts/migrate/preview      inline-connections migration proposal
    POST   /api/v1/hosts/migrate/apply        create hosts + rewrite the checks
"""

from flask import jsonify, request, session

from lib.security import secret_manager
from lib.core.constants import SYSTEM_USER
from lib.core.hosts import service as hosts_svc
from lib.core.hosts import ssh_client
from lib.core.hosts import probe as host_probe
from lib.core.hosts.migrate import apply_to_modules, build_migration_plan
from lib.core.hosts.service import (
    _MOD_RE, _bare, _probe_host_record, _restore_check_secrets,
    _apply_check_cred, _checks_for_host, _create_unique_host,
)


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_hosts_store', None)

    # ── host registry CRUD ───────────────────────────────────────────────────────

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
        hosts_svc.enrich_hosts(hosts, hosts_svc._host_statuses(wa),
                               hosts_svc._host_bound_modules(wa))
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
        return jsonify({'results': hosts_svc.build_host_status(bound, status_raw, hist_by_mod)})

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
            'virtual': bool(data.get('virtual')),
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
        # Build the clone record (deep-copy + name/address override + os=auto + strip
        # per-node cluster identity). Member fields are discovered, not hardcoded.
        from lib.core.hosts.profiles import module_member_fields  # noqa: PLC0415
        data = hosts_svc.build_clone_record(
            src, body, module_member_fields(wa._modules_dir).values())
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
        checks_cloned = hosts_svc._clone_host_checks(wa, uid, new_uid, label=data['name'],
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
                    and hosts_svc._only_modules_growth(old, data)):
                return jsonify({'error': wa._t('access_denied')}), 403
        if not store.update(uid, data, actor=session.get('username', SYSTEM_USER)):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        # Field-level diff (secrets masked) — same convention as config/modules.
        _diffable = ('name', 'address', 'kind', 'os', 'maintenance', 'virtual', 'tags',
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
            checks_deleted = hosts_svc._delete_host_checks(wa, uid)
        wa._audit('host_deleted', detail={
            'uid': uid, 'name': old.get('name', ''), 'address': old.get('address', ''),
            'checks_deleted': checks_deleted,
        })
        return jsonify({'ok': True, 'checks_deleted': checks_deleted})

    # ── test / probe endpoints (run a check once without saving) ─────────────────

    def _can_edit_body_host():
        """Edit gate for the test endpoints — allow the global ``servers_edit``
        or a per-server ``server.{uid}.edit`` when the body targets an existing
        host (a new draft has no uid, so it needs the global permission)."""
        uid = str((request.get_json(silent=True) or {}).get('uid') or '').strip()
        return wa._has_server_permission(uid, 'edit')

    @app.route('/api/v1/hosts/test_ssh', methods=['POST'])
    @login_required
    def api_test_host_ssh():
        """Probe the SSH connection for a (remote) host without saving it.

        Body: ``{address, profiles:{ssh:{...}}, uid?}``.  When a secret field is
        masked (null/'') and ``uid`` is given, it is restored from the stored
        host so the user need not re-enter the password/key to test.
        """
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        if not ssh_client.HAS_PARAMIKO:
            return jsonify({'ok': False,
                            'message': 'paramiko is not installed (pip install paramiko)'})
        data, err = wa._require_json()
        if err:
            return err
        ssh = dict((data.get('profiles') or {}).get('ssh') or {})
        uid = str(data.get('uid') or '').strip()
        cred_uid = str(ssh.get('cred_uid') or '').strip()
        if cred_uid:
            # A reusable credential supplies the identity: drop any inline
            # user/auth/secret (so a stale value can't win) and overlay the
            # credential — exactly what resolve_host does at runtime.  The
            # stored host's inline secret must NOT be restored here, or a wrong
            # credential would be tested with the host's old correct password.
            from lib.core.credentials.store import apply_credential, SSH_CRED_FIELDS  # noqa: PLC0415
            cstore = getattr(wa, '_credentials_store', None)
            cred = cstore.get(cred_uid) if cstore is not None else None
            ssh = apply_credential({k: v for k, v in ssh.items() if k not in SSH_CRED_FIELDS}, cred)
        else:
            # Inline edit flow: restore masked secrets from the stored host so
            # the user need not re-type the password/key just to test.
            store = _store()
            if store is not None and uid:
                stored = store.get(uid, decrypt=True) or {}
                stored_ssh = (stored.get('profiles') or {}).get('ssh') or {}
                for k in ('ssh_password', 'ssh_key_string'):
                    if ssh.get(k) in (None, '') and stored_ssh.get(k):
                        ssh[k] = stored_ssh[k]
        ok, msg, os_found = ssh_client.test_connection(
            address=data.get('address', ''),
            port=ssh.get('ssh_port') or 22,
            user=ssh.get('ssh_user', ''),
            password=ssh.get('ssh_password', ''),
            key_path=ssh.get('ssh_key', ''),
            key_string=ssh.get('ssh_key_string', ''),
            verify_host=bool(ssh.get('ssh_verify_host', False)),
            detect=True,
        )
        wa._audit('host_ssh_tested', detail={
            'uid': uid, 'address': data.get('address', ''), 'ok': ok, 'os': os_found,
        })
        return jsonify({'ok': ok, 'message': msg, 'os': os_found})

    def _item_name(items, key):
        """Friendly label for a result key: the item's ``label``, falling back to
        the base item for derived keys (e.g. ram_swap ``<uid>_ram``)."""
        for cand in (key, key.rsplit('_', 1)[0]):
            it = items.get(cand)
            if isinstance(it, dict) and str(it.get('label') or '').strip():
                return str(it['label']).strip()
        return ''

    def _run_checks(record, grouped):
        """Run each grouped check once on the host; return a flat result list."""
        store = host_probe.ProbeHostsStore(record, _store())
        db = getattr(wa, '_db_connector', None)
        out = []
        for (bare, coll), items in grouped.items():
            cfg = {f'watchfuls.{bare}': {coll: items}}
            try:
                results = host_probe.run_module_check(
                    bare, cfg, hosts_store=store, db=db, modules_dir=wa._modules_dir)
            except Exception as exc:  # pylint: disable=broad-except
                out.append({'module': bare, 'key': '', 'name': '', 'ok': False,
                            'message': str(exc)})
                continue
            for r in results:
                out.append({'module': bare, 'key': r['key'],
                            'name': _item_name(items, r['key']),
                            'ok': r['status'], 'message': r['message']})
        return out

    def _ssh_test(record):
        ssh = (record.get('profiles') or {}).get('ssh') or {}
        if not ssh_client.HAS_PARAMIKO:
            return {'ok': False, 'message': 'paramiko is not installed'}
        ok, msg, _os = ssh_client.test_connection(
            address=record.get('address', ''), port=ssh.get('ssh_port') or 22,
            user=ssh.get('ssh_user', ''), password=ssh.get('ssh_password', ''),
            key_path=ssh.get('ssh_key', ''), key_string=ssh.get('ssh_key_string', ''),
            verify_host=bool(ssh.get('ssh_verify_host', False)), detect=True)
        return {'ok': ok, 'message': msg}

    @app.route('/api/v1/hosts/test_check', methods=['POST'])
    @login_required
    def api_test_host_check():
        """Run ONE check once on the host and return its result(s)."""
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        body, err = wa._require_json()
        if err:
            return err
        module = _bare(str(body.get('module') or ''))
        if not _MOD_RE.match(module):
            return jsonify({'ok': False, 'message': 'invalid module'}), 400
        coll = str(body.get('collection') or 'list')
        key = str(body.get('key') or 'check')
        record = _probe_host_record(wa, body)
        fields = dict(body.get('fields') or {})
        # The modal sends cred_uid at the body level (the check's binding lives
        # outside its fields); fold it in so the credential is actually applied.
        if body.get('cred_uid') and not fields.get('cred_uid'):
            fields['cred_uid'] = body.get('cred_uid')
        _restore_check_secrets(wa, module, coll, key, fields)
        fields = _apply_check_cred(wa, fields)
        item = {**fields, 'host_uid': record['uid'], 'enabled': True}
        results = _run_checks(record, {(module, coll): {key: item}})
        ok = bool(results) and all(r['ok'] for r in results)
        wa._audit('host_test_check', detail={
            'uid': record['uid'], 'name': record.get('name', ''),
            'module': module, 'key': key, 'ok': ok,
            'results': [{'key': r['key'], 'ok': r['ok'], 'message': r['message']}
                        for r in results],
        })
        return jsonify({'ok': ok, 'results': results})

    @app.route('/api/v1/hosts/test', methods=['POST'])
    @login_required
    def api_test_host():
        """Full host test: SSH connection (if remote) + every bound check once."""
        if not _can_edit_body_host():
            return jsonify({'error': wa._t('access_denied')}), 403
        body, err = wa._require_json()
        if err:
            return err
        record = _probe_host_record(wa, body)
        out = {'ssh': None, 'results': []}
        # A module-scoped test (no_ssh) skips the SSH connection check.
        if str(record.get('kind') or '').lower() == 'remote' and not body.get('no_ssh'):
            out['ssh'] = _ssh_test(record)

        # Checks: explicit list from the modal, else everything bound in the module configuration.
        grouped = {}
        checks = body.get('checks')
        if isinstance(checks, list):
            for c in checks:
                bare = _bare(str(c.get('module') or ''))
                if not _MOD_RE.match(bare):
                    continue
                coll = str(c.get('collection') or 'list')
                key = str(c.get('key') or '') or f'check{len(grouped)}'
                fields = dict(c.get('fields') or {})
                if c.get('cred_uid') and not fields.get('cred_uid'):
                    fields['cred_uid'] = c.get('cred_uid')
                _restore_check_secrets(wa, bare, coll, key, fields)
                fields = _apply_check_cred(wa, fields)
                grouped.setdefault((bare, coll), {})[key] = {
                    **fields, 'host_uid': record['uid'], 'enabled': True}
        else:
            grouped = _checks_for_host(wa, record['uid'])
            for _items in grouped.values():
                for _k in list(_items):
                    _items[_k] = _apply_check_cred(wa, _items[_k])

        out['results'] = _run_checks(record, grouped)
        out['ok'] = ((out['ssh'] is None or out['ssh']['ok'])
                     and all(r['ok'] for r in out['results']))
        passed = sum(1 for r in out['results'] if r['ok'])
        failed = [r for r in out['results'] if not r['ok']]
        wa._audit('host_tested', detail={
            'uid': record['uid'], 'name': record.get('name', ''),
            'ok': out['ok'],
            'ssh': (out['ssh'] or {}).get('ok'),
            'total': len(out['results']), 'passed': passed, 'failed': len(failed),
            # Per-check outcome so the audit shows exactly which check failed.
            'results': [{'module': r['module'], 'key': r['key'], 'ok': r['ok'],
                         'message': r['message']} for r in out['results']],
        })
        return jsonify(out)

    # ── assisted migration (inline connections → shared hosts) ───────────────────

    @app.route('/api/v1/hosts/migrate/preview', methods=['GET'])
    @login_required
    def api_migrate_preview():
        """Return the migration proposal (candidate hosts; secrets masked)."""
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        modules = wa._load_modules()
        plan = build_migration_plan(modules, wa._modules_dir)
        return jsonify(secret_manager.mask_sensitive(plan, wa._secret_keys))

    @app.route('/api/v1/hosts/migrate/apply', methods=['POST'])
    @login_required
    def api_migrate_apply():
        """Create hosts for the accepted candidates and rewrite the checks.

        Body: ``{"accept": [{"id": <candidate id>, "name": <optional>}]}``.
        The plan is rebuilt server-side from the (decrypted) module configuration, so the
        client never supplies credentials — only which candidates to accept.
        """
        if 'servers_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        body, err = wa._require_json()
        if err:
            return err
        accept = body.get('accept') or []
        modules = wa._load_modules()
        plan = build_migration_plan(modules, wa._modules_dir)
        by_id = {c['id']: c for c in plan['candidates']}
        actor = session.get('username', SYSTEM_USER)

        applied, created = [], []
        for acc in accept:
            cand = by_id.get(acc.get('id'))
            if not cand:
                continue
            uid = _create_unique_host(store, acc.get('name'), cand, actor)
            if not uid:
                continue
            applied.append({'uid': uid, 'members': cand['members']})
            created.append({
                'uid': uid,
                'name': (acc.get('name') or cand.get('suggested_name') or '').strip(),
                'address': cand.get('address', ''),
                'members': len(cand['members']),
                'checks': [f"{m['module'].split('.')[-1]}/{m['key']}" for m in cand['members']],
            })

        if applied:
            apply_to_modules(modules, applied, wa._modules_dir)
            if not wa._save_modules(modules):
                return jsonify({'error': wa._t('save_file_error')}), 500
            wa._audit('hosts_migrated', detail={
                'hosts': len(created),
                'checks': sum(c['members'] for c in created),
                'created': [{k: c[k] for k in ('uid', 'name', 'address', 'checks')}
                            for c in created],
            })
        return jsonify({'ok': True, 'created': len(created),
                        'checks': sum(c['members'] for c in created)})
