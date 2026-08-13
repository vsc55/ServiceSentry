#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backup routes: the SCHEDULE — tasks and shared retention profiles.

Routes registered by this file:

    GET    /api/v1/backups/tasks              List the scheduled tasks
    PUT    /api/v1/backups/tasks              Create or update one
    DELETE /api/v1/backups/tasks/<uid>        Delete one
    POST   /api/v1/backups/tasks/preview      What a retention policy would keep / delete
    POST   /api/v1/backups/tasks/<uid>/run    Start a run now, as the schedule would
    GET    /api/v1/backups/profiles           List the shared retention profiles
    PUT    /api/v1/backups/profiles           Create or update one
    DELETE /api/v1/backups/profiles/<uid>     Delete one (refused while a task follows it)

Its own module because it is its own DECISION, with its own permission: `routes.py` is about
archives — making one, fetching one, putting one back, destroying one — and this is about how
often the install is protected and how much history is kept. A task edited to run monthly
destroys no file and quietly halves the protection, which is why `backup_schedule` exists and
why these do not ride on create/delete.

The exception is "run now", which is `backup_create`: running a task makes a copy, and one
grant should not be two ways to the same result.

`_var_dir` and `_backup_dir` are handed in by `routes.py` rather than rebuilt here — they read
the panel's own settings on every request, and a second copy of that rule is a second thing to
keep in step.
"""

from flask import jsonify, request, session

from lib.core.backup import schedule as backup_svc_sched
from lib.core.backup import service as backup_svc


def register(app, wa, _var_dir, _backup_dir):
    view_req     = wa._perm_required('backup_view')
    # Running a task is making a copy: the same grant the Create button needs.
    create_req   = wa._perm_required('backup_create')
    # The schedule is a decision of its own: who says how often this install is protected and
    # how long its copies are kept. It rode on create/delete, and those are about ARCHIVES —
    # a task edited to run monthly destroys no file and quietly halves the protection.
    schedule_req = wa._perm_required('backup_schedule')

    @app.route('/api/v1/backups/tasks', methods=['GET'])
    @view_req
    def api_list_backup_tasks():
        """The scheduled tasks. Normalised by the store, so the form and the scheduler read a
        task the same way — a default applied in one of the two is how a task runs weekly on
        the screen and daily on disk."""
        store = getattr(wa, '_backup_tasks_store', None)
        tasks = store.list_tasks() if store else []
        profiles = _profiles()
        return jsonify({
            'ok': True,
            'tasks': tasks,
            # The rules that actually apply to each task, resolved by the same function the
            # scheduler uses. A task following a profile carries two sets of numbers — its own
            # and the profile's — and a screen that picked between them itself would be a
            # retention screen guessing at what is about to be deleted.
            'policies': {t.get('id'): {k: backup_svc_sched.with_profile(t, profiles).get(k, 0)
                                       for k in backup_svc_sched.RETENTION_KEYS}
                         for t in tasks},
        })

    def _profiles() -> list:
        store = getattr(wa, '_backup_profiles_store', None)
        return store.list_profiles() if store is not None else []

    @app.route('/api/v1/backups/profiles', methods=['GET'])
    @view_req
    def api_list_backup_profiles():
        """The shared retention profiles, and the starting points the editor offers.

        `suggested` comes from the server for the same reason the part catalogue does: it is the
        panel's opinion about how much history is worth keeping, and an opinion written into a
        template is one the API cannot state and no test can read.
        """
        from lib.core.backup.profiles_store import SUGGESTED  # noqa: PLC0415
        return jsonify({
            'ok': True,
            'profiles': _profiles(),
            # How many tasks follow each one. Sent rather than counted in the browser because it
            # is the sentence the editor needs before saving — "this changes 3 tasks" — and a
            # count taken from a list the screen happens to be holding is a count that is right
            # until somebody else adds a task.
            'used_by': _profile_usage(),
            'suggested': [{**s, 'label': wa._t(s['key'])} for s in SUGGESTED],
        })

    def _profile_usage() -> dict:
        """`{profile_uid: [task name, …]}` — who would be affected by editing one."""
        store = getattr(wa, '_backup_tasks_store', None)
        out: dict = {}
        for task in (store.list_tasks() if store else []):
            uid = str(task.get('profile') or '')
            if uid:
                out.setdefault(uid, []).append(task.get('name', ''))
        return out

    @app.route('/api/v1/backups/profiles', methods=['PUT'])
    @schedule_req
    def api_save_backup_profile():
        """Create or update a profile — `backup_schedule`, the same decision editing a task's
        retention is, and now taken for every task that follows it at once."""
        body = request.get_json(silent=True) or {}
        name = str(body.get('name') or '').strip()
        if not name:
            return jsonify({'ok': False, 'error': wa._t('backup_profile_bad_name')}), 400
        store = getattr(wa, '_backup_profiles_store', None)
        if store is None:
            return jsonify({'ok': False, 'error': wa._t('not_found')}), 404
        uid_in = str(body.get('uid') or body.get('id') or '').strip()
        # Merged over what is stored, not written from the body alone. A record is REPLACED by
        # an upsert, so a caller that sent only a new name would leave the profile on today's
        # defaults — silently changing how much history every task following it keeps. One task
        # saved short is a mistake somebody can see; this one is invisible and multiplied.
        current = next((p for p in _profiles() if p.get('id') == uid_in), {}) if uid_in else {}
        doc = {
            **{k: current[k] for k in backup_svc_sched.RETENTION_KEYS if k in current},
            'id': uid_in or None,
            'name': name,
            **{k: body[k] for k in backup_svc_sched.RETENTION_KEYS if k in body},
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        uid = store.upsert(doc, actor=session.get('username', ''))
        # The tasks it affects go in the line: a profile edited to keep four weeklies instead of
        # eight halves the history of every task following it, and the log should not make
        # somebody cross-reference which those were at the time.
        wa._audit('backup_profile_saved',
                  detail={'uid': uid, 'tasks': _profile_usage().get(uid, []),
                          **{k: doc[k] for k in doc if k != 'id'}})
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/backups/profiles/<uid>', methods=['DELETE'])
    @schedule_req
    def api_delete_backup_profile(uid: str):
        """Delete a profile — refused while a task still follows it.

        The alternative was to let it go and have those tasks fall back to their own stored
        numbers, which is what happens if a row disappears some other way. As an ANSWER to a
        button, though, it is a silent change of policy on tasks nobody was looking at: the
        deletion succeeds, the screen says nothing, and how much history three tasks keep is now
        whatever they happened to hold before they were linked. Saying "three tasks follow this"
        costs one more click and no surprises.
        """
        used = _profile_usage().get(uid, [])
        if used:
            return jsonify({'ok': False,
                            'error': wa._t('backup_profile_in_use').replace(
                                '{}', ', '.join(used))}), 409
        store = getattr(wa, '_backup_profiles_store', None)
        if store is None or not store.delete(uid):
            return jsonify({'error': wa._t('not_found')}), 404
        wa._audit('backup_profile_deleted', detail={'uid': uid})
        return jsonify({'ok': True})

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
            # Retention, bucket by bucket. Only what the caller actually sent: a task saved by
            # an older client keeps whatever it had rather than acquiring today's defaults —
            # and `keep`, the single counter this replaced, is still accepted and still means
            # "the newest N", because an API that was working must go on working.
            **{k: body[k] for k in (*backup_svc_sched.RETENTION_KEYS, 'keep') if k in body},
            # Which profile this task follows, '' meaning its own numbers. Only when the caller
            # said something: absent must not read as "unlink", or a client that predates
            # profiles would quietly detach every task it saves.
            **({'profile': str(body.get('profile') or '').strip()} if 'profile' in body else {}),
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        uid = store.upsert(doc, actor=session.get('username', ''))
        wa._audit('backup_task_saved', detail={'uid': uid, **{k: doc[k] for k in doc
                                                              if k != 'id'}})
        return jsonify({'ok': True, 'uid': uid})

    @app.route('/api/v1/backups/tasks/preview', methods=['POST'])
    @view_req
    def api_preview_retention():
        """What a retention policy would keep and delete, on the copies that exist today.

        A bucket policy is not something anybody can evaluate in their head — "7 daily + 4
        weekly + 6 monthly" against 200 files is exactly the kind of arithmetic people get
        wrong and then trust. So the form shows it, computed by the SAME pure function the
        scheduler uses: a preview worked out a second way would be a preview that lies on the
        day it matters.

        `backup_view`, and a POST because the policy travels in the body: it answers a
        question about the copies already on disk and changes nothing.

        A body naming a `profile` is resolved exactly as the scheduler resolves a task, so the
        preview of a task that follows a profile shows the profile's rules and not the numbers
        the form still has in its boxes.
        """
        body = request.get_json(silent=True) or {}
        name = str(body.get('name') or '').strip()
        rows = backup_svc.list_backups(_var_dir(), _backup_dir())
        mine = [b for b in rows if backup_svc_sched.is_auto(b.get('name'), name)]
        policy = backup_svc_sched.with_profile(body, _profiles())
        doomed = set(backup_svc_sched.prune(rows, policy, name))
        # The size is what makes a budget legible: "22 copies, 4.1 GiB" is the sentence the
        # number in the box is trying to be.
        kept = [b for b in mine if b['name'] not in doomed]
        return jsonify({
            'ok': True,
            'total': len(mine),
            'keep': [{'name': b['name'], 'mtime': b.get('mtime'), 'size': b.get('size'),
                      'size_h': b.get('size_h'), 'status': b.get('status')} for b in kept],
            'delete': [{'name': b['name'], 'mtime': b.get('mtime'), 'size': b.get('size'),
                        'size_h': b.get('size_h'), 'status': b.get('status')}
                       for b in mine if b['name'] in doomed],
            'keep_bytes': sum(int(b.get('size') or 0) for b in kept),
        })

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
