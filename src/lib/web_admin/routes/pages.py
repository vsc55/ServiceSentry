#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML page views: / (entry redirect), /admin (admin panel), /overview (standalone).

The rendered dashboard pulls in the module/host/widget discovery catalogs it needs to build
the UI.  The lighter session/API endpoints (/lang, /api/v1/me, /api/v1/health) live in
:mod:`lib.web_admin.routes.ui`.

Routes registered by this file:

    GET /           entry point: anon → /login, else the user's effective landing page
    GET /admin      the main admin dashboard (all tabs)
    GET /overview   the Overview dashboard as its own page (tabs hidden)
"""

from flask import make_response, redirect, render_template, session, url_for

from lib.modules import ModuleBase
from lib.util import os_detect
from lib.core.hosts.profiles import (
    host_profiles_catalog,
    module_host_collections,
    module_host_fields,
    module_host_multiple,
    module_host_multi_bind,
    module_status_render,
)
from lib.modules.discovery.credential_schemas import credential_schemas
from lib.modules.discovery.overview_widgets import overview_widgets_catalog
from lib.core.overview.discovery import discover_overview_widgets_public as _discover_overview_widgets


def register(app, wa):
    login_required = wa._login_required

    @app.route('/')
    def _root():
        """Entry point: anonymous → /login; logged-in → the user's effective landing
        page (per-user → group → global default), e.g. the admin panel (/admin) or the
        public status page (/status). Same resolution used right after login."""
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        user = wa._users.get(session.get('username', ''), {})
        return redirect(wa._landing_url(user))

    def _render_dashboard(overview_page: bool):
        """Render dashboard.html either as the full admin panel (``/admin``) or as the
        standalone Overview page (``/overview``, tabs hidden, only the widget grid)."""
        html = render_template(
            'dashboard.html',
            overview_page=overview_page,
            username=session.get('username', ''),
            display_name=session.get('display_name', ''),
            role=session.get('role', 'viewer'),
            item_schemas=ModuleBase.discover_schemas(wa._modules_dir),
            host_profiles=host_profiles_catalog(wa._modules_dir),
            credential_types=credential_schemas(wa._modules_dir),
            module_host_fields=module_host_fields(wa._modules_dir),
            module_host_collections=module_host_collections(wa._modules_dir),
            module_host_multiple=module_host_multiple(wa._modules_dir),
            module_host_multi_bind=module_host_multi_bind(wa._modules_dir),
            module_widgets=overview_widgets_catalog(wa._modules_dir),
            overview_widgets=_discover_overview_widgets(),
            module_status_render=module_status_render(wa._modules_dir),
            host_os_options=list(os_detect.OPTIONS),
            local_os=os_detect.local_os(),
        )
        # Never cache the dashboard: it embeds the server's startup_id (used by the
        # reload banner) and the inlined app JS, so a reload must always fetch a
        # fresh copy — otherwise a stale cached page keeps the banner up forever.
        resp = make_response(html)
        resp.headers['Cache-Control'] = 'no-store, must-revalidate'
        return resp

    @app.route('/admin')
    @login_required
    def dashboard():
        """Render the main admin dashboard (all tabs)."""
        return _render_dashboard(False)

    @app.route('/overview')
    @login_required
    def overview():
        """Render the Overview dashboard as its own page (separate from the admin panel)."""
        return _render_dashboard(True)
