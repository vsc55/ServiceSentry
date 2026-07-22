#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Every i18n key referenced in code/templates must exist in the language files.

``wa._t(key)`` / ``translate(lang, key)`` / ``t(key)`` all fall back to returning the key
itself when it is missing, so a forgotten translation does not raise — it silently ships
the raw key to the user (``insufficient_permissions`` was live in 17 route call sites for
exactly that reason).  This test turns that class of bug into a test failure.

Two deliberate exclusions, both structural rather than convenience:

* **Dynamic prefixes** — keys built by concatenation (``t('svc_' + key)``) are captured by
  the regex as a bare prefix ending in ``_``; the real key only exists at runtime, so
  there is nothing static to verify.
* **``overview2.html``** — the standalone Alpine.js proof-of-concept page, explicitly out
  of the i18n sweep (see CHANGELOG); it is not part of the shipped UI.
"""

import glob
import io
import os
import re

import pytest

from lib.i18n.lang import en_EN, es_ES

# ── where keys are referenced ────────────────────────────────────────────────
# Backend: wa._t('key') / self._t('key') / translate(lang, 'key')
_PY_KEY = re.compile(
    r"""(?:\b_t|\btranslate)\(\s*(?:[A-Za-z_][\w.]*\s*,\s*)?['"]([a-z][a-z0-9_]{2,})['"]""")
# Frontend: t('key') / tf('key', …) — literal keys only
_JS_KEY = re.compile(r"""\bt[f]?\(\s*['"]([a-z][a-z0-9_]{2,})['"]""")

_EXCLUDED_FILES = ('overview2.html',)


def _src_root() -> str:
    """The ``src`` directory (this file lives in ``src/tests``)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _flat(d: dict, prefix: str = '') -> dict:
    out: dict = {}
    for k, v in d.items():
        nk = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            out.update(_flat(v, nk))
        else:
            out[nk] = v
    return out


def _known_keys(lang_mod) -> set:
    """Top-level keys plus the leaf names of nested sections.

    Nested groups (``labels``/``hints``/``permission_labels``…) are looked up by leaf name
    at runtime, so a leaf counts as defined."""
    flat = _flat(lang_mod.LANG)
    return set(flat) | {k.split('.')[-1] for k in flat}


def _referenced_keys() -> dict:
    """``{key: [files]}`` for every statically-resolvable key referenced in the tree."""
    root = _src_root()
    found: dict = {}
    targets = [(p, _PY_KEY) for p in glob.glob(f'{root}/lib/**/*.py', recursive=True)]
    targets += [(p, _PY_KEY) for p in glob.glob(f'{root}/watchfuls/**/*.py', recursive=True)]
    targets += [(p, _JS_KEY) for p in glob.glob(f'{root}/lib/**/*.html', recursive=True)]
    targets += [(p, _JS_KEY) for p in glob.glob(f'{root}/watchfuls/**/*.html', recursive=True)]
    for path, pat in targets:
        if '.venv' in path or os.path.basename(path) in _EXCLUDED_FILES:
            continue
        text = io.open(path, encoding='utf-8', errors='replace').read()
        for m in pat.finditer(text):
            key = m.group(1)
            if key.endswith('_'):
                continue                     # dynamic prefix (t('svc_' + x)) — not static
            found.setdefault(key, []).append(os.path.relpath(path, root))
    return found


@pytest.mark.parametrize('lang_mod,lang', [(en_EN, 'en_EN'), (es_ES, 'es_ES')])
def test_no_referenced_key_is_missing(lang_mod, lang):
    """A key used by the code but absent from *lang* would render as the raw key."""
    known = _known_keys(lang_mod)
    missing = {k: v for k, v in _referenced_keys().items() if k not in known}
    assert not missing, (
        f'{len(missing)} i18n key(s) referenced but missing from {lang}:\n' +
        '\n'.join(f'  {k}  ← {v[0]}' + (f' (+{len(v) - 1} more)' if len(v) > 1 else '')
                  for k, v in sorted(missing.items())))


def test_language_files_are_in_parity():
    """en_EN and es_ES must define exactly the same keys."""
    en, es = set(_flat(en_EN.LANG)), set(_flat(es_ES.LANG))
    assert en == es, (f'only in en_EN: {sorted(en - es)}\n'
                      f'only in es_ES: {sorted(es - en)}')


def test_the_regression_that_motivated_this():
    """``insufficient_permissions`` is returned by 6 route modules on 403."""
    for mod in (en_EN, es_ES):
        assert 'insufficient_permissions' in _known_keys(mod)


def test_audit_actually_finds_keys():
    """Guard the guard: if the regexes stopped matching, the test would pass vacuously."""
    refs = _referenced_keys()
    assert len(refs) > 200, f'only {len(refs)} keys found — the scan is probably broken'
    assert 'insufficient_permissions' in refs
