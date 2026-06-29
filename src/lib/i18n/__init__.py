#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application-wide internationalisation loader.

Shared by the web admin (UI labels) and the Flask-free notification subsystem
(:mod:`lib.notify` e-mail templates), so translations live in the general
library rather than under the web layer.

Translations are stored as individual Python modules inside the ``lang/``
package (one file per language, e.g. ``lang/en_EN.py``).  Each module must
expose a ``LANG`` dictionary with the translation strings.

Adding a new language only requires dropping a new ``<code>.py`` file into
``lang/`` — the loader picks it up automatically.
"""

import importlib
import pkgutil

from lib.i18n import lang as _lang_pkg

__all__ = ['SUPPORTED_LANGS', 'DEFAULT_LANG', 'TRANSLATIONS', 'coerce_lang', 'translate']

DEFAULT_LANG = 'en_EN'

# Auto-discover every module inside the ``lang`` package.
TRANSLATIONS: dict[str, dict] = {}

for _finder, _name, _ispkg in pkgutil.iter_modules(_lang_pkg.__path__):
    _mod = importlib.import_module(f'lib.i18n.lang.{_name}')
    _data = getattr(_mod, 'LANG', None)
    if isinstance(_data, dict):
        TRANSLATIONS[_name] = _data

SUPPORTED_LANGS: tuple[str, ...] = tuple(sorted(TRANSLATIONS))


def coerce_lang(value, default: str = '') -> str:
    """Return *value* if it is a supported language code, else *default*.

    Single home for the ``x if x in SUPPORTED_LANGS else fallback`` pattern.
    The chosen *default* selects the semantics:
      * ``coerce_lang(x, DEFAULT_LANG)`` — fall back to the default language
      * ``coerce_lang(x, '')``          — empty means "use the default" (status_lang)
      * ``coerce_lang(x, current)``     — keep the current value if x is invalid
    """
    return value if value in SUPPORTED_LANGS else default


def translate(lang: str, key: str, *args) -> str:
    """Translate *key* into *lang* (falling back to the default language and then
    to the key itself), filling each ``{}`` placeholder with *args* in order.

    Flask-free, instance-free — for console/daemon messages where the web app's
    request-bound translator is unavailable (see :meth:`WebAdmin._t`)."""
    text = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG]).get(key, key)
    for arg in args:
        text = text.replace('{}', str(arg), 1)
    return text
