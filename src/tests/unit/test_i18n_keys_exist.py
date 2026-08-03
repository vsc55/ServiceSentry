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


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_i18n_keys_exist.py`` lives in ``tests/meta/test_i18n_keys_exist.py``."""

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


def test_language_files_are_in_parity():
    """en_EN and es_ES must define exactly the same keys."""
    en, es = set(_flat(en_EN.LANG)), set(_flat(es_ES.LANG))
    assert en == es, (f'only in en_EN: {sorted(en - es)}\n'
                      f'only in es_ES: {sorted(es - en)}')


def test_the_regression_that_motivated_this():
    """``insufficient_permissions`` is returned by 6 route modules on 403."""
    for mod in (en_EN, es_ES):
        assert 'insufficient_permissions' in _known_keys(mod)




def test_the_two_role_deleted_strings_stayed_apart():
    """They are different messages for different surfaces; merging them again would
    reintroduce the bug in whichever one loses."""
    for mod in (en_EN, es_ES):
        keys = _known_keys(mod)
        assert 'role_deleted' in keys and 'role_deleted_ref' in keys


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


@pytest.mark.parametrize('lang_mod,lang', [(en_EN, 'en_EN'), (es_ES, 'es_ES')])
def test_every_config_option_has_a_label(lang_mod, lang):
    """Reported from a screenshot: "Landing Page", "Allowed Sources", "Retention Days" and
    "Max Rows" sitting untranslated in a Spanish configuration screen — forty-four options
    with no entry at all, each humanised from its key and looking almost like a label.

    Checked by path first, then by field name, which is the order `_field_render.html` reads
    them in: a name is enough when it means the same everywhere (`group_display_names` in
    three auth providers), a path is what disambiguates when it does not.
    """
    from lib.config.spec import CONFIG_FIELDS
    labels = lang_mod.LANG['labels']
    missing = [f.path for f in CONFIG_FIELDS
               if f.path not in _LABELLED_ELSEWHERE
               and f.path not in labels and f.path.split('|', 1)[1] not in labels]
    assert not missing, f'{lang}: {len(missing)} config options have no label: ' + ', '.join(missing)
