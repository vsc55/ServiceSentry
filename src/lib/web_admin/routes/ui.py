#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session / lightweight-API UI routes.  The HTML page views (/, /admin, /overview)
live in :mod:`lib.web_admin.routes.pages`.

Routes registered by this file:

    GET /lang/<code>       switch UI language (persisted to profile on same-origin)
    GET /favicon.ico       the site-root icon browsers request on their own
    GET /api/v1/me         current logged-in user info
    GET /api/v1/health     unauthenticated startup_id (client-side version check)
    GET /api/v1/ui/icons   every icon the bundled font actually has
"""

import io
import os
import re

from flask import jsonify, redirect, request, send_from_directory, session

from lib.debug import DebugLevel
from lib.i18n import SUPPORTED_LANGS


#: Los nombres de icono que trae la fuente, leídos una vez. Son dos mil y el fichero pesa 84 KB:
#: leerlo en cada petición sería releer y volver a recorrer con una expresión regular lo mismo
#: que no cambia hasta que alguien actualice el paquete — y entonces se reinicia el proceso.
_ICONOS: list | None = None


def _iconos_de_la_fuente(base_dir: str) -> list:
    """Todo lo que la fuente vendida sabe dibujar, sacado de su propia hoja de estilos.

    De ahí y no de una lista escrita a mano: la lista se queda vieja en cuanto se actualiza el
    paquete, y lo que da un nombre que la fuente no tiene no es un error — es una clase que no
    aplica nada, así que el botón sale con un hueco y la pantalla parece terminada.
    """
    global _ICONOS                               # pylint: disable=global-statement
    if _ICONOS is None:
        ruta = os.path.join(base_dir, 'static', 'css', 'bootstrap-icons.min.css')
        try:
            with io.open(ruta, encoding='utf-8') as fh:
                css = fh.read()
        except OSError:
            # Sin la hoja no hay catálogo, y eso no puede tumbar nada: lo que se pierde es la
            # lista larga, y queda la corta que va escrita en la pantalla.
            _ICONOS = []
        else:
            _ICONOS = sorted(set(re.findall(r'\.(bi-[a-z0-9-]+)::before', css)))
    return _ICONOS


def register(app, wa):
    login_required = wa._login_required

    @app.route('/api/v1/ui/icons', methods=['GET'])
    @login_required
    def api_ui_icons():
        """Todos los iconos que la fuente trae de verdad.

        **Aparte y no con la página.** Son dos mil nombres, unos 37 KB: mandarlos en cada carga
        del panel es pagarlos siempre para que sirvan cuando alguien abre un selector de iconos.
        Así se piden cuando se despliega la lista larga, una vez por sesión del navegador.
        """
        return jsonify({'icons': _iconos_de_la_fuente(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))})

    @app.route('/lang/<code>')
    def set_lang(code):
        """Switch UI language and persist to user profile."""
        if code in SUPPORTED_LANGS:
            old_lang = session.get('lang', wa._DEFAULT_LANG)
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
            or str(getattr(wa, '_LANDING_PAGE', '') or '')
        if _landing_default not in _hp_ids:
            _landing_default = 'admin'
        return jsonify({
            'username': uname_me,
            'display_name': session.get('display_name', ''),
            'role': session.get('role', 'viewer'),
            'lang': session.get('lang', wa._DEFAULT_LANG),
            'dark_mode': session.get('dark_mode', wa._DEFAULT_DARK_MODE),
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
