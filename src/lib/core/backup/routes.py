#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backup routes: /api/v1/backups.

Routes registered by this file:

    GET    /api/v1/backups                    List the copies on disk + the part catalogue
    GET    /api/v1/backups/browse             Sub-directories of ?path=, for the folder picker
    POST   /api/v1/backups/mkdir              Create a folder from the picker
    GET    /api/v1/backups/tasks              List the scheduled tasks
    PUT    /api/v1/backups/tasks              Create or update one
    DELETE /api/v1/backups/tasks/<uid>        Delete one
    POST   /api/v1/backups/tasks/<uid>/run    Start a run now, as the schedule would
    GET    /api/v1/backups/jobs/<job_id>      How that run is going
    POST   /api/v1/backups/<name>/verify      Check it against its own checksums
    POST   /api/v1/backups                    Start one, by hand (answers a job id)
    GET    /api/v1/backups/<name>/download    Download it
    POST   /api/v1/backups/<name>/restore     Start putting it back (answers a job id)
    DELETE /api/v1/backups/<name>             Delete it

Every one of these is audited, download included: the archive holds the whole install, so
"who took a copy off this machine, and when" is a question the log has to be able to answer.
"""

import os

from flask import jsonify, request, send_file, session

from lib import __version__
from lib.core.backup import schedule as backup_svc_sched
from lib.core.backup import service as backup_svc


def register(app, wa):
    view_req     = wa._perm_required('backup_view')
    create_req   = wa._perm_required('backup_create')
    download_req = wa._perm_required('backup_download')
    restore_req  = wa._perm_required('backup_restore')
    delete_req   = wa._perm_required('backup_delete')
    # The schedule is a decision of its own: who says how often this install is protected and
    # how long its copies are kept. It rode on create/delete, and those are about ARCHIVES —
    # a task edited to run monthly destroys no file and quietly halves the protection.
    schedule_req = wa._perm_required('backup_schedule')
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
            'parts': backup_svc.parts_catalogue(session.get('lang') or wa._DEFAULT_LANG),
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

    @app.route('/api/v1/backups/tasks', methods=['GET'])
    @view_req
    def api_list_backup_tasks():
        """The scheduled tasks. Normalised by the store, so the form and the scheduler read a
        task the same way — a default applied in one of the two is how a task runs weekly on
        the screen and daily on disk."""
        store = getattr(wa, '_backup_tasks_store', None)
        return jsonify({'ok': True, 'tasks': store.list_tasks() if store else []})

    @app.route('/api/v1/backups/tasks', methods=['PUT'])
    @schedule_req
    def api_save_backup_task():
        """Create or update a task — `backup_schedule`, which is the decision being made here:
        not "may I take a copy" but "how often is this install copied, and how many kept".

        The name is checked as the file-name component it becomes: a task called `../etc`
        would otherwise steer where its own copies are written.
        """
        body = request.get_json(silent=True) or {}
        name = str(body.get('name') or '').strip()
        if not name or not backup_svc_sched.task_slug(name):
            return jsonify({'ok': False, 'error': wa._t('backup_task_bad_name')}), 400
        store = getattr(wa, '_backup_tasks_store', None)
        if store is None:
            return jsonify({'ok': False, 'error': wa._t('not_found')}), 404
        # `id`, not `uid`: that is the key JsonDocStore splits a record on. Sending `uid`
        # left the id absent, so every edit minted a new one and "save" quietly meant "add".
        doc = {
            'id': str(body.get('uid') or body.get('id') or '').strip() or None,
            'name': name,
            'enabled': bool(body.get('enabled', True)),
            'mode': (str(body.get('mode') or '').strip()
                     if str(body.get('mode') or '').strip() in backup_svc_sched.MODES
                     else backup_svc_sched.MODE_INTERVAL),
            'every_hours': body.get('every_hours', 24),
            # Normalised HERE as well as in the store: a client that sent 'lunes' or [9] must
            # not be able to store a day nothing will ever match, which is a task that looks
            # scheduled and never runs.
            'days': backup_svc_sched.normalise_days(body.get('days')),
            'at': '%02d:%02d' % backup_svc_sched.parse_at(body.get('at')),
            'parts': body.get('parts') if isinstance(body.get('parts'), list) else [],
            'secrets': bool(body.get('secrets', True)),
            'keep': body.get('keep', 7),
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        uid = store.upsert(doc, actor=session.get('username', ''))
        wa._audit('backup_task_saved', detail={'uid': uid, **{k: doc[k] for k in doc
                                                              if k != 'id'}})
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/backups/tasks/<uid>/run', methods=['POST'])
    @create_req
    def api_run_backup_task(uid: str):
        """Run a task now, through the scheduler's own path.

        Not the generic create: that would produce a copy the task does not own — outside its
        retention counter and not the thing somebody pressing "run" asked to try.
        """
        store = getattr(wa, '_backup_tasks_store', None)
        task = next((t for t in (store.list_tasks() if store else []) if t.get('id') == uid),
                    None)
        if task is None:
            return jsonify({'error': wa._t('not_found')}), 404
        # Started, not awaited. A copy of a large install takes minutes — the syslog table
        # alone is six figures of rows — and a request held open that long is one a browser or
        # a reverse proxy eventually gives up on, leaving the operator unable to tell whether
        # it worked. The browser polls the job id instead, the same shape the MIB compile uses.
        from lib.core.backup.runner import BackupRunner  # noqa: PLC0415
        return jsonify({'ok': True, 'job_id': BackupRunner(wa).start_run(task)})

    @app.route('/api/v1/backups/jobs/<job_id>', methods=['GET'])
    @view_req
    def api_backup_job(job_id: str):
        """How a run started from this process is going.

        A 404 for a job this process does not know is the truth, not an error: jobs live in
        memory, so one started before a restart is genuinely gone and the browser should stop
        asking rather than wait for an answer that will never come.
        """
        from lib.core.backup.runner import job_status  # noqa: PLC0415
        job = job_status(job_id)
        if job is None:
            return jsonify({'error': wa._t('not_found')}), 404
        return jsonify({'ok': True, **job})

    @app.route('/api/v1/backups/tasks/<uid>', methods=['DELETE'])
    @schedule_req
    def api_delete_backup_task(uid: str):
        """Delete a task — the schedule's permission and not `backup_delete`, which is about
        destroying archives. This destroys none; it stops new ones being made."""
        store = getattr(wa, '_backup_tasks_store', None)
        if store is None or not store.delete(uid):
            return jsonify({'error': wa._t('not_found')}), 404
        # The copies it already took are NOT deleted with it: they are backups, and the task
        # was only the reason they exist. Retention stops applying to them, which is the
        # honest consequence of removing the thing that was counting.
        wa._audit('backup_task_deleted', detail={'uid': uid})
        return jsonify({'ok': True})

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

    @app.route('/api/v1/backups/<name>/verify', methods=['POST'])
    @verify_req
    def api_verify_backup(name: str):
        """Check a copy against its own checksums.

        Its own flag rather than riding on `backup_view`: it writes nothing, but it is not
        reading a list either — it walks every member of a multi-gigabyte archive and hashes
        it, which is minutes of disk and CPU that anybody able to see the section could
        otherwise start, as often as they liked.
        """
        res = backup_svc.verify_backup(_var_dir(), name, _backup_dir())
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
            # Every store reads through the connector, so the rows are already the new ones —
            # but anything cached in this process is not. Dropped as soon as the restore
            # worked rather than left for the next request to notice, which is how a restore
            # appears to have done nothing.
            after=lambda: _invalidate_caches(wa),
        )
        return jsonify({'ok': True, 'job_id': job_id})

    @app.route('/api/v1/backups/<name>', methods=['DELETE'])
    @delete_req
    def api_delete_backup(name: str):
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
