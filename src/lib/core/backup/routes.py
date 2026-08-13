#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backup routes: /api/v1/backups.

Routes registered by this file:

    GET    /api/v1/backups                    List the copies on disk + the part catalogue
    GET    /api/v1/backups/browse             Sub-directories of ?path=, for the folder picker
    POST   /api/v1/backups/mkdir              Create a folder from the picker
    GET    /api/v1/backups/jobs/<job_id>      How that run is going
    GET    /api/v1/backups/<name>/tables      What it holds, by part and table
    POST   /api/v1/backups/<name>/verify      Check it against its own checksums
    POST   /api/v1/backups/<name>/lock        Protect it from deletion, or stop protecting it
    POST   /api/v1/backups                    Start one, by hand (answers a job id)
    GET    /api/v1/backups/<name>/download    Download it
    POST   /api/v1/backups/<name>/restore     Start putting it back (answers a job id)
    DELETE /api/v1/backups/<name>             Delete it

The SCHEDULE — tasks and retention profiles — lives in `routes_schedule.py` and is registered
from here: it is its own decision with its own permission. This file is about archives; that
one is about how often the install is protected.

Every one of these is audited, download included: the archive holds the whole install, so
"who took a copy off this machine, and when" is a question the log has to be able to answer.
"""

import os

from flask import jsonify, request, send_file, session

from lib import __version__
from lib.core.backup import archive as backup_archive
from lib.core.backup import folders as backup_folders
from lib.core.backup import locks as backup_locks
from lib.core.backup import parts as backup_parts
from lib.core.backup import restore as backup_restore
from lib.core.backup import routes_schedule
from lib.core.backup import service as backup_svc
from lib.core.backup import verify as backup_verify


def register(app, wa):
    view_req     = wa._perm_required('backup_view')
    create_req   = wa._perm_required('backup_create')
    download_req = wa._perm_required('backup_download')
    restore_req  = wa._perm_required('backup_restore')
    delete_req   = wa._perm_required('backup_delete')
    # Verifying is not reading the list: it walks every member of the archive and hashes it.
    verify_req   = wa._perm_required('backup_verify')

    def _var_dir():
        return wa._var_dir or ''

    def _backup_dir():
        """Where copies are written — `web_admin|backup_dir`, empty meaning <var_dir>/backups.

        Read on every request rather than captured here: an operator who points it at another
        mount must not have to restart the panel, and a value captured at registration would
        write the next copy to the old path and go looking in the new one."""
        return str(getattr(wa, '_BACKUP_DIR', '') or '')

    # The schedule's endpoints, handed the two helpers above rather than a second copy of them.
    routes_schedule.register(app, wa, _var_dir, _backup_dir)

    @app.route('/api/v1/backups', methods=['GET'])
    @view_req
    def api_list_backups():
        """The copies on disk, and what a copy can be made of.

        The catalogue travels WITH the list so the form is drawn from the same declaration the
        service builds from: a part added to `PARTS` — or declared by a module, which is how
        anything module-specific gets in here — appears in the UI without a second list to
        keep in step.

        The language goes in because a module's part is labelled from the module's own lang
        files, which the browser's catalogue does not hold."""
        return jsonify({
            'ok': True,
            'backups': backup_svc.list_backups(_var_dir(), _backup_dir(), __version__),
            'parts': backup_parts.parts_catalogue(session.get('lang') or wa._DEFAULT_LANG),
            # What this install is, so the restore dialog can say which way the jump goes
            # instead of showing a build number the operator has to compare in their head.
            'version': __version__,
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
        configured = backup_archive.backups_dir(_var_dir(), _backup_dir())
        path = request.args.get('path', '')
        if not path:
            path = configured if os.path.isdir(configured) else _var_dir()
        out = backup_folders.list_dirs(path)
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
        res = backup_folders.make_dir(str(body.get('parent') or ''), str(body.get('name') or ''))
        if not res.get('ok'):
            return jsonify({'ok': False, 'error': res.get('message', '')}), 400
        wa._audit('backup_dir_created', detail={'path': res['path']})
        return jsonify(res)

    @app.route('/api/v1/backups', methods=['POST'])
    @create_req
    def api_create_backup():
        body = request.get_json(silent=True) or {}
        name = str(body.get('name') or '').strip()
        if not backup_archive.valid_name(name):
            return jsonify({'ok': False, 'error': wa._t('backup_bad_name')}), 400
        parts = body.get('parts')
        # Started, not awaited — the same treatment the scheduled runs get, and for the same
        # reason: a copy of a large install takes minutes, and a hand-made one is watched by
        # somebody standing there. Held open, it showed nothing at all until it was over.
        # The audit line is written by the job, with the actor and the address read HERE:
        # there is no request on the thread that will need them.
        from lib.core.backup.runner import BackupRunner  # noqa: PLC0415
        job_id = BackupRunner(wa).start_manual(
            name, parts if isinstance(parts, list) else [], bool(body.get('secrets')),
            session.get('username', ''), request.remote_addr or '',
        )
        return jsonify({'ok': True, 'job_id': job_id})

    @app.route('/api/v1/backups/jobs/<job_id>', methods=['GET'])
    @view_req
    def api_backup_job(job_id: str):
        """How a run started from this process is going.

        A 404 for a job this process does not know is the truth, not an error: jobs live in
        memory, so one started before a restart is genuinely gone and the browser should stop
        asking rather than wait for an answer that will never come.
        """
        from lib.core.backup.jobs import job_status  # noqa: PLC0415
        job = job_status(job_id)
        if job is None:
            return jsonify({'error': wa._t('not_found')}), 404
        return jsonify({'ok': True, **job})

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

    @app.route('/api/v1/backups/<name>/tables', methods=['GET'])
    @view_req
    def api_backup_tables(name: str):
        """What one copy holds, grouped by part — what the restore form's advanced half offers.

        `backup_view`, which is what the listing already grants: every manifest travels with
        its `tables` map, so the names and the row counts are on screen before this is asked
        for. What this adds is the GROUPING, and the reason it is a route rather than a few
        lines of JavaScript is that `core` means "every table nobody else claimed" — a rule
        that already decides what a copy holds and what a restore applies, and must not get a
        third implementation in the browser.

        Read when the advanced panel is opened, not with the list: it opens one archive, and
        doing it for every copy on the shelf would make drawing the section pay for a fold
        most people never unfold.
        """
        res = backup_restore.archive_contents(_var_dir(), name, _backup_dir())
        if not res.get('ok'):
            return jsonify({'ok': False, 'error': res.get('message', '')}), 404
        return jsonify(res)

    @app.route('/api/v1/backups/<name>/verify', methods=['POST'])
    @verify_req
    def api_verify_backup(name: str):
        """Check a copy against its own checksums.

        Its own flag rather than riding on `backup_view`: it writes nothing, but it is not
        reading a list either — it walks every member of a multi-gigabyte archive and hashes
        it, which is minutes of disk and CPU that anybody able to see the section could
        otherwise start, as often as they liked.
        """
        res = backup_verify.verify_backup(_var_dir(), name, _backup_dir())
        if 'message' in res:
            return jsonify({'ok': False, 'error': res['message']}), 404
        wa._audit('backup_verified', detail={'name': name, 'ok': res['ok'],
                                             'file': res.get('file'),
                                             'bad': res.get('bad', [])})
        return jsonify(res)

    @app.route('/api/v1/backups/<name>/restore', methods=['POST'])
    @restore_req
    def api_restore_backup(name: str):
        body = request.get_json(silent=True) or {}
        parts = body.get('parts')
        # The advanced half: named tables inside those parts. Absent means "all of them", which
        # is every caller that predates this — and an empty LIST means none, which the service
        # honours rather than reading as "everything". A client that sends `tables: []` has
        # asked for no table at all, and rewriting the whole install for it would be the one
        # mistake this endpoint cannot make.
        tables = body.get('tables')
        # Asked here and not inside the job: "there is no such copy" is an answer to THIS
        # request, and finding it out on a thread would put a progress bar on screen for
        # something that was never going to happen. Audited all the same — an attempt to
        # restore something is worth a line whether or not it existed.
        if not backup_svc.backup_exists(_var_dir(), name, _backup_dir()):
            wa._audit('backup_restored', detail={'name': name, 'ok': False,
                                                 'message': 'backup not found'})
            return jsonify({'ok': False, 'error': wa._t('not_found')}), 400
        # Started, not awaited — the same treatment the copies get. A restore rewrites every
        # table in one transaction, so it is the longest thing this section does, and a request
        # held open for it is one a proxy gives up on while the install is being overwritten.
        # The audit line and the cache drop happen on the job, with the actor read HERE:
        # there is no request on the thread that will need it.
        from lib.core.backup.runner import BackupRunner  # noqa: PLC0415
        job_id = BackupRunner(wa).start_restore(
            name, parts, session.get('username', ''), request.remote_addr or '',
            tables=tables if isinstance(tables, list) else None,
            # Every store reads through the connector, so the rows are already the new ones —
            # but anything cached in this process is not. Dropped as soon as the restore
            # worked rather than left for the next request to notice, which is how a restore
            # appears to have done nothing.
            after=lambda: _invalidate_caches(wa),
        )
        return jsonify({'ok': True, 'job_id': job_id})

    @app.route('/api/v1/backups/<name>/lock', methods=['POST'])
    @delete_req
    def api_lock_backup(name: str):
        """Protect a copy from being deleted, or stop protecting it.

        `backup_delete`, in BOTH directions, and that is the honest mapping: the lock only ever
        affects whether an archive can be destroyed. Unlocking is asking to be able to delete
        it, so it cannot be a weaker grant than deleting — and locking, the harmless half, would
        be a strange thing to hand to somebody who may not delete anything anyway.

        What it is NOT: protection from an administrator. Whoever may unlock may then delete.
        It is a guard rail against retention and against the wrong row — which is what loses the
        copy taken before a migration.
        """
        body = request.get_json(silent=True) or {}
        locked = bool(body.get('locked', True))
        res = backup_locks.set_lock(_var_dir(), name, locked,
                                    actor=session.get('username', ''),
                                    backup_dir=_backup_dir())
        if not res.get('ok'):
            return jsonify({'ok': False, 'error': res.get('message', '')}), 400
        # Both directions audited under one key: the interesting case is somebody removing a
        # protection another person put there, and a single key keeps both sides of that in one
        # filter instead of two.
        wa._audit('backup_locked', detail={'name': name, 'locked': locked})
        return jsonify(res)

    @app.route('/api/v1/backups/<name>', methods=['DELETE'])
    @delete_req
    def api_delete_backup(name: str):
        # Answered before the attempt so the refusal can say WHY. `delete_backup` refuses a
        # locked copy on its own — that is the guard that holds for every caller — but it can
        # only answer False, and "not found" would be a lie about a file that is right there.
        if backup_locks.is_locked(_var_dir(), name, _backup_dir()):
            return jsonify({'ok': False, 'error': wa._t('backup_locked_refused')}), 409
        if not backup_svc.delete_backup(_var_dir(), name, _backup_dir()):
            return jsonify({'error': wa._t('not_found')}), 404
        wa._audit('backup_deleted', detail={'name': name})
        return jsonify({'ok': True})


def _invalidate_caches(wa) -> None:
    """Drop what this process remembers about rows a restore has just replaced, and tell the
    other processes to look again.

    A restore replaces the whole `config` table, so on a multi-container install every worker
    is running against settings that no longer exist. They converge on their own — each polls
    the shared database every 15 seconds — but the panel already has a way to say "now", and it
    is the same one a config save uses. Fifteen seconds of a scheduler running the old check
    list is not a disaster; it is just a wait nobody needed to have.

    Best-effort and deliberately quiet throughout: a cache that cannot be cleared is a stale
    screen, and failing the restore over it would turn a cosmetic problem into a lost one. What
    it cannot fix, a reload of the page does.
    """
    for attr in ('_config_cache', '_perm_cache'):
        try:
            cache = getattr(wa, attr, None)
            if isinstance(cache, dict):
                cache.clear()
        except Exception:      # pylint: disable=broad-except
            continue
    # Every service, not the ones whose section "changed": a restore replaced all of them.
    try:
        for key in list(getattr(wa, '_embedded_services', {}) or {}):
            wa._poke_service_instances(key)
    except Exception:      # pylint: disable=broad-except
        pass
