#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The words a module wrote in the audit log.

An entry for a module action is `{module, action, …}` and the action is an IDENTIFIER —
`restore_orphan`, `clean_library`, `import_mib_archive_status`. The core ships no string that
names a module's action, on purpose: the vocabulary belongs to whoever invented it. So the
panel asks the module, in the module's own `ui` block, under `audit_v_<action>`.

Two ways for that to fail, and both were live:

* **the word is missing** — eight modules had at least one action with no word in either
  language, so the log printed the identifier;
* **nothing asked for it** — the row of the log printed the `name` the route composes for it
  (`snmp / delete_mib`) and never looked the action up at all, while the modal three clicks
  away read it correctly.

Read-only actions are exempt: they are not audited, so a word for them would be a word
nobody can reach.
"""

import io
import json
import os
import re

import pytest

from tests.helpers import _fn, _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
MODULES = os.path.join(SRC, 'watchfuls')
AUDIT = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'audit', '_detail.html')
LANGS = ('es_ES', 'en_EN')


def _frozenset_names(src: str, name: str) -> set:
    """The action names inside a `frozenset({...})` declaration."""
    i = src.find(name)
    if i < 0:
        return set()
    return set(re.findall(r"'([a-z0-9_]+)'", src[i:src.index('})', i)]))


def _modules() -> list:
    """``[(vocabulary, [state-changing actions])]`` for every surface the audit log names.

    Two sources now, one rule. A watchful declares its actions in its ``__init__``; a CORE
    package that owns a surface declares them in its manifest — SNMP's library and catalogue
    operations moved there when they stopped being a check's business. Both end up in the
    same audit row, read through the same module vocabulary, so both are checked here.
    """
    out = []
    for mod in sorted(os.listdir(MODULES)):
        init = os.path.join(MODULES, mod, '__init__.py')
        if not os.path.isfile(init):
            continue
        src = _read(init)
        changing = _frozenset_names(src, 'WATCHFUL_ACTIONS')             - _frozenset_names(src, 'READ_ONLY_ACTIONS')
        if changing:
            out.append((mod, sorted(changing)))
    out.extend(_core_surfaces())
    return out


def _core_surfaces() -> list:
    """The same, for core packages whose manifest declares ``ACTIONS``.

    The vocabulary is still the module's lang file — that is where these words live and where
    the audit renderer reads them — so the pair is ``(module_name, actions)`` exactly as
    above. This is about which words must exist, not about who runs the operation.
    """
    from lib.discovery import scan          # noqa: PLC0415
    ro = dict(scan('READ_ONLY'))
    out = []
    for pkg, actions in scan('ACTIONS'):
        changing = sorted(set(actions) - set(ro.get(pkg) or ()))
        if changing:
            out.append((pkg, changing))
    return out


def _ui(mod: str, lang: str) -> dict:
    """Where *mod*'s action words live.

    A watchful keeps them in its own lang file. A CORE surface keeps them in core i18n, as
    plain ``audit_v_*`` keys — which is where ``_auditWord`` looks FIRST, so the renderer
    needed no change when they moved. Both are checked, because both end up in the same row.
    """
    path = os.path.join(MODULES, mod, 'lang', lang + '.json')
    if os.path.isfile(path):
        with io.open(path, encoding='utf-8') as fh:
            own = json.load(fh).get('ui') or {}
        if own:
            return own
    from lib.i18n import TRANSLATIONS              # noqa: PLC0415
    texts = TRANSLATIONS.get(lang) or {}
    return {k: v for k, v in texts.items()
            if isinstance(k, str) and k.startswith(('audit_v_', 'audit_f_'))}


class TestTheScanItself:

    def test_the_modules_are_found_and_they_have_actions(self):
        mods = _modules()
        assert len(mods) >= 8, 'the action lists stopped being readable from here'
        assert any(m == 'snmp' for m, _ in mods)


@pytest.mark.parametrize('lang', LANGS)
def test_every_state_changing_action_has_a_word(lang):
    """A log that prints `clean_library` is a log half in identifiers — and the reader who
    needs it is the one who does not already know what the module calls things."""
    missing = []
    for mod, actions in _modules():
        ui = _ui(mod, lang)
        missing += ['%s: %s' % (mod, a) for a in actions if not ui.get('audit_v_' + a)]
    assert not missing, (
        'no audit_v_* in %s for: %s — these reach the audit screen as written'
        % (lang, ', '.join(missing)))


def test_the_two_languages_carry_the_same_actions():
    """A word in one language and not the other is the same bug, found later."""
    for mod, _ in _modules():
        es = {k for k in _ui(mod, 'es_ES') if k.startswith('audit_v_')}
        en = {k for k in _ui(mod, 'en_EN') if k.startswith('audit_v_')}
        assert es == en, f'{mod}: only in one language: {sorted(es ^ en)}'


class TestTheScreenActuallyAsksForThem:
    """The words existed for `delete_mib` and `restore_orphan` all along. What was missing was
    anybody asking: the row printed the identifier the server had composed."""

    def test_the_row_translates_the_action_through_the_module(self):
        body = _fn(_read(AUDIT), 'auditSummaryHtml')
        assert 'detail.module && detail.action' in body, \
            'the row has no branch for a module action'
        assert '_auditWord(detail.action)' in body
        assert '_auditMod = detail.module' in body, \
            'the lookup is not scoped to the module whose word it is'

    def test_it_puts_the_module_name_beside_the_verb(self):
        """"Delete a MIB file" says what happened and not what to."""
        assert 'modulePrettyName(detail.module' in _fn(_read(AUDIT), 'auditSummaryHtml')

    def test_the_module_lookup_is_the_fallback_and_never_the_first_answer(self):
        """A module must not be able to rename `error` or `user` for everybody."""
        src = _read(AUDIT)
        line = [ln for ln in src.split('\n') if 'const _auditWord' in ln]
        assert line and "I18N['audit_v_'" in line[0], 'the core is no longer asked first'
