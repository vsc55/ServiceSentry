#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI routes: / (dashboard), /api/v1/me, /api/v1/health, /lang."""

from flask import jsonify, make_response, redirect, render_template, request, session, url_for

from lib.modules import ModuleBase
from lib.util import os_detect
from lib.debug import DebugLevel
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

from lib.i18n import SUPPORTED_LANGS


def register(app, wa):
    login_required = wa._login_required

    @app.route('/lang/<code>')
    def set_lang(code):
        """Switch UI language and persist to user profile."""
        if code in SUPPORTED_LANGS:
            old_lang = session.get('lang', wa._default_lang)
            session['lang'] = code
            # Persist to the user profile + audit ONLY on a same-origin navigation. This
            # GET carries no CSRF token, so a cross-site `<img src="/lang/xx">` must not
            # silently rewrite the victim's stored preference nor spam the audit log
            # (the session-only change is harmless and ephemeral). Header absent on older
            # browsers → treated as same-origin, preserving the previous behaviour.
            if request.headers.get('Sec-Fetch-Site') != 'cross-site':
                uname = session.get('username')
                if uname and uname in wa._users:
                    wa._users[uname]['lang'] = code
                    wa._persist_users()
                if old_lang != code:
                    wa._audit('language_changed', detail={'old': old_lang, 'new': code})
        return redirect(wa._safe_referrer('login'))

    @app.route('/')
    def _root():
        """Entry point: anonymous → /login; logged-in → the user's effective landing
        page (per-user → group → global default), e.g. the admin panel (/admin) or the
        public status page (/status). Same resolution used right after login."""
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        from .auth import _landing_url   # noqa: PLC0415  (avoid import cycle at load)
        user = wa._users.get(session.get('username', ''), {})
        return redirect(_landing_url(wa, user))

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

    @app.route('/api/v1/me', methods=['GET'])
    @login_required
    def api_me():
        """Return current logged-in user info."""
        uname_me = session.get('username', '')
        wa._dbg(f"> Me >> user={uname_me!r} (from session + in-memory _users cache)",
                DebugLevel.debug)
        user_data = wa._users.get(uname_me, {})
        raw_groups = user_data.get('groups', [])
        # _groups is now keyed by uid; return labels as display names
        group_names = [
            wa._uid_to_group_label(g) or g
            for g in raw_groups
            if g in wa._groups
        ]
        # Landing page: the user's own choice ('' = inherit) + what "inherit" resolves to
        # (first group alphabetically with a value → global default), so the account
        # settings modal can show a "Default (…)" option.
        from ..constants import HOME_PAGES as _HOME_PAGES  # noqa: PLC0415
        _hp_ids = {p['id'] for p in _HOME_PAGES}
        _grp_land = sorted(
            ((wa._uid_to_group_label(g) or g, wa._groups[g].get('landing_page', ''))
             for g in raw_groups
             if g in wa._groups and wa._groups[g].get('landing_page')),
            key=lambda x: str(x[0]).lower())
        _landing_default = (_grp_land[0][1] if _grp_land else '') \
            or str(getattr(wa, '_landing_page', '') or '')
        if _landing_default not in _hp_ids:
            _landing_default = 'admin'
        return jsonify({
            'username': uname_me,
            'display_name': session.get('display_name', ''),
            'role': session.get('role', 'viewer'),
            'lang': session.get('lang', wa._default_lang),
            'dark_mode': session.get('dark_mode', wa._default_dark_mode),
            'permissions': list(wa._get_session_permissions()),
            'groups': group_names,
            'pref_lang': user_data.get('lang', ''),
            'pref_landing_page': user_data.get('landing_page', ''),
            'landing_default': _landing_default,
            'pref_dark_mode': user_data.get('dark_mode'),
            'table_config': user_data.get('table_config', {}),
            'dashboard_layout': user_data.get('dashboard_layout', []),
            'modal_config': user_data.get('modal_config', {}),
            'login_id': session.get('session_id', ''),
            'restart_pending': wa._restart_pending,
            'startup_id':      wa._startup_id,
        })

    @app.route('/api/v1/health', methods=['GET'])
    def api_health():
        """Lightweight unauthenticated endpoint for client-side version checks."""
        return jsonify({'startup_id': wa._startup_id})

