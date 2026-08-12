#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostics routes: /api/v1/diagnostics.

Routes registered by this file:

    GET  /api/v1/diagnostics               Everything that can be answered locally
    POST /api/v1/diagnostics/update-check  Ask the releases API whether there is a newer one
    GET  /api/v1/diagnostics/report        The same thing as a document: ?format=txt|json|xml

The split between the first two is the point: *local* and *remote*. Putting them in one
endpoint would make a page that reads the process wait on a socket somebody's firewall is
dropping. The check happens when a person presses a button, never on load.

What each answer CONTAINS lives next door — :mod:`service` (a function of the running panel),
:mod:`collect` (a function of the process and the disk) and :mod:`report` (a function of what
those returned). What is left here is three declarations, a permission and an audit line.
"""

from flask import Response, jsonify, request

from lib import __version__
from lib.core.diagnostics import report as diag_report
from lib.core.diagnostics import service as diag_service
from lib.core.diagnostics import update as diag_update


def register(app, wa):
    view_req = wa._perm_required('diagnostics_view')

    @app.route('/api/v1/diagnostics', methods=['GET'])
    @view_req
    def api_diagnostics():
        """Everything that can be answered from this process and this disk.

        Not audited. It reads and changes nothing, it is opened precisely when something is
        already wrong, and an entry per refresh would bury the line that matters — the update
        check, which is the one action here with an outside effect.
        """
        return jsonify({'ok': True, **diag_service.payload(wa)})

    @app.route('/api/v1/diagnostics/update-check', methods=['POST'])
    @view_req
    def api_diagnostics_update_check():
        """Ask the releases API whether a newer version is published.

        A POST for something that reads: it is not the retrieval of a resource, it is *making
        this machine talk to the internet*, and that belongs behind a verb a browser will not
        issue on its own from a prefetch or a link.
        """
        import time                                          # noqa: PLC0415
        res = diag_update.fetch_latest(diag_service.update_url(wa))
        out = {'ok': bool(res.get('ok')),
               'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'), **res}
        if res.get('ok'):
            out['compare'] = diag_update.compare(__version__, res.get('tag', ''))
        # Audited either way: on a segregated network "who made this box reach out, and when"
        # is a question with an owner, and a check that failed still made the attempt.
        wa._audit('diagnostics_update_checked',
                  detail={'url': res.get('url', ''), 'ok': bool(res.get('ok')),
                          'latest': res.get('tag', ''), 'error': res.get('error', '')})
        return jsonify(out)

    @app.route('/api/v1/diagnostics/report', methods=['GET'])
    @view_req
    def api_diagnostics_report():
        """The same information as a document, in the format the destination wants.

        The screen is for reading and this is for *sending*: nobody transcribes forty fields
        into a bug report, and a screenshot of them cannot be searched or diffed.
        """
        import time                                          # noqa: PLC0415
        body, mimetype, ext = diag_report.render(
            diag_service.payload(wa), request.args.get('format'),
            time.strftime('%Y-%m-%d %H:%M:%S'))
        # `inline`, not an attachment: it opens in the tab so it can be read before it is
        # pasted anywhere. Whoever wants a file still gets one with Save As.
        return Response(body, mimetype=f'{mimetype}; charset=utf-8',
                        headers={'Content-Disposition':
                                 f'inline; filename="diagnostics.{ext}"'})
