#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Experimental Overview rebuilt with Alpine.js — the standalone ``/overview2`` page.

A self-contained proof-of-concept that renders the SAME self-describing Overview widgets
as ``/overview`` (discovered from each domain/service ``overview_widget.py``) and pulls
their REAL data over the existing API (``GET /api/v1/overview/widget/<id>``) — but with an
Alpine.js reactive frontend instead of the hand-rolled DOM code in
``partials/overview/*``.  It is deliberately **additive and isolated**: it registers one
extra GET route, reuses the real permission gate + data endpoints, and touches nothing
else (its own template + the local ``static/js/alpine.min.js``).

Routes registered by this file:

    GET /overview2   experimental Alpine-based Overview (real widgets + real data)
"""

from flask import make_response, render_template, session

from lib.core.overview import service as overview_svc
from lib.core.overview.discovery import discover_overview_widgets_public
from lib.core.roles.overview_widget import role_meta
from lib.security.headers import _CSP

# Alpine.js evaluates its directive expressions with ``new Function()``, which the app's
# global CSP forbids (``script-src`` has ``'unsafe-inline'`` but NOT ``'unsafe-eval'``).
# This experimental page therefore serves its OWN, slightly relaxed CSP that adds
# ``'unsafe-eval'`` — scoped to /overview2 only (``apply_security_headers`` uses
# ``setdefault``, so a header set here is not overridden).  The production UI is plain JS
# and needs no such exception; this is a real trade-off of adopting a runtime-evaluated
# reactive lib under a strict CSP (see the note rendered on the page).
_CSP_ALPINE = _CSP.replace("script-src 'self' 'unsafe-inline'",
                           "script-src 'self' 'unsafe-inline' 'unsafe-eval'")


def register(app, wa):
    login_required = wa._login_required

    @app.route('/overview2')
    @login_required
    def overview2():
        """Render the experimental Alpine Overview: the real, permission-filtered widget
        catalog is injected; the page then fetches each widget's data from the same
        ``/api/v1/overview/widget/<id>`` endpoint the production Overview uses."""
        perms = wa._get_session_permissions()
        widgets = [w for w in discover_overview_widgets_public()
                   if overview_svc.widget_allowed(perms, w)]
        # Inject the caller's own saved dashboard layout for the initial render (no flash),
        # exactly as the production Overview seeds ``currentUser.dashboard_layout``. Edits
        # are persisted back over the same API (PUT /api/v1/users/me/preferences).
        user = wa._users.get(session.get('username', '')) or {}
        saved_layout = user.get('dashboard_layout') or []
        # Shared role metadata (uid -> name/key) so the users/groups by-role badges resolve
        # uids to names, exactly like the production aggregate feeds _dwRoleName.
        rmeta = role_meta(wa)
        html = render_template(
            'overview2.html',
            username=session.get('username', ''),
            overview_widgets=widgets,
            saved_layout=saved_layout,
            role_names=rmeta.get('role_names', {}),
            role_keys=rmeta.get('role_keys', {}),
        )
        resp = make_response(html)
        resp.headers['Cache-Control'] = 'no-store, must-revalidate'
        resp.headers['Content-Security-Policy'] = _CSP_ALPINE   # allow Alpine's new Function()
        return resp
