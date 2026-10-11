#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The 3D viewer's page: ``/3d``

    GET    /3d    the sites on a map with their state; a site in 3D, the whole building or
                  floor by floor, to walk its floors and go from one site to another

A page and not a section: like ``/status``, it is the whole screen, with no panel around it —
something to leave open on a wall or hand to whoever walks the building. Unlike ``/status`` it
needs a session and ``dcim_view``: it draws every rack, door and lock of the installation.

It reuses the panel's own pieces — the sites map, the site's 3D, the room's and the rack's —
and serves them in a template of its own (``core/view3d/web/explore3d.html``) that loads only
the core, the 3D engine and the inventory. Its data comes from the same ``/api/v1/dcim/*``
routes the panel uses, under the same permissions.
"""

from __future__ import annotations

from flask import make_response, redirect, render_template, session, url_for


def register(app, wa):
    """The page's one route: the page asks the API for everything it draws."""

    @app.route('/3d')
    @wa._login_required
    def dcim_explore3d():
        """The inventory in 3D, as a page of its own: the sites on a map, and each site's
        building and floors in 3D.

        A session is required (``_login_required`` sends a guest to the login), and so is
        ``dcim_view``: without it the page would only draw refusals, so the panel is the
        answer instead.
        """
        if 'dcim_view' not in set(wa._get_session_permissions() or ()):
            return redirect(url_for('dashboard'))
        html = render_template(
            'core/view3d/web/explore3d.html',
            username=session.get('username', ''),
            page_title=wa._t('x3_title'),
        )
        resp = make_response(html)
        # The same as the panel: the page inlines its script, and a cached copy would keep
        # the code of the build it was first loaded with.
        resp.headers['Cache-Control'] = 'no-store, must-revalidate'
        return resp
