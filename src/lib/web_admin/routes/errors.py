#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom HTTP error handlers (400, 403, 404, 405, 500)."""

from flask import jsonify, render_template, request

# (icon, title_i18n_key, desc_i18n_key)
_ERRORS = {
    400: ('bi-exclamation-triangle', 'err_400_title', 'err_400_desc'),
    403: ('bi-lock',                 'err_403_title', 'err_403_desc'),
    404: ('bi-search',               'err_404_title', 'err_404_desc'),
    405: ('bi-slash-circle',         'err_405_title', 'err_405_desc'),
    500: ('bi-bug',                  'err_500_title', 'err_500_desc'),
}


def _wants_json() -> bool:
    """Return True when the client expects a JSON response."""
    return request.path.startswith('/api/') or \
        'application/json' in request.accept_mimetypes.best_match(
            ['application/json', 'text/html'], default='text/html'
        )


def _make_handler(code: int):
    from lib.web_admin.constants import TRANSLATIONS, DEFAULT_LANG

    def handler(e):
        if _wants_json():
            return jsonify({'error': str(e)}), code

        icon, title_key, desc_key = _ERRORS.get(code, ('bi-x-circle', 'err_generic_title', 'err_generic_desc'))

        # Resolve translations using the session lang (falls back to default
        # gracefully — the context processor handles the template vars, but we
        # also need them here to pass as explicit params for safety).
        try:
            from flask import session
            from lib.web_admin.constants import DEFAULT_LANG as _DEFAULT_LANG
            lang = session.get('lang', _DEFAULT_LANG)
            if lang not in TRANSLATIONS:
                lang = DEFAULT_LANG
            trans = TRANSLATIONS[lang]
        except Exception:
            trans = TRANSLATIONS.get(DEFAULT_LANG, {})

        return render_template(
            'error.html',
            code=code,
            icon=icon,
            title=trans.get(title_key, title_key),
            description=trans.get(desc_key, desc_key),
        ), code

    handler.__name__ = f'error_handler_{code}'
    return handler


def register(app, wa):  # noqa: ARG001 — wa kept for interface consistency
    for code in _ERRORS:
        app.register_error_handler(code, _make_handler(code))
