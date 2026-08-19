#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""An audit entry must not be half in the reader's language and half in identifiers.

A detail record holds two very different kinds of string, and the screen was treating them the
same. Most are DATA — a hostname, a filename, something somebody typed — and translating those
would be nonsense. A few are VOCABULARY the panel itself chose when it wrote the entry:
``stage: 'forced_enrol'``, ``error: 'bad_code'``, ``method: 'totp'``. Those were reaching the
audit screen exactly as written, which is how a log ends up reading half in Spanish and half in
snake_case. Reported from the panel: "I see texts like bad_code, forced_enrol".

The renderer translates by FIELD and never by value — a value-driven rule would translate a
host called ``local`` — and every lookup falls back to the raw word, so an entry a module wrote
still reads, just untranslated. That fallback is also why nothing FAILS when a word is missing,
which is precisely why this guard exists: the symptom is quiet, and it is one grep away from
being caught.

The scan is static and deliberately narrow: it reads the ``detail={...}`` literals the core
writes for the fields the renderer translates, and asks the language files for each value. A
value that is computed rather than written out (``out.get('error', '')``) cannot be read here —
those come from the service layer, so the vocabulary of `_ERROR_SOURCES` is scanned too.
"""

import ast
import io
import os
import re

from lib.i18n.lang import en_EN, es_ES

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
DETAIL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'audit', '_detail.html')

# Where an audit detail's vocabulary is written down.
_DETAIL_SOURCES = (
    os.path.join(SRC, 'lib', 'core', 'mfa', 'routes.py'),
    os.path.join(SRC, 'lib', 'core', 'mfa', 'mixin.py'),
    os.path.join(SRC, 'lib', 'web_admin', 'routes', 'auth.py'),
)
# …and where the `error` values those details forward come from.
_ERROR_SOURCES = (
    os.path.join(SRC, 'lib', 'core', 'mfa', 'service.py'),
)


def _enum_fields() -> set:
    """The fields the renderer translates, read from the renderer itself."""
    src = io.open(DETAIL, encoding='utf-8-sig').read()
    m = re.search(r'_AUDIT_ENUM_FIELDS = new Set\(\[([^\]]*)\]\)', src)
    assert m, '_AUDIT_ENUM_FIELDS is gone — this guard needs re-aiming'
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def _written_values() -> set:
    """Literal `detail={'stage': 'x', …}` values for the translated fields.

    Only dicts passed as the `detail=` argument. Every other dict in these files is a JSON
    response body — `{'ok': False, 'error': 'unknown_user'}` — and those never reach the audit
    screen: demanding a translation for them would be asking for words nobody ever reads."""
    fields, out = _enum_fields(), set()
    for path in _DETAIL_SOURCES:
        tree = ast.parse(io.open(path, encoding='utf-8-sig').read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != 'detail' or not isinstance(kw.value, ast.Dict):
                    continue
                for key, val in zip(kw.value.keys, kw.value.values):
                    if (isinstance(key, ast.Constant) and key.value in fields
                            and isinstance(val, ast.Constant) and isinstance(val.value, str)
                            and val.value):
                        out.add(val.value)
    return out


def _service_errors() -> set:
    """`{'ok': False, 'error': 'x'}` — the values the routes forward into `error`."""
    out = set()
    for path in _ERROR_SOURCES:
        tree = ast.parse(io.open(path, encoding='utf-8-sig').read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, val in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == 'error'
                        and isinstance(val, ast.Constant) and isinstance(val.value, str)
                        and val.value):
                    out.add(val.value)
    return out


class TestTheScanItself:

    def test_the_renderer_still_translates_by_field(self):
        fields = _enum_fields()
        assert {'stage', 'error', 'method'} <= fields, \
            'the renderer stopped translating the fields this guard is about'

    def test_the_sources_yield_vocabulary(self):
        assert len(_written_values()) >= 4
        assert len(_service_errors()) >= 3


class TestEveryWordThePanelWroteHasWords:

    def _missing(self, lang, words) -> list:
        return sorted(w for w in words if not lang.LANG.get('audit_v_' + w))

    def test_the_stages_and_reasons_are_translated(self):
        words = _written_values() | _service_errors()
        for lang, name in ((es_ES, 'es_ES'), (en_EN, 'en_EN')):
            missing = self._missing(lang, words)
            assert not missing, (
                f'{name} has no audit_v_* for: {", ".join(missing)} — these reach the audit '
                'screen as written, which is how a log ends up half in identifiers')

    def test_the_field_names_are_translated(self):
        for lang, name in ((es_ES, 'es_ES'), (en_EN, 'en_EN')):
            missing = sorted(f for f in _enum_fields() if not lang.LANG.get('audit_f_' + f))
            assert not missing, f'{name} has no audit_f_* for: {", ".join(missing)}'

    def test_the_two_languages_carry_the_same_set(self):
        """A word translated in one language and not the other is the same bug, found later."""
        es = {k for k in es_ES.LANG if k.startswith(('audit_v_', 'audit_f_'))}
        en = {k for k in en_EN.LANG if k.startswith(('audit_v_', 'audit_f_'))}
        assert es == en, f'only in one language: {sorted(es ^ en)}'


class TestAPermissionReadsTheSameEverywhere:
    """Reported from the panel: the audit entry for a new token showed `audit_view`.

    A third kind of value turned up with the tokens, and it is neither data nor vocabulary the
    panel chose: a PERMISSION FLAG. Sending those through `audit_v_*` would mean a second name
    for each of the 75 flags, kept in a different file from the one Access › Permissions reads
    — two names for one thing, drifting from the day they are written.

    So the detail renderer reads the same catalog everything else reads. By FIELD again, never
    by value: somebody's chosen name that happens to look like a flag must not turn into a
    permission label.
    """

    def test_the_renderer_has_a_field_rule_for_permissions(self):
        src = io.open(DETAIL, encoding='utf-8-sig').read()
        assert '_AUDIT_PERM_FIELDS' in src, 'permission flags reach the screen raw again'
        assert '_permLabel(' in src, 'a second set of names instead of the shared catalog'

    def test_it_is_by_field_and_not_by_value(self):
        """The rule this whole file is about: a value-driven match would translate a host
        called `local` or a module whose id happens to be a flag."""
        src = io.open(DETAIL, encoding='utf-8-sig').read()
        assert '_AUDIT_PERM_FIELDS.has(k)' in src

    def test_the_all_sentinel_is_not_treated_as_a_flag(self):
        """`'*'` means "whatever the owner has". It is not in the catalog and has no label,
        so looking it up there would print an asterisk and call it a permission."""
        assert "v === '*'" in io.open(DETAIL, encoding='utf-8-sig').read()

    def test_the_new_fields_have_names(self):
        for key in ('audit_f_token_id', 'audit_f_permissions', 'audit_f_expires_at',
                    'audit_f_count', 'audit_v_never'):
            for lang, name in ((es_ES, 'es_ES'), (en_EN, 'en_EN')):
                assert lang.LANG.get(key), f'{key} missing in {name}'


class TestAChangedFieldIsNamed:
    """Reported from the panel, on saving a setting: the entry said
    ``web_admin.session_log_max``.

    That is the storage path — the identifier the audit stores and must go on storing, since
    it is what ties an entry to a setting from a bug report or a config file. What it must not
    be is the ONLY thing on screen: an audit that reads as a list of internal keys makes the
    reader translate the panel back into itself, and the panel already knows every one of
    these names — the Configuration screen labels the very same field two clicks away.

    So the label is shown and the key becomes the tooltip: the same shape as the permission
    badges above, for the same reason.
    """

    def _src(self) -> str:
        return io.open(DETAIL, encoding='utf-8-sig').read()

    def test_the_changes_table_resolves_the_label(self):
        src = self._src()
        assert 'function _auditChangeLabel(' in src, 'nothing turns a field into a name'
        assert '_auditChangeLabel(c.field)' in src, 'the change rows print the raw key again'

    def test_it_reads_the_catalog_the_config_screen_reads(self):
        """`LABELS` and not a second dictionary of its own: two names for one option is one
        name that goes stale, and it would be this one — nobody reads the audit until
        something has gone wrong."""
        body = re.search(r'function _auditChangeLabel\(field\)\s*\{(.*?)\n\}',
                         self._src(), re.S).group(1)
        assert 'LABELS[' in body
        assert "split(/[.|]/)" in body, 'a path like web_admin.session_log_max is not resolved'

    def test_the_identifier_survives_as_the_tooltip(self):
        assert 'title="${escAttr(c.field' in self._src(), (
            'the raw key is gone from the screen entirely — an entry that cannot be grepped '
            'back to a setting is a nicer entry that answers less')

    def test_the_last_fallback_is_the_key_itself(self):
        """Not a prettified guess: a name invented here for a field nobody translated would be
        a name that exists nowhere else in the product."""
        body = re.search(r'function _auditChangeLabel\(field\)\s*\{(.*?)\n\}',
                         self._src(), re.S).group(1)
        assert body.rstrip().endswith('|| raw;')
        assert 'humanizeKey' not in body

    def test_the_snapshot_renderer_names_them_the_same_way(self):
        """`before`/`after` entries are field names too, and two rules for "what is this
        field called" is one rule that drifts."""
        assert self._src().count('_auditChangeLabel(') >= 4

    def test_the_export_keeps_the_raw_key(self):
        """The CSV is read by a machine, or grepped. A translated column header inside the
        data would make the export depend on the reader's language."""
        export = io.open(os.path.join(os.path.dirname(DETAIL), '_export.html'),
                         encoding='utf-8-sig').read()
        assert 'c.field' in export and '_auditChangeLabel' not in export
