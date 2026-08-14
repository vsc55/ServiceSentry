#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostics routes: /api/v1/diagnostics.

Routes registered by this file:

    GET  /api/v1/diagnostics                 Everything that can be answered locally
    POST /api/v1/diagnostics/update-check    Ask the releases API whether there is a newer one
    POST /api/v1/diagnostics/dependency-check  Ask PyPI and OSV about the installed versions
    GET  /api/v1/diagnostics/report          The same thing as a document: ?format=txt|json|xml

The split is the point: *local* and *remote*. Putting them in one endpoint would make a page
that reads the process wait on a socket somebody's firewall is dropping. The two remote checks
happen when a person presses a button, never on load — and each is audited, because "who made
this box reach out, and when" is a question with an owner.

What each answer CONTAINS lives next door — :mod:`service` (a function of the running panel),
:mod:`collect` (a function of the process and the disk) and :mod:`report` (a function of what
those returned). What is left here is three declarations, a permission and an audit line.
"""

from flask import Response, jsonify, request

from lib import __version__
from lib.core.diagnostics import advisories as diag_advisories
from lib.core.diagnostics import report as diag_report
from lib.core.diagnostics import service as diag_service
from lib.core.diagnostics import update as diag_update


def register(app, wa):
    view_req = wa._perm_required('diagnostics_view')

    def _seen() -> dict:
        """What THIS request looked like, for the network block.

        Gathered here because `service` is Flask-free and this half of the answer exists only
        while a request is being served. `scheme`, `host` and `remote_addr` are already through
        ProxyFix when it is mounted; the `X-Forwarded-*` headers are read RAW beside them, so
        the report can say "a proxy declared https and this panel is ignoring it" — which is a
        different fault from plain HTTP and has a different fix.
        """
        return {
            'scheme': request.scheme,
            'secure': request.is_secure,
            'host': request.host,
            'client_ip': request.remote_addr or '',
            'forwarded_proto': request.headers.get('X-Forwarded-Proto', ''),
            'forwarded_for': request.headers.get('X-Forwarded-For', ''),
            'forwarded_host': request.headers.get('X-Forwarded-Host', ''),
        }

    @app.route('/api/v1/diagnostics', methods=['GET'])
    @view_req
    def api_diagnostics():
        """Everything that can be answered from this process and this disk.

        Not audited. It reads and changes nothing, it is opened precisely when something is
        already wrong, and an entry per refresh would bury the line that matters — the update
        check, which is the one action here with an outside effect.
        """
        return jsonify({'ok': True, **diag_service.payload(wa, _seen())})

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

    @app.route('/api/v1/diagnostics/dependency-check', methods=['POST'])
    @view_req
    def api_diagnostics_dependency_check():
        """What PyPI and OSV.dev say about the versions installed here.

        A POST for the same reason the update check is one: it is not the retrieval of a
        resource, it is *making this machine talk to the internet* — forty small requests to
        pypi.org and one to api.osv.dev — and that belongs behind a verb a browser will not
        issue from a prefetch.

        The package list is built HERE, from the lock and what is installed. A client that
        could name the packages could make the panel query an outside service for anything it
        liked, and the server already has the only list that is correct.

        It is THREE lists: what the lock pins, everything else installed beside it, and what
        only the OTHER processes of this installation run. The second exists because an
        advisory does not care whether a package was pinned — `pip` and `setuptools` run in
        the container too. The third exists because, split across containers, this process is
        the web admin and nothing else, and its packages are not the installation's.

        One round for all three. Asking from each container would put four processes on
        pypi.org for nearly the same question, in exactly the deployment where that is least
        welcome — and the answer says which names came from which list, so the screen can keep
        them apart without deciding it for itself.
        """
        import time                                          # noqa: PLC0415
        rows = diag_service.dependency_rows(wa)
        extra = diag_service.unpinned_rows(wa)
        # And what only the OTHER processes of this installation run. Added to the same round
        # rather than checked from each container: four processes reaching pypi.org to ask
        # nearly the same question is the wrong shape in exactly the deployment where it
        # happens. Contributes nothing when they all came from one image, which is the norm.
        elsewhere = diag_service.elsewhere_rows(wa)
        res = diag_advisories.check(rows + extra + elsewhere)

        def _pins(items):
            # Name AND version. Three lists can name the same package — this process at one
            # version, another container at a different one — and counting by name alone
            # attributes one of them to the wrong list.
            return {(r['name'], str(r.get('installed') or '')) for r in items}

        def _behind(pins):
            return sum(1 for r in res['rows']
                       if (r['name'], r.get('installed', '')) in pins
                       and r.get('state') == 'behind')

        # By name, not by position: the browser holds the answer keyed by name, and a list of
        # indexes into a list it rebuilds is an association waiting to slip.
        res['unpinned'] = [r['name'] for r in extra]
        res['elsewhere'] = [{'name': r['name'], 'installed': r['installed']} for r in elsewhere]
        # "Behind" is split and the advisories are NOT, because they answer different
        # questions. A newer release of a package the lock pins is an action with an owner —
        # regenerate the lock — while a newer `pytest` in a developer's checkout is not, and
        # counting them together turns the one number into something nobody acts on. An
        # advisory has the same weight either way: it is code running on this machine.
        res['behind'] = _behind(_pins(rows))
        res['behind_unpinned'] = _behind(_pins(extra))
        wa._audit('diagnostics_dependencies_checked',
                  detail={'packages': len(rows), 'unpinned': len(extra),
                          'elsewhere': len(elsewhere),
                          'behind': res.get('behind', 0),
                          'vulnerable_packages': res.get('vuln_packages', 0),
                          'advisories': res.get('vuln_total', 0),
                          'vulns_ok': res.get('vulns_ok'),
                          'error': res.get('vulns_error', '')})
        return jsonify({'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'), **res})

    @app.route('/api/v1/diagnostics/report', methods=['GET'])
    @view_req
    def api_diagnostics_report():
        """The same information as a document, in the format the destination wants.

        The screen is for reading and this is for *sending*: nobody transcribes forty fields
        into a bug report, and a screenshot of them cannot be searched or diffed.
        """
        import time                                          # noqa: PLC0415
        body, mimetype, ext = diag_report.render(
            diag_service.payload(wa, _seen()), request.args.get('format'),
            time.strftime('%Y-%m-%d %H:%M:%S'))
        # `inline`, not an attachment: it opens in the tab so it can be read before it is
        # pasted anywhere. Whoever wants a file still gets one with Save As.
        return Response(body, mimetype=f'{mimetype}; charset=utf-8',
                        headers={'Content-Disposition':
                                 f'inline; filename="diagnostics.{ext}"'})
