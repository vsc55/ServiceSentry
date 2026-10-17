#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application-wide internationalisation loader.

Shared by the web admin (UI labels) and the Flask-free notification subsystem
(:mod:`lib.core.notify` e-mail templates), so translations live in the general
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

__all__ = ['SUPPORTED_LANGS', 'DEFAULT_LANG', 'TRANSLATIONS', 'DATA_SECTIONS', 'coerce_lang',
           'is_ref', 'materialize', 'shipped_text', 'translate', 'ui_strings']

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


# ── The words of what the product SHIPS ─────────────────────────────────────────────────────
#
# Translations live in one place: these lang files, or a module's own `lang/`. A data file the
# product ships —an SNMP profile, the DCIM connectors and basics— does not carry a text per
# language: it writes ``{"i18n": "<key>"}`` where the text goes, and the code that loads it
# resolves the key in the section of these files that word that kind of data. What an
# installation writes itself (its own profiles, the connectors document it saves, its catalogue
# rows) keeps its texts inside: it is its data, and a key of ours would not say it.

#: The sections that word shipped DATA rather than the panel's own screens. Resolved on the
#: server; they are left out of what a page receives (:func:`ui_strings`).
DATA_SECTIONS: tuple[str, ...] = (
    'snmp_shipped_profiles',        # lib/core/snmp/profiles/sources/*.json
    'dcim_shipped_connectors',      # lib/core/dcim/data/connectors.json
    'dcim_shipped_basics',          # lib/core/dcim/data/basics.json
    'dcim_demo_words',              # lib/core/dcim/demo.py
    'dcim_demo_monitor_words',      # lib/core/dcim/demo_monitor.py
)

#: The field that marks a reference in a shipped document: ``{"i18n": "<key>"}``.
REF = 'i18n'


def is_ref(value) -> bool:
    """Is *value* a reference to a shipped word rather than a text?"""
    return isinstance(value, dict) and len(value) == 1 and isinstance(value.get(REF), str)


def shipped_text(section: str, key: str) -> dict:
    """``{lang: text}`` of *key* in *section*, for every language that words it.

    The same shape a per-language text has always had in these documents, so everything that
    reads one —``label_of`` for a profile, ``_text`` for a connector— reads this unchanged, and
    falls back to the default language and then to the object's id as it always did. ``{}`` for
    a key nobody worded, which the guards in ``tests/meta/test_i18n_shipped_data.py`` refuse.
    """
    out = {}
    for lang, table in TRANSLATIONS.items():
        text = (table.get(section) or {}).get(key)
        if isinstance(text, str) and text:
            out[lang] = text
    return out


def materialize(doc, section: str):
    """*doc* with every ``{"i18n": key}`` replaced by its words (:func:`shipped_text`).

    A copy — the caller's document is never written to. Applied to whatever a loader reads,
    shipped or not: a profile an administrator copied from the shipped folder keeps resolving
    the keys it carries, and one where they wrote their own words is left as it is, because a
    text there is not a reference. Lists and objects are walked; everything else is kept.
    """
    if is_ref(doc):
        return shipped_text(section, doc[REF])
    if isinstance(doc, dict):
        return {k: materialize(v, section) for k, v in doc.items()}
    if isinstance(doc, list):
        return [materialize(v, section) for v in doc]
    return doc


_UI_CACHE: dict = {}


def ui_strings(lang: str) -> dict:
    """The panel's own words in *lang* (else the default language), without the
    :data:`DATA_SECTIONS` — what a page is sent. Built once per language."""
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANG]
    key = lang if lang in TRANSLATIONS else DEFAULT_LANG
    if key not in _UI_CACHE:
        _UI_CACHE[key] = {k: v for k, v in table.items() if k not in DATA_SECTIONS}
    return _UI_CACHE[key]


def translate(lang: str, key: str, *args) -> str:
    """Translate *key* into *lang* (falling back to the default language and then
    to the key itself), filling each ``{}`` placeholder with *args* in order.

    Flask-free, instance-free — for console/daemon messages where the web app's
    request-bound translator is unavailable (see :meth:`WebAdmin._t`)."""
    text = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG]).get(key, key)
    for arg in args:
        text = text.replace('{}', str(arg), 1)
    return text
