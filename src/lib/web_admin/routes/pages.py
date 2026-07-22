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
from ..constants import standalone_pages


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

    def _render_dashboard(standalone: str = ''):
        """Render dashboard.html as the full admin panel (``/admin``, *standalone* empty)
        or as one standalone section page (``/overview``, ``/history``, ``/syslog``): the
        tab bar is hidden and only that section's pane is shown and rendered."""
        html = render_template(
            'dashboard.html',
            standalone=standalone,
            # Registry-driven: the navbar builds its buttons from this and the wiring
            # calls the declared render entry point for the active standalone page.
            standalone_specs=[{'id': p['id'], 'url': p['url'], **p['standalone']}
                              for p in standalone_pages()],
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
        return _render_dashboard()

    # Standalone section pages (Overview / History / Syslog): one generic route per
    # entry in the HOME_PAGES registry, gated by the permission it declares. Adding a
    # page to the registry is enough — no per-page view function here.
    def _make_standalone_view(page: dict):
        spec = page['standalone']

        def _view():
            perms = set(wa._get_effective_permissions(
                session.get('username', ''), session.get('role', '')) or [])
            if spec.get('perm') and spec['perm'] not in perms:
                return redirect(url_for('dashboard'))
            return _render_dashboard(page['id'])

        _view.__name__ = f"page_{page['id']}"
        _view.__doc__ = f"Render the {page['id']} section as its own page."
        return _view

    for _page in standalone_pages():
        app.add_url_rule(_page['url'], endpoint=f"page_{_page['id']}",
                         view_func=login_required(_make_standalone_view(_page)))
