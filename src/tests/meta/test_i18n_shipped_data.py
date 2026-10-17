#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the product ships names its words by key; the words live in the lang files.

Translations live in ONE place: the core lang files (``lib/i18n/lang/<lang>.py``) or a module's
own (``watchfuls/<m>/lang/``). A data file the product ships —an SNMP profile, the DCIM
connectors and basics, the demo— used to carry ``{"es_ES": …, "en_EN": …}`` inline, and the
demo one word file per language. Out of reach of the lang files, those texts could not gain a
third language without editing data, did not show up in any review of the translations, and a
word corrected in ``es_ES.py`` went on saying the old one on the screen.

Now a shipped file holds ``{"i18n": "<key>"}`` and the loader resolves it
(:func:`lib.i18n.materialize`). What an installation writes itself —its own SNMP profiles, the
connectors document it saves, its catalogue rows— keeps its texts inside: it is its data, and
none of it lives in this repository.

The guards:

* no shipped JSON carries a map keyed by language codes, and no file outside a ``lang/`` folder
  is named after a language (the demo's old ``es_ES.json``/``en_EN.json`` shape);
* every key a shipped file references exists, non-empty, in EVERY language;
* every key of a data section is referenced by some shipped file (a word nobody reads is one
  nobody will keep up to date);
* those sections do not travel to the browser with the panel's own words.

Dict literals with language keys inside ``.py`` code are guarded next door, in
``test_i18n_no_text_in_code.py``, for the core and the modules alike.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]

#: A language code, as the lang files name them.
_LANG_CODE = re.compile(r'^[a-z]{2}_[A-Z]{2}$')

#: The shipped files that reference keys, and the section of the core lang files they name.
REFERENCING = {
    'lib/core/snmp/profiles/sources/*.json': 'snmp_shipped_profiles',
    'lib/core/dcim/data/connectors.json':    'dcim_shipped_connectors',
    'lib/core/dcim/data/basics.json':        'dcim_shipped_basics',
}

#: Writers of USER data allowed to hold a per-language map in a JSON under the tree. Empty: what
#: an installation writes lives in its database and its `var_dir`, never in the repository. A
#: path added here says why, in a comment beside it.
ALLOWED_LANG_MAPS: frozenset = frozenset()


def _rel(path: str) -> str:
    return os.path.relpath(path, SRC).replace(os.sep, '/')


def _shipped_json():
    """Every JSON the product ships, outside the lang folders and the tests."""
    for root in ('lib', 'watchfuls'):
        for path in glob.glob(os.path.join(SRC, root, '**', '*.json'), recursive=True):
            rel = _rel(path)
            parts = rel.split('/')
            if 'lang' in parts or 'tests' in parts or '__pycache__' in parts:
                continue
            yield path, rel


def _lang_maps(o, path=''):
    if isinstance(o, dict):
        if any(_LANG_CODE.match(str(k)) for k in o):
            yield path or '/'
            return
        for k, v in o.items():
            yield from _lang_maps(v, f'{path}/{k}')
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _lang_maps(v, f'{path}[{i}]')


def _refs(o):
    if isinstance(o, dict):
        if set(o) == {'i18n'}:
            yield str(o['i18n'])
            return
        for v in o.values():
            yield from _refs(v)
    elif isinstance(o, list):
        for v in o:
            yield from _refs(v)


def _referenced() -> dict:
    """``{section: {key: [files]}}`` for every reference in the shipped files."""
    out: dict = {}
    for pattern, section in REFERENCING.items():
        files = sorted(glob.glob(os.path.join(SRC, pattern)))
        assert files, f'{pattern} matches nothing — this guard needs updating'
        for path in files:
            with io.open(path, encoding='utf-8') as fh:
                doc = json.load(fh)
            for key in _refs(doc):
                out.setdefault(section, {}).setdefault(key, []).append(_rel(path))
    return out


class TestNoShippedFileCarriesItsOwnTranslations:

    def test_no_json_holds_a_map_keyed_by_language(self):
        bad = []
        seen = 0
        for path, rel in _shipped_json():
            if rel in ALLOWED_LANG_MAPS:
                continue
            try:
                with io.open(path, encoding='utf-8') as fh:
                    doc = json.load(fh)
            except ValueError:
                continue
            seen += 1
            bad += [f'{rel}: {where}' for where in _lang_maps(doc)]
        assert seen > 60, f'only {seen} JSON files scanned — the walk is broken'
        assert not bad, ('texts translated inline in a shipped file — move them to the core '
                         'lang files and leave {"i18n": "<key>"}:\n' + '\n'.join(bad[:40]))

    def test_no_file_outside_a_lang_folder_is_named_after_a_language(self):
        bad = []
        for root in ('lib', 'watchfuls'):
            for path in glob.glob(os.path.join(SRC, root, '**', '*.*'), recursive=True):
                rel = _rel(path)
                parts = rel.split('/')
                if 'lang' in parts or 'tests' in parts or '__pycache__' in parts:
                    continue
                stem, ext = os.path.splitext(parts[-1])
                if ext in ('.json', '.py', '.yaml', '.yml') and _LANG_CODE.match(stem):
                    bad.append(rel)
        assert not bad, ('a word file per language outside a lang/ folder — its words belong '
                         'in the lang files:\n' + '\n'.join(bad))


class TestEveryReferencedKeyExists:

    def _langs(self):
        from lib.i18n import TRANSLATIONS                           # noqa: PLC0415
        assert {'es_ES', 'en_EN'} <= set(TRANSLATIONS)
        return TRANSLATIONS

    def test_the_scan_finds_references(self):
        """Guard the guard: a regex that stopped matching would pass everything."""
        refs = _referenced()
        assert len(refs.get('snmp_shipped_profiles', {})) > 600
        assert len(refs.get('dcim_shipped_connectors', {})) > 30
        assert len(refs.get('dcim_shipped_basics', {})) > 100

    def test_in_every_language(self):
        missing = []
        for lang, table in self._langs().items():
            for section, keys in _referenced().items():
                have = table.get(section) or {}
                for key, files in sorted(keys.items()):
                    text = have.get(key)
                    if not isinstance(text, str) or not text.strip():
                        missing.append(f'{lang}:{section}[{key!r}]  ← {files[0]}')
        assert not missing, 'referenced but not worded:\n' + '\n'.join(missing[:60])

    def test_and_no_word_is_left_that_nothing_references(self):
        """A key nothing names is a word nobody reads — and the next person corrects it in
        the lang file and wonders why the screen did not change."""
        orphans = []
        refs = _referenced()
        for lang, table in self._langs().items():
            for section in REFERENCING.values():
                for key in sorted(set(table.get(section) or {}) - set(refs.get(section, {}))):
                    orphans.append(f'{lang}:{section}[{key!r}]')
        assert not orphans, 'worded but never referenced:\n' + '\n'.join(orphans[:60])

    def test_the_demo_words_are_there_in_every_language(self):
        """The demo reads its words by name from code, not through references: what is
        checked is that each language has the base language's whole set."""
        from lib.i18n import TRANSLATIONS                           # noqa: PLC0415
        for section in ('dcim_demo_words', 'dcim_demo_monitor_words'):
            base = set(TRANSLATIONS['es_ES'][section])
            assert len(base) > 10, section
            for lang, table in TRANSLATIONS.items():
                assert set(table.get(section) or {}) == base, (lang, section)


class TestTheDataSectionsStayOnTheServer:

    def test_they_are_not_in_the_page(self):
        """The panel ships its words to the browser on every page. The data sections are
        resolved on the server, and as page payload they would be dead weight on each load."""
        from lib.i18n import DATA_SECTIONS, TRANSLATIONS, ui_strings  # noqa: PLC0415
        assert set(DATA_SECTIONS) >= set(REFERENCING.values())
        assert {'dcim_demo_words', 'dcim_demo_monitor_words'} <= set(DATA_SECTIONS)
        for lang in TRANSLATIONS:
            page = ui_strings(lang)
            assert not set(DATA_SECTIONS) & set(page)
            assert set(page) == set(TRANSLATIONS[lang]) - set(DATA_SECTIONS)

    def test_and_the_context_sends_that_one(self):
        with io.open(os.path.join(SRC, 'lib', 'web_admin', 'mixins', 'context.py'),
                     encoding='utf-8') as fh:
            src = fh.read()
        assert "'i18n': ui_strings(" in src
