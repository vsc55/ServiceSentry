#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Internationalisation loader for the web administration panel.

Translations are stored as individual Python modules inside the
``lang/`` package (one file per language, e.g. ``lang/en.py``).  Each
module must expose a ``LANG`` dictionary with the translation strings.

Adding a new language only requires dropping a new ``<code>.py`` file
into ``lang/`` — the loader picks it up automatically.
"""

import importlib
import pkgutil

from lib.web_admin import lang as _lang_pkg

__all__ = ['SUPPORTED_LANGS', 'DEFAULT_LANG', 'TRANSLATIONS']

DEFAULT_LANG = 'en'

# Auto-discover every module inside the ``lang`` package.
TRANSLATIONS: dict[str, dict] = {}

for _finder, _name, _ispkg in pkgutil.iter_modules(_lang_pkg.__path__):
    _mod = importlib.import_module(f'lib.web_admin.lang.{_name}')
    _data = getattr(_mod, 'LANG', None)
    if isinstance(_data, dict):
        TRANSLATIONS[_name] = _data

SUPPORTED_LANGS: tuple[str, ...] = tuple(sorted(TRANSLATIONS))
