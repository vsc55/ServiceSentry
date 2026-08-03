#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A number field has to be clearable, and the schema key that says so has to be read.

Three states hide in one numeric box: a value, "use the inherited default", and "off". The
schema distinguishes them — `inherit_blank` stores null when cleared, `zero_as_blank` stores
0 — and the renderer marks the input so the on-change validator knows which it is.

`zero_as_blank` was read NOWHERE. The attribute the validator looks for was only emitted as a
side effect of a field having a placeholder, so a clearable field that inherits nothing never
got it: emptying the box and leaving it snapped back to the stored value, which reads as an
input refusing to be cleared. Five shipped modules declared the key; for the fields without a
placeholder it did nothing at all.

That is the failure mode worth a guard: not a wrong pixel, but schema vocabulary that looks
meaningful and is inert.
"""

import io
import json
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                      '_field_render.html')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _schemas():
    """Every shipped watchful's item schema."""
    wf = os.path.join(SRC, 'watchfuls')
    for entry in sorted(os.listdir(wf)):
        sp = os.path.join(wf, entry, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            yield entry, (json.load(io.open(sp, encoding='utf-8-sig')) or {})
        except ValueError:
            continue










class TestEveryOptionKnowsItsDefault:
    """Reported: whole sections with no "restore default" button, and boxes that show nothing
    when emptied — Platform health among them, but not only it.

    The frontend asked `CONFIG_FIELD_DEFAULTS` for defaults. That map is five deliberate
    exceptions, back-filled at boot from `/api/v1/config/schema` — which carries `default` for
    instance-backed bool/int fields and for nothing else. So ~65 options had a default and the
    other ~136 silently had none, while the code around the lookup said "the registry default"
    and looked entirely correct.

    `CONFIG_REGISTRY_DEFAULTS` is the registry, derived from `lib.config.spec`, and it knows
    them all. One helper reads both, exceptions first.
    """

    def _core(self, name: str) -> str:
        return io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                    name), encoding='utf-8-sig').read()

    def test_the_registry_knows_every_option_that_can_be_seeded(self):
        from lib.config.spec import CONFIG_FIELDS, registry_defaults
        rd = registry_defaults()
        missing = [f.path for f in CONFIG_FIELDS if f.path not in rd and not f.no_seed]
        assert not missing, missing

    def test_the_schema_alone_was_never_enough(self):
        """The guard for the bug itself: if `frontend_schema` ever did carry every default,
        this fails and the whole two-map dance can go. Until then it documents WHY the
        frontend cannot rely on it."""
        from lib.config.spec import CONFIG_FIELDS, frontend_schema
        sch = frontend_schema()
        without = [f.path for f in CONFIG_FIELDS if 'default' not in (sch.get(f.path) or {})]
        assert len(without) > 100, \
            'the schema now carries defaults broadly — revisit cfgDefaultFor and this guard'

    def test_one_helper_answers_and_the_exceptions_win(self):
        body = self._core('_constants.html')
        assert 'function cfgDefaultFor(pathStr)' in body
        i = body.index('function cfgDefaultFor(pathStr)')
        block = body[i:i + 700]
        assert block.index('CONFIG_FIELD_DEFAULTS') < block.index('CONFIG_REGISTRY_DEFAULTS'), \
            'the registry wins over the deliberate exceptions — lang would restore to English'

    def test_nothing_reads_a_single_map_behind_its_back(self):
        """Either map alone is half an answer, and the half you get depends on which field it
        is — which is exactly how this shipped looking correct."""
        for name in ('_field_render.html',):
            body = self._core(name)
            assert 'CONFIG_FIELD_DEFAULTS[' not in body, name
            assert 'CONFIG_REGISTRY_DEFAULTS[' not in body, name

    def test_the_boot_no_longer_backfills_the_exception_map(self):
        """Mutating it at boot is what made five keys look like the source of every default."""
        wiring = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                      'init', '_wiring.html'), encoding='utf-8-sig').read()
        assert 'CONFIG_FIELD_DEFAULTS[k] = v.default' not in wiring

    def test_restore_is_offered_exactly_when_there_is_something_to_restore_to(self):
        body = self._core('_field_render.html')
        assert "target === 'config' && cfgHasDefault(pathStr)" in body
        i = body.index('function resetConfigField(pathStr)')
        assert 'cfgDefaultFor(pathStr)' in body[i:i + 300]

    def test_an_emptied_box_shows_what_the_system_will_use(self):
        """A blank field with no placeholder says "unset" when it means "the default applies"."""
        body = self._core('_field_render.html')
        assert body.count('cfgDefaultFor(pathStr)') >= 3, \
            'a placeholder branch is still asking a map that only knows a slice of the options'

    def test_a_config_number_at_its_default_is_drawn_empty(self):
        """Reported twice. First: "Service down after (s)" had no placeholder at all — it lands
        in the plain-number branch, which had one for module cascades and for nothing else.
        Then: clearing the box refilled it with the default on blur, which undoes the clearing
        in front of the reader.

        At its default the box is EMPTY, with the default greyed inside it. That is the honest
        drawing of "this install did not decide this": printing 60 as a value claims an admin
        chose 60, and leaves nothing on screen telling a deliberate 60 from the shipped one.
        Clearing returns to exactly that state, so it stays empty."""
        body = self._core('_field_render.html')
        assert "target === 'config' && typeof cfgDefaultFor(pathStr) === 'number'" in body
        assert 'if (value === cfgDefaultFor(pathStr)) displayValue = ' in body, \
            'a value equal to the default is still printed as a value'
        i = body.index('function validateAndUpdateNumber')
        blur = body[i:i + 1800]
        assert 'hasDefaultBlank' in blur, 'the marker is rendered but never acted on'
        assert "el.value = '';\n            updateField(target, pathStr, cfgDefaultFor(pathStr))" in blur, \
            'blanking the box puts the number back, which is the reported bug'

    def test_the_default_is_what_is_stored_never_null(self):
        """A config option has nothing to inherit from, so null would be a third state every
        consumer would have to agree about — and `cfg.get('x', 60)` returns None for a stored
        null, falling back only for an ABSENT key. The quiet readers would break first."""
        body = self._core('_field_render.html')
        i = body.index('} else if (hasDefaultBlank) {')
        block = body[i:i + 900]
        assert 'updateField(target, pathStr, cfgDefaultFor(pathStr))' in block
        assert 'updateField(target, pathStr, null)' not in block

    def test_a_text_option_shows_its_default_but_blank_still_means_blank(self):
        """For a string, empty is usually a real answer — no proxy, no filter — so the
        placeholder is offered and the behaviour is not changed: clearing the box keeps meaning
        "empty" rather than quietly writing the default back. Only non-empty defaults are
        shown; for the many options whose default IS "", a placeholder would be inventing one.
        """
        body = self._core('_field_render.html')
        i = body.index("if (!_strPh && target === 'config')")
        block = body[i:i + 400]
        assert "typeof _cfgDef === 'string' && _cfgDef !== ''" in block
        assert 'data-default-blank' not in block, 'clearing a text box would rewrite the default'
