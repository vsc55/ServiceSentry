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


@pytest.mark.parametrize('lang_mod,lang', [(en_EN, 'en_EN'), (es_ES, 'es_ES')])
def test_every_config_section_has_a_title(lang_mod, lang):
    """Reported from the panel: a new section shipped with its title key defined and the title
    still missing — because it was defined in the wrong dictionary.

    The language file has a nested `labels` dict for the OPTIONS and a flat top level for
    everything else, and a section's `title_key` is read from the top level. Put it in `labels`
    and every check passes: the key exists, the option beside it has a label, nothing raises.
    The section is simply drawn with its key as its name, which reads like a label until you
    look twice.

    Both halves are checked here, and both directions matter: the option labels are covered
    above, and this is the card the option sits in.
    """
    from lib.config.layout import CARDS
    top = lang_mod.LANG
    missing = [c['id'] for c in CARDS if c.get('title_key') and c['title_key'] not in top]
    assert not missing, (
        f'{lang}: config sections whose title is not in the top-level dictionary '
        f'(a nested one does not count — that is not where a card reads it): '
        + ', '.join(missing))


@pytest.mark.parametrize('lang_mod,lang', [(en_EN, 'en_EN'), (es_ES, 'es_ES')])
def test_no_option_hint_hides_in_the_labels_dict(lang_mod, lang):
    """Reported from the panel: an option's help text was written, was in the language file,
    and did not appear. The info panel opened — the env var and the key were in it — with no
    prose above them.

    It was defined in the nested `labels` dict, under `<option>_hint`. Nothing reads that:
    `fieldLabel()` looks in `labels` by the option's own name, and `fieldHint()` looks in
    `hints` by `section|option` (or by the bare option). A key that matches neither is text
    nobody will ever see, and every check passes — the key exists, the parity holds, the
    option has a label.

    The same shape as the section title that shipped invisible for the same reason (see
    `test_every_config_section_has_a_title`). Two dictionaries, one of them nested, and the
    only signal that you picked the wrong one is that the screen stays blank.
    """
    strays = sorted(k for k in lang_mod.LANG.get('labels', {}) if k.endswith('_hint'))
    assert not strays, (
        f'{lang}: help text inside `labels`, where nothing reads it — it belongs in `hints`, '
        f"keyed `section|option` (or, for a hint a template draws itself with t('…_hint'), at "
        f'the top level): ' + ', '.join(strays))
