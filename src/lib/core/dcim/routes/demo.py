#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demonstration data, from Configuration → Maintenance: ``/api/v1/dcim/demo``

    GET    /api/v1/dcim/demo            whether it is installed, which version, and the one
                                        this code would install; the job running, if any
    POST   /api/v1/dcim/demo            install it in the background; ``{"replace": true}``
                                        rebuilds (updates) one already there → ``{job}``
    DELETE /api/v1/dcim/demo            remove it in the background → ``{job}``
    GET    /api/v1/dcim/demo/jobs/<job_id>  how that job is going: its step, its percentage, the
                                        steps done with their counts and times, its result

The same as ``main.py dcim demo`` (and ``--replace``, ``--remove``, ``--status``), for whoever
runs the panel and not a shell. Asked for: an option in Maintenance to add or delete the demo
data, a dialog that says what it is doing at each moment, and knowing whether the installed
demo is the latest.

Behind ``db_maintenance``, the flag of the section it sits in, and not ``dcim_edit``: it writes
and deletes whole sites in one go, which is a maintenance act and not tidying a rack. Only the
sites :mod:`lib.core.dcim.demo` names are ever touched — removing it cannot reach anything a
person entered. Both are audited when they finish.
"""

from __future__ import annotations

from flask import jsonify, request, session

from lib.core.dcim import demo as dcim_demo
from lib.core.dcim import jobs as dcim_jobs


def register(app, wa, C):
    maintenance_req = wa._perm_required('db_maintenance')

    def _dirs() -> dict:
        return {'var_dir': wa._var_dir or '', 'media_dir': C.media_dir()}

    def _who() -> tuple:
        """Who asked, read while there is a request: the job runs on a thread without one."""
        return str(session.get('username') or ''), str(request.remote_addr or '')

    @app.route('/api/v1/dcim/demo', methods=['GET'])
    @maintenance_req
    def api_dcim_demo():
        store = C.store()
        estado = dcim_demo.state(store) if store else {
            'installed': False, 'sites': [], 'version': dcim_demo.DEMO_VERSION,
            'installed_version': None, 'installed_at': None, 'installed_by': None,
            'outdated': False}
        estado['job'] = dcim_jobs.running_job('demo')
        return jsonify(estado)

    @app.route('/api/v1/dcim/demo', methods=['POST'])
    @maintenance_req
    def api_dcim_demo_install():
        store = C.store()
        if not store:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        replace = bool((request.get_json(silent=True) or {}).get('replace'))
        corre = dcim_jobs.running_job('demo')
        if corre:
            return jsonify({'error': wa._t('dcim_demo_busy'), 'job': corre['id']}), 409
        if dcim_demo.find(store) and not replace:
            return jsonify({'error': wa._t('dcim_demo_exists')}), 409
        quien, ip = _who()
        lang, area = wa._lang(), wa._t('dcim_floor_area')
        actor = C.actor()

        def run(report):
            made = dcim_demo.build(store, actor=actor, area_word=area, lang=lang, images=True,
                                   replace=replace, progress=report, app=wa, **_dirs())
            counts = {k: v for k, v in made.items() if k not in dcim_demo.UID_KEYS}
            wa._audit_write('dcim_demo_installed', quien, ip,
                            {'replace': replace, 'counts': counts,
                             'version': dcim_demo.DEMO_VERSION})
            return {'counts': counts, 'version': dcim_demo.DEMO_VERSION}

        job_id, err = dcim_jobs.start_demo('update' if replace else 'install', run, actor=actor)
        if err:
            return jsonify({'error': wa._t(err), 'job': job_id}), 409
        return jsonify({'ok': True, 'job': job_id}), 202

    @app.route('/api/v1/dcim/demo', methods=['DELETE'])
    @maintenance_req
    def api_dcim_demo_remove():
        store = C.store()
        if not store:
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        corre = dcim_jobs.running_job('demo')
        if corre:
            return jsonify({'error': wa._t('dcim_demo_busy'), 'job': corre['id']}), 409
        if not dcim_demo.find(store):
            # Nothing to watch: what a half-finished one left goes now, in the request.
            dcim_demo.remove(store, app=wa, **_dirs())
            return jsonify({'ok': True, 'removed': 0})
        quien, ip = _who()
        lang = wa._lang()

        def run(report):
            prog = dcim_demo.Progress(report, dcim_demo.texts(lang), dcim_demo.REMOVE_STEPS
                                      + ('done',))
            gone = dcim_demo.remove(store, progress=prog, app=wa, **_dirs())
            prog('done')
            wa._audit_write('dcim_demo_removed', quien, ip, {'sites': gone})
            return {'removed': gone}

        job_id, err = dcim_jobs.start_demo('remove', run, actor=C.actor())
        if err:
            return jsonify({'error': wa._t(err), 'job': job_id}), 409
        return jsonify({'ok': True, 'job': job_id}), 202

    @app.route('/api/v1/dcim/demo/jobs/<job_id>', methods=['GET'])
    @maintenance_req
    def api_dcim_demo_job(job_id):
        job = dcim_jobs.job_status(job_id)
        if not job or job.get('type') != 'demo':
            return jsonify({'error': wa._t('dcim_not_found')}), 404
        return jsonify({'job': job})

    _ = (api_dcim_demo, api_dcim_demo_install, api_dcim_demo_remove, api_dcim_demo_job)
