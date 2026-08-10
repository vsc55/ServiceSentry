#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backup routes: /api/v1/backups.

Routes registered by this file:

    GET    /api/v1/backups                    List the copies on disk + the part catalogue
    GET    /api/v1/backups/browse             Sub-directories of ?path=, for the folder picker
    POST   /api/v1/backups/mkdir              Create a folder from the picker
    POST   /api/v1/backups                    Create one
    GET    /api/v1/backups/<name>/download    Download it
    POST   /api/v1/backups/<name>/restore     Put it back (optionally only some parts)
    DELETE /api/v1/backups/<name>             Delete it

Every one of these is audited, download included: the archive holds the whole install, so
"who took a copy off this machine, and when" is a question the log has to be able to answer.
"""

import os

from flask import jsonify, request, send_file, session

from lib import __version__
from lib.core.backup import service as backup_svc


def register(app, wa):
    view_req     = wa._perm_required('backup_view')
    create_req   = wa._perm_required('backup_create')
    download_req = wa._perm_required('backup_download')
    restore_req  = wa._perm_required('backup_restore')
    delete_req   = wa._perm_required('backup_delete')

    def _var_dir():
        return wa._var_dir or ''

    def _config_dir():
        return getattr(wa, '_config_dir', '') or ''

    def _backup_dir():
        """Where copies are written — `web_admin|backup_dir`, empty meaning <var_dir>/backups.

        Read on every request rather than captured here: an operator who points it at another
        mount must not have to restart the panel, and a value captured at registration would
        write the next copy to the old path and go looking in the new one."""
        return str(getattr(wa, '_BACKUP_DIR', '') or '')

    @app.route('/api/v1/backups', methods=['GET'])
    @view_req
    def api_list_backups():
        """The copies on disk, and what a copy can be made of.

        The catalogue travels WITH the list so the form is drawn from the same declaration the
        service builds from: a part added to `PARTS` appears in the UI without a second list
        to keep in step."""
        return jsonify({
            'ok': True,
            'backups': backup_svc.list_backups(_var_dir(), _backup_dir()),
            'parts': backup_svc.parts_catalogue(),
        })

    @app.route('/api/v1/backups/browse', methods=['GET'])
    @wa._perm_required('config_edit')
    def api_browse_dirs():
        """Sub-directories of ?path=, for the folder picker behind the backup-dir setting.

        Gated on `config_edit` and not on a backup permission: it serves the CONFIG field, and
        whoever may edit that field can already type any path into it and read the outcome back
        from the error. The picker makes visible what the field already allowed — pairing it
        with a weaker permission would be the only way to turn it into a new grant.
        """
        # No ?path= means "start where the copies actually go", not "start at the roots":
        # the picker is opened to change a folder, and the folder in use is the one answer
        # that is always relevant. Falling back to var_dir when it does not exist yet keeps
        # the first open — before any copy has been taken — somewhere real.
        configured = backup_svc.backups_dir(_var_dir(), _backup_dir())
        path = request.args.get('path', '')
        if not path:
            path = configured if os.path.isdir(configured) else _var_dir()
        out = backup_svc.list_dirs(path)
        # The folder the copies go to, travelling with every listing: the picker's left rail
        # offers a way back to it from wherever the operator has wandered, and computing it
        # there would mean the browser doing the `<var_dir>/backups` fallback a second time.
        out['configured'] = configured
        return jsonify(out)

    @app.route('/api/v1/backups/mkdir', methods=['POST'])
    @wa._perm_required('config_edit')
    def api_mkdir():
        """Create a folder from the picker. Same permission as browsing, and for the same
        reason: whoever may point the setting at a path may already make the panel write
        there."""
        body = request.get_json(silent=True) or {}
        res = backup_svc.make_dir(str(body.get('parent') or ''), str(body.get('name') or ''))
        if not res.get('ok'):
            return jsonify({'ok': False, 'error': res.get('message', '')}), 400
        wa._audit('backup_dir_created', detail={'path': res['path']})
        return jsonify(res)

    @app.route('/api/v1/backups', methods=['POST'])
    @create_req
    def api_create_backup():
        body = request.get_json(silent=True) or {}
        name = str(body.get('name') or '').strip()
        if not backup_svc.valid_name(name):
            return jsonify({'ok': False, 'error': wa._t('backup_bad_name')}), 400
        parts = body.get('parts')
        res = backup_svc.create_backup(
            wa._db_connector, name,
            var_dir=_var_dir(), config_dir=_config_dir(), backup_dir=_backup_dir(),
            parts=parts if isinstance(parts, list) else [],
            include_secrets=bool(body.get('secrets')),
            actor=session.get('username', ''), app_version=__version__,
            engine=str(getattr(wa._db_connector, 'driver', '') or ''),
        )
        if not res.get('ok'):
            return jsonify({'ok': False, 'error': res.get('message', '')}), 400
        man = res['manifest']
        wa._audit('backup_created', detail={
            'name': name, 'parts': man.get('parts', []), 'secrets': man.get('secrets'),
            'tables': man.get('tables', {}), 'size': man.get('size', 0),
        })
        return jsonify(res)

    @app.route('/api/v1/backups/<name>/download', methods=['GET'])
    @download_req
    def api_download_backup(name: str):
        stream = backup_svc.archive_bytes(_var_dir(), name, _backup_dir())
        if stream is None:
            return jsonify({'error': wa._t('not_found')}), 404
        # Audited BEFORE the file goes out: a copy that left with the entry unwritten is the
        # one case the log must not have.
        wa._audit('backup_downloaded', detail={'name': name})
        return send_file(stream, mimetype='application/zip', as_attachment=True,
                         download_name=f'{name}.zip')

    @app.route('/api/v1/backups/<name>/restore', methods=['POST'])
    @restore_req
    def api_restore_backup(name: str):
        body = request.get_json(silent=True) or {}
        parts = body.get('parts')
        res = backup_svc.restore_backup(
            wa._db_connector, _var_dir(), name,
            parts=parts if isinstance(parts, list) else None,
            config_dir=_config_dir(), backup_dir=_backup_dir(),
        )
        # Audited either way. A restore that failed half way through is the most important
        # line in the log, not the least — and the tables it did reach are named.
        wa._audit('backup_restored', detail={
            'name': name, 'ok': bool(res.get('ok')),
            'parts': sorted(parts) if isinstance(parts, list) else 'all',
            'tables': res.get('tables', {}),
            'message': res.get('message', ''),
        })
        if not res.get('ok'):
            return jsonify({'ok': False, 'error': res.get('message', '')}), 400
        # Every store reads through the connector, so the rows are already the new ones — but
        # anything cached in this process is not. Invalidated here rather than left to the
        # next request to notice, which is how a restore appears to have done nothing.
        _invalidate_caches(wa)
        return jsonify(res)

    @app.route('/api/v1/backups/<name>', methods=['DELETE'])
    @delete_req
    def api_delete_backup(name: str):
        if not backup_svc.delete_backup(_var_dir(), name, _backup_dir()):
            return jsonify({'error': wa._t('not_found')}), 404
        wa._audit('backup_deleted', detail={'name': name})
        return jsonify({'ok': True})


def _invalidate_caches(wa) -> None:
    """Drop what this process remembers about rows a restore has just replaced.

    Best-effort and deliberately quiet: a cache that cannot be cleared is a stale screen, and
    failing the restore over it would turn a cosmetic problem into a lost one. What it cannot
    fix, a reload of the page does.
    """
    for attr in ('_config_cache', '_perm_cache'):
        try:
            cache = getattr(wa, attr, None)
            if isinstance(cache, dict):
                cache.clear()
        except Exception:      # pylint: disable=broad-except
            continue
