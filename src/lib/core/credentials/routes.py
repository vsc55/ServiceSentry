#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reusable-credentials routes: /api/v1/credentials (GET, POST),
/api/v1/credentials/<uid> (PUT, DELETE), /api/v1/credentials/test (POST).

A credential is a named SSH identity (user + password or private key) defined
once and referenced by hosts and inline checks via ``cred_uid``.  Management is
gated by the dedicated ``credentials_*`` permissions; the list is also visible
to anyone who can see/edit servers, so the host form can offer a picker.

Secret values inside ``data`` (ssh_password / ssh_key_string) are masked on
read and restored from the stored value when the client omits them on write —
the same scheme as the host profiles.

Routes registered by this file:

    GET    /api/v1/credentials                  list credentials (secrets masked)
    POST   /api/v1/credentials                  create a credential
    POST   /api/v1/credentials/<uid>/clone      duplicate a credential (secrets incl.)
    GET    /api/v1/credentials/<uid>/usage      where a credential is referenced
    PUT    /api/v1/credentials/<uid>            update a credential (masked restored)
    DELETE /api/v1/credentials/<uid>            delete a credential
    POST   /api/v1/credentials/test             test an SSH credential against a host
"""

from flask import jsonify, session

from lib.security import secret_manager
from lib.core.hosts import ssh_client
from lib.core.credentials import service as cred_svc

from lib.core.constants import SYSTEM_USER


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_credentials_store', None)

    @app.route('/api/v1/credentials', methods=['GET'])
    @login_required
    def api_get_credentials():
        """List credentials (secrets masked).

        Visible to ``credentials_view`` or to anyone who can see/edit servers
        (so the host SSH form can offer a credential picker)."""
        perms = wa._get_session_permissions()
        if not (perms & {'credentials_view', 'credentials_edit',
                         'credentials_add', 'credentials_delete',
                         'servers_view', 'servers_edit',
                         'modules_view', 'modules_edit'}):
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'credentials': []})
        creds = secret_manager.mask_sensitive(store.list(decrypt=True), wa._secret_keys)
        return jsonify({'credentials': creds})

    @app.route('/api/v1/credentials', methods=['POST'])
    @login_required
    def api_create_credential():
        """Create a credential."""
        if 'credentials_add' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        data, err = wa._require_json()
        if err:
            return err
        if not str(data.get('name') or '').strip():
            return jsonify({'error': wa._t('cred_name_required')}), 400
        uid = store.create(data, actor=session.get('username', SYSTEM_USER))
        if not uid:
            return jsonify({'error': wa._t('cred_name_exists')}), 400
        wa._audit('credential_created', detail={
            'uid': uid, 'name': data.get('name'),
            'ctype': data.get('ctype', 'ssh'),
            'ssh_user': (data.get('data') or {}).get('ssh_user', ''),
        })
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/credentials/<uid>/clone', methods=['POST'])
    @login_required
    def api_clone_credential(uid):
        """Duplicate a credential (secrets included, copied server-side so they
        are never exposed) under a free ``"<name> (copy)"`` name."""
        if 'credentials_add' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        src = store.get(uid, decrypt=True)
        if src is None:
            return jsonify({'error': wa._t('cred_not_found')}), 404
        suffix = wa._t('cred_copy_suffix') or '(copy)'
        base = src.get('name') or 'credential'
        actor = session.get('username', SYSTEM_USER)
        payload = cred_svc.clone_payload(src)
        new_uid, cand = None, ''
        for cand in cred_svc.clone_candidate_names(base, suffix):
            new_uid = store.create({'name': cand, **payload}, actor=actor)
            if new_uid:
                break
        if not new_uid:
            return jsonify({'error': wa._t('cred_name_exists')}), 400
        wa._audit('credential_cloned', detail={'from': uid, 'uid': new_uid, 'name': cand})
        return jsonify({'ok': True, 'uid': new_uid})

    @app.route('/api/v1/credentials/<uid>/usage', methods=['GET'])
    @login_required
    def api_credential_usage(uid):
        """Where a credential is referenced: hosts (ssh profile cred_uid) and
        module checks (inline cred_uid).  Shown in the credential modal."""
        perms = wa._get_session_permissions()
        if not (perms & {'credentials_view', 'credentials_edit',
                         'credentials_add', 'credentials_delete'}):
            return jsonify({'error': wa._t('access_denied')}), 403
        hs = getattr(wa, '_hosts_store', None)
        hosts = hs.list(decrypt=False) if hs is not None else []
        return jsonify(cred_svc.find_credential_usage(uid, hosts, wa._load_modules()))

    @app.route('/api/v1/credentials/<uid>', methods=['PUT'])
    @login_required
    def api_update_credential(uid):
        """Update a credential.  Masked (null/'') secrets are restored from the
        stored value so the client never has to resend them."""
        if 'credentials_edit' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        old = store.get(uid, decrypt=True)
        if old is None:
            return jsonify({'error': wa._t('cred_not_found')}), 404
        data, err = wa._require_json()
        if err:
            return err
        if isinstance(data.get('data'), dict):
            secret_manager.restore_sensitive(
                data['data'], old.get('data') or {}, keys=wa._secret_keys)
        changes = wa._diff_dicts(old, data, sensitive=wa._secret_keys)
        if not store.update(uid, data, actor=session.get('username', SYSTEM_USER)):
            return jsonify({'error': wa._t('cred_name_exists')}), 400
        wa._audit('credential_updated', detail={'uid': uid, 'name': data.get('name'),
                                                'changes': changes})
        return jsonify({'ok': True})

    @app.route('/api/v1/credentials/<uid>', methods=['DELETE'])
    @login_required
    def api_delete_credential(uid):
        """Delete a credential.  Hosts/checks that referenced it fall back to
        their inline SSH fields (a dangling cred_uid is ignored at resolution)."""
        if 'credentials_delete' not in wa._get_session_permissions():
            return jsonify({'error': wa._t('access_denied')}), 403
        store = _store()
        if store is None:
            return jsonify({'error': wa._t('save_file_error')}), 500
        old = store.get(uid, decrypt=False)
        if not store.delete(uid):
            return jsonify({'error': wa._t('cred_not_found')}), 404
        wa._audit('credential_deleted', detail={
            'uid': uid, 'name': (old or {}).get('name', '')})
        return jsonify({'ok': True})

    @app.route('/api/v1/credentials/test', methods=['POST'])
    @login_required
    def api_test_credential():
        """Open an SSH connection with a credential against a given address to
        verify it works.  Body: {cred_uid?|data?, address, ssh_port?,
        ssh_verify_host?}.  Masked secrets are taken from the stored credential."""
        perms = wa._get_session_permissions()
        if not (perms & {'credentials_view', 'credentials_edit',
                         'credentials_add', 'servers_edit'}):
            return jsonify({'error': wa._t('access_denied')}), 403
        body, err = wa._require_json()
        if err:
            return err
        store = _store()
        # Resolve the identity: a saved credential by uid, or an inline draft.
        data = body.get('data') if isinstance(body.get('data'), dict) else {}
        uid = str(body.get('cred_uid') or '').strip()
        if uid and store is not None:
            stored = store.get(uid, decrypt=True) or {}
            cred_svc.resolve_test_identity(data, stored.get('data') or {})
        address = str(body.get('address') or '').strip()
        if not address:
            return jsonify({'ok': False, 'message': wa._t('host_address_required')})
        ok, msg = ssh_client.test_connection(
            address=address,
            port=body.get('ssh_port') or 22,
            user=data.get('ssh_user', ''),
            password=data.get('ssh_password', ''),
            key_path=data.get('ssh_key', ''),
            key_string=data.get('ssh_key_string', ''),
            verify_host=bool(body.get('ssh_verify_host', False)),
        )
        return jsonify({'ok': bool(ok), 'message': msg})
