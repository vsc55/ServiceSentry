#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session / lightweight-API UI routes.  The HTML page views (/, /admin, /overview)
live in :mod:`lib.web_admin.routes.pages`.

Routes registered by this file:

    GET /lang/<code>       switch UI language (persisted to profile on same-origin)
    GET /favicon.ico       the site-root icon browsers request on their own
    GET /api/v1/me         current logged-in user info
    GET /api/v1/health     unauthenticated startup_id (client-side version check)
"""

import os

from flask import jsonify, redirect, request, send_from_directory, session

from lib.debug import DebugLevel
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

    @app.route('/favicon.ico')
    def favicon():
        """The icon a browser fetches from the site ROOT, on its own.

        The ``<link rel="icon">`` tags in ``base.html`` cover a rendered page, but the
        request for ``/favicon.ico`` is made regardless — and on responses that are not a
        page of ours at all (an error page, a JSON endpoint opened in a tab). Without this it
        404s on every visit: harmless, and noise in the access log of every deployment.

        Public and cacheable: it is a static image, it identifies nothing, and requiring a
        session for it would 302 the browser to the login page and hand it an HTML document
        where an icon belongs.
        """
        resp = send_from_directory(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'static', 'img'),
            'favicon.ico', mimetype='image/x-icon')
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

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
