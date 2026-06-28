#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host test routes: /api/v1/hosts/test_ssh, /test_check, /test.

Probe a (possibly unsaved) host without persisting it: SSH connectivity and/or
running one or every bound check once, returning the live results.
"""

from flask import jsonify, request

from lib import ssh_client
from lib.hosts import probe as host_probe

from ._helpers import (
    _MOD_RE, _bare, _probe_host_record, _restore_check_secrets,
    _apply_check_cred, _checks_for_host,
)


def register(app, wa):
    login_required = wa._login_required

    def _store():
        return getattr(wa, '_hosts_store', None)

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
            from lib.stores.credentials import apply_credential, SSH_CRED_FIELDS  # noqa: PLC0415
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
