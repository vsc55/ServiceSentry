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


Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_i18n_keys_exist.py`` lives in
``tests/unit/test_i18n_keys_exist.py``."""

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

_EXCLUDED_FILES = ()      # (was: overview2.html, an Alpine proof-of-concept now removed)


def _src_root() -> str:
    """The ``src`` directory (this file lives in ``src/tests``)."""
    return os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


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






def test_audit_actually_finds_keys():
    """Guard the guard: if the regexes stopped matching, the test would pass vacuously."""
    refs = _referenced_keys()
    assert len(refs) > 200, f'only {len(refs)} keys found — the scan is probably broken'
    assert 'insufficient_permissions' in refs


def _duplicate_keys(path):
    """Keys assigned twice inside the same dict literal → [(key, first_line, second_line,
    same_value)]. Python keeps the LAST one silently, so the first is dead."""
    import ast
    tree = ast.parse(io.open(path, encoding='utf-8-sig').read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen = {}
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            try:
                val = ast.literal_eval(v)
            except Exception:                      # noqa: BLE001  (non-literal value)
                val = object()
            if k.value in seen:
                prev_line, prev_val = seen[k.value]
                out.append((k.value, prev_line, k.lineno, prev_val == val))
            seen[k.value] = (k.lineno, val)
    return out


@pytest.mark.parametrize('lang', ['en_EN', 'es_ES'])
def test_no_key_is_defined_twice(lang):
    """A key assigned twice is resolved by Python to the LAST value, silently.

    ``role_deleted`` was defined twice with different values: the select that flags a
    dangling role reference wanted '⚠ Deleted role', the toast after deleting one wanted
    'Role deleted' — and the toast won, so the select lost its warning marker and read like
    a confirmation. Nothing failed; the wrong string simply shipped.

    Same-value duplicates are caught too: they break nothing today, but the next person to
    edit one has even odds of editing the copy that does not win.
    """
    path = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                        'lib', 'i18n', 'lang', f'{lang}.py')
    dups = _duplicate_keys(path)
    assert not dups, '\n'.join(
        f'{k!r} defined at line {a} and {b} '
        f'({"same value — the first is dead" if same else "DIFFERENT values — the first is dead"})'
        for k, a, b, same in dups)




# ── every option the config screen DRAWS has a name in both languages ────────
# A field with no entry in `labels` is not blank: `fieldLabel()` humanises the key, so the
# screen quietly shows "Retention Days" and "Max Rows" in the middle of a Spanish panel. It
# never fails, it never logs, and it looks enough like a label that it survives review.
#
# These are drawn with a label of their own instead of by name — a bespoke editor supplies it
# (webhooks, the Teams delivery selector), or the field is an internal id the renderers hide.
_LABELLED_ELSEWHERE = {
    # Internal Entra ids: written by the wizards, used for deep links, never shown
    # (`_hide` in the SCIM and SAML2 renderers).
    'saml2|sp_app_id', 'saml2|sp_object_id', 'scim|sp_app_id', 'scim|sp_object_id',
    # The webhook editor labels its own rows (`webhook_url`, `webhook_method`, …): these
    # names are too generic to key globally — `url` belongs to no one section.
    'webhooks|url', 'webhooks|method', 'webhooks|secret', 'webhooks|secret_header',
    'webhooks|headers', 'webhooks|body_template',
    # Drawn as a custom <select> labelled `msteams_delivery`, not through renderField.
    'msteams|delivery',
}


