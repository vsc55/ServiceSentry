#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host registry routes: /api/v1/hosts (GET, POST), /api/v1/hosts/<uid> (PUT, DELETE).

A host carries an address plus per-protocol connection profiles (ssh, snmp, db,
http…) that watchful modules reuse, so a server's connection is defined once.

Access is gated by the existing ``modules_view`` / ``modules_edit`` permissions
(hosts are monitoring configuration); dedicated host permissions can be added
later.  Secret values inside the profiles are masked on read and restored from
the stored value when the client omits them on write — the same scheme as
modules.json.
"""

from flask import jsonify, session

from lib import secret_manager
from lib.host_migrate import apply_to_modules, build_migration_plan

SYSTEM_USER = 'system'


def _create_unique_host(store, name, candidate, actor):
    """Create a host, suffixing the name on collision.  Returns the uid or None."""
    base = (name or candidate.get('address') or 'host').strip() or 'host'
    body = {'name': base, 'address': candidate.get('address', ''),
            'profiles': candidate.get('profiles', {})}
    for attempt in (base, f"{base} ({candidate.get('address', '')})",
                    *[f"{base}-{i}" for i in range(2, 12)]):
        body['name'] = attempt.strip()
        uid = store.create(body, actor=actor)
        if uid:
            return uid
    return None


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_hosts_store', None)

    @app.route('/api/v1/hosts', methods=['GET'])
    @login_required
    def api_get_hosts():
        """List all hosts (secrets masked)."""
        if 'modules_view' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'hosts': []})
        hosts = store.list(decrypt=True)
        return jsonify({'hosts': secret_manager.mask_sensitive(hosts, wa._secret_keys)})

    @app.route('/api/v1/hosts', methods=['POST'])
    @login_required
    def api_create_host():
        """Create a host."""
        if 'modules_edit' not in wa._get_session_permissions():
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
        wa._audit('host_created', detail={'uid': uid, 'name': data.get('name')})
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/hosts/<uid>', methods=['PUT'])
    @login_required
    def api_update_host(uid):
        """Update a host.  Masked (null/'') secrets are restored from the
        stored value so the client never has to resend them."""
        if 'modules_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
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
        if isinstance(data.get('profiles'), dict):
            secret_manager.restore_sensitive(
                data['profiles'], old.get('profiles') or {}, keys=wa._secret_keys)
        if not store.update(uid, data, actor=session.get('username', SYSTEM_USER)):
            return jsonify({'error': wa._t('invalid_modules_data')}), 400
        wa._audit('host_updated', detail={'uid': uid, 'name': data.get('name')})
        return jsonify({'ok': True})

    @app.route('/api/v1/hosts/<uid>', methods=['DELETE'])
    @login_required
    def api_delete_host(uid):
        """Delete a host."""
        if 'modules_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None or not store.delete(uid):
            return jsonify({'error': wa._t('host_not_found')}), 404
        wa._audit('host_deleted', detail={'uid': uid})
        return jsonify({'ok': True})

    # ── Assisted migration: detect inline connections repeated across modules
    #    and propose collapsing them into shared hosts. ───────────────────────

    @app.route('/api/v1/hosts/migrate/preview', methods=['GET'])
    @login_required
    def api_migrate_preview():
        """Return the migration proposal (candidate hosts; secrets masked)."""
        if 'modules_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        modules = wa._read_config_file(wa._MODULES_FILE)
        plan = build_migration_plan(modules, wa._modules_dir)
        return jsonify(secret_manager.mask_sensitive(plan, wa._secret_keys))

    @app.route('/api/v1/hosts/migrate/apply', methods=['POST'])
    @login_required
    def api_migrate_apply():
        """Create hosts for the accepted candidates and rewrite the checks.

        Body: ``{"accept": [{"id": <candidate id>, "name": <optional>}]}``.
        The plan is rebuilt server-side from the (decrypted) modules.json, so the
        client never supplies credentials — only which candidates to accept.
        """
        if 'modules_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        body, err = wa._require_json()
        if err:
            return err
        accept = body.get('accept') or []
        modules = wa._read_config_file(wa._MODULES_FILE)
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
            created.append({'uid': uid, 'members': len(cand['members'])})

        if applied:
            apply_to_modules(modules, applied, wa._modules_dir)
            if not wa._save_config_file(wa._MODULES_FILE, modules):
                return jsonify({'error': wa._t('save_file_error')}), 500
            wa._audit('hosts_migrated', detail={
                'hosts': len(created),
                'checks': sum(c['members'] for c in created),
            })
        return jsonify({'ok': True, 'created': len(created),
                        'checks': sum(c['members'] for c in created)})
