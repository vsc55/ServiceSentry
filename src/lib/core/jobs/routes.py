#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The background-jobs API.

    GET /api/v1/jobs               what this process is running right now
    GET /api/v1/jobs/history       what it has finished, newest first
    GET /api/v1/jobs/history/<uid>  …and everything one of them said while doing it

Three routes, and every one of them is a GET. This screen starts nothing and stops
nothing: every row on it is work another permission already let somebody begin, and the
buttons that begin it live on the screens that own it. A "cancel" here would be a second way
to reach four different pieces of machinery from one place that understands none of them.

The live list and the history are two questions — "what is happening" and "what happened" —
and they are two routes because they come from two places: one is the packages' own memory,
the other is a table written where each piece of work ENDED.
"""

from __future__ import annotations

import time

from flask import jsonify, request

from lib.core.jobs import record as jobs_record
from lib.core.jobs import service as jobs_svc


def register(app, wa):
    """Wire the routes onto the Flask app."""
    jobs_view_req = wa._perm_required('jobs_view')

    @app.route('/api/v1/jobs', methods=['GET'])
    @jobs_view_req
    def api_jobs():
        """Every background job, with the counts a badge is drawn from.

        ``now`` travels with them because "running for 4 minutes" is arithmetic on two clocks
        otherwise — the browser's and the server's — and a laptop whose clock is a minute out
        would show a job that started in the future.
        """
        jobs = jobs_svc.live(wa)
        summary = jobs_svc.summary(jobs)
        # …and how many are in the HISTORY, which is a `COUNT(*)` on a capped table and not
        # the hundred rows themselves. The tab's badge came from the list, so it stayed blank
        # until somebody opened that tab — which is the one moment the number is no longer
        # news. Reported from the screen.
        st = jobs_record.store()
        summary['history'] = st.count() if st is not None else 0
        return jsonify({'jobs': jobs, 'summary': summary, 'now': time.time()})

    @app.route('/api/v1/jobs/history', methods=['GET'])
    @jobs_view_req
    def api_jobs_history():
        """What has finished, newest first — without the logs.

        A hundred rows each carrying a couple of hundred lines is a megabyte of JSON to draw
        a list of names and dates; the log arrives when a row is opened.
        """
        st = jobs_record.store()
        if st is None:
            # Nothing bound a database to write into. Said plainly rather than answered with
            # an empty list, which reads as "nothing has ever run".
            return jsonify({'jobs': [], 'kept': False, 'limits': jobs_record.limits()})
        limit = max(1, min(500, int(request.args.get('limit') or 100)))
        return jsonify({
            'jobs': st.list(limit=limit,
                            kind=str(request.args.get('kind') or ''),
                            state=str(request.args.get('state') or '')),
            'total': st.count(), 'kept': True, 'limits': jobs_record.limits(),
            'now': time.time(),
        })

    @app.route('/api/v1/jobs/history/<uid>', methods=['GET'])
    @jobs_view_req
    def api_jobs_history_one(uid):
        """One finished job, with everything it said while it was working."""
        st = jobs_record.store()
        got = st.get(uid) if st is not None else None
        if not got:
            return jsonify({'error': wa._t('not_found')}), 404
        return jsonify(got)
