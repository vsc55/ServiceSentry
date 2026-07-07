#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assisted host migration: /api/v1/hosts/migrate/{preview,apply}.

Detect inline connections repeated across modules and propose collapsing them
into shared hosts; on apply, create the hosts and rewrite the checks.
"""

from flask import jsonify, session

from lib.security import secret_manager
from lib.core.hosts.migrate import apply_to_modules, build_migration_plan

from lib.core.constants import SYSTEM_USER
from ._helpers import _create_unique_host


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_hosts_store', None)

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
