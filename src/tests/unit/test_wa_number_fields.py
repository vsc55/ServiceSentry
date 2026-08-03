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


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_number_fields.py`` lives in ``tests/meta/test_wa_number_fields.py``."""

import io
import json
import os
from tests.helpers import _fn, _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                      '_field_render.html')


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


class TestTheVocabularyIsRead:

    def test_zero_as_blank_is_honoured_on_its_own(self):
        """Not as a side effect of having a placeholder: a field can be clearable and inherit
        nothing, and that combination is the one that was broken."""
        assert 'meta.zero_as_blank' in _read(RENDER), \
            'the schema key is declared by modules and read by nobody'

    def test_the_validator_reads_the_marks_the_renderer_writes(self):
        body = _fn(_read(RENDER), 'validateAndUpdateNumber')
        assert "hasAttribute('data-zero-as-blank')" in body
        assert "hasAttribute('data-inherit-blank')" in body

    def test_the_three_states_stay_three(self):
        """Blank → null when the field inherits, 0 when it is an on/off amount, and the
        stored value restored only when it is neither. Collapsing any two of them is how a
        cleared box comes back with a number in it."""
        body = _fn(_read(RENDER), 'validateAndUpdateNumber')
        assert 'updateField(target, pathStr, null)' in body      # inherit
        assert 'updateField(target, pathStr, min ?? 0)' in body  # off


class TestEveryDeclaringFieldIsCovered:

    def test_no_module_declares_a_key_the_core_ignores(self):
        """The regression in one line: if a module says `zero_as_blank` the core must act on
        it, whether or not that field also happens to carry a placeholder."""
        render = _read(RENDER)
        declaring = []
        for name, schema in _schemas():
            for field, meta in (schema.get('list') or {}).items():
                if isinstance(meta, dict) and meta.get('zero_as_blank'):
                    declaring.append(f'{name}.{field}')
        assert declaring, 'no field declares it — has the key been renamed?'
        assert 'meta.zero_as_blank' in render, (
            f'{len(declaring)} fields declare zero_as_blank and the renderer never reads it: '
            + ', '.join(declaring[:6]))

    def test_a_clearable_field_is_an_int_or_a_float(self):
        """`zero_as_blank` means "0 is how this stores off". On a string it means nothing, and
        the renderer would never reach the numeric branch that honours it."""
        for name, schema in _schemas():
            for field, meta in (schema.get('list') or {}).items():
                if isinstance(meta, dict) and meta.get('zero_as_blank'):
                    assert meta.get('type') in ('int', 'float'), f'{name}.{field}'

class TestAModuleDefaultCanBeCleared:
    """Reported: clearing a module default filled itself back in on blur, with no placeholder
    showing what the blank would fall back to. Reported twice — the second time for `alert`,
    which had been left out on the theory that "no threshold" is not a state it has. That was
    the wrong reading: at module level a blank never meant "off", it meant "use what the
    system ships with", and the placeholder is what says so.

    A module-level number is the root of the item→module chain, and blanking it has a
    meaning: "use what the system ships with". That is `inherit_blank` — it stores null and
    shows the effective default as the placeholder. Without it the field lands in the branch
    that restores the stored value, which reads as a box refusing to be emptied.
    """

    # Empty, and that is the point: every module default is clearable now. The list existed
    # because `inherit_blank` stores null and a field read as `int(self.get_conf(x))` would
    # have met that null as a TypeError mid-check — so each read was moved to
    # `module_default`, which distinguishes "blank → what the system ships with" from "an
    # explicit 0 → off". A new entry here means somebody skipped that step.
    _UNAUDITED: set = set()

    def test_every_module_number_is_clearable(self):
        offenders = []
        for name, schema in _schemas():
            for field, meta in (schema.get('__module__') or {}).items():
                if not isinstance(meta, dict) or meta.get('type') not in ('int', 'float'):
                    continue
                if meta.get('inherit_blank'):
                    continue
                if f'{name}.{field}' in self._UNAUDITED:
                    continue
                offenders.append(f'{name}.{field}')
        assert not offenders, ('these module defaults cannot be cleared — blanking them '
                               'restores the stored value on blur: ' + ', '.join(offenders))

    def test_the_unaudited_list_does_not_rot(self):
        """A field that gains `inherit_blank` has to leave this list, or it hides the next
        one that appears."""
        stale = []
        for name, schema in _schemas():
            for field, meta in (schema.get('__module__') or {}).items():
                if (isinstance(meta, dict) and meta.get('inherit_blank')
                        and f'{name}.{field}' in self._UNAUDITED):
                    stale.append(f'{name}.{field}')
        assert not stale, f'fixed but still listed as unaudited: {stale}'

    def test_an_item_field_shows_what_it_inherits(self):
        """Reported: "Sites to store" showed no default at all. An ITEM field that inherits
        from its MODULE has `default: null` of its own, and the placeholder cascade only knew
        about the GLOBAL Configuration>Modules value — so it ended at null and the box showed
        nothing, which is exactly what "blank means inherit" must not look like.

        The cascade gained the module step: global → registry → the module's own value →
        the field's schema default."""
        body = _read(RENDER)
        assert 'meta.placeholder_module' in body
        assert '_placeholderModuleValue(pathStr, meta.placeholder_module)' in body

    def test_every_inheriting_item_field_names_its_source(self):
        """A field whose own default is null and that declares no `placeholder_module` shows
        an empty box with nothing to explain it."""
        offenders = []
        for name, schema in _schemas():
            for field, meta in (schema.get('list') or {}).items():
                if not isinstance(meta, dict) or not meta.get('inherit_blank'):
                    continue
                if meta.get('default') is None and not meta.get('placeholder_module'):
                    offenders.append(f'{name}.{field}')
        assert not offenders, ('these inherit but say nothing about what from, so they render '
                               'a blank box with no placeholder: ' + ', '.join(offenders))

    def test_a_cleared_default_reaches_the_check_as_a_number(self):
        """The reason the list existed. `inherit_blank` stores null, and a read like
        `int(self.get_conf(x))` meets that null as a TypeError in the middle of a check —
        a monitor that stops monitoring because a box was emptied.

        `module_default` is the read that survives it, and it keeps the distinction that
        matters: blank falls through to what the system ships with, while an explicit 0 stays
        0 (which for a threshold means off)."""
        from lib.modules.module_base import ModuleBase                # noqa: PLC0415

        class _Fake(ModuleBase):                                       # noqa: D401
            def __init__(self, stored):
                self._stored = stored
                self._monitor = None
            @property
            def is_monitor_exist(self):
                return True
            def get_conf(self, *a, **kw):
                return self._stored
            def _module_schema_defaults(self):
                return {'x': 5}

        assert _Fake({'x': None}).module_default('x', 5) == 5, 'a cleared box broke the read'
        assert _Fake({'x': 0}).module_default('x', 5) == 0, 'an explicit 0 stopped meaning off'
        assert _Fake({'x': 9}).module_default('x', 5) == 9

    def test_a_float_default_stays_a_float(self):
        """cpu's `interval` and ntp's `max_offset` are floats: coercing them to int turns 0.5 s
        of sampling into 0, which is a different measurement rather than a rounder one."""
        from lib.modules.module_base import ModuleBase                # noqa: PLC0415

        class _Fake(ModuleBase):
            def __init__(self, stored):
                self._stored = stored
                self._monitor = None
            @property
            def is_monitor_exist(self):
                return True
            def get_conf(self, *a, **kw):
                return self._stored
            def _module_schema_defaults(self):
                return {'x': 1.0}

        assert _Fake({'x': 0.5}).module_default('x', 1.0) == 0.5
        assert _Fake({'x': None}).module_default('x', 1.0) == 1.0

    def test_a_cleared_default_still_resolves(self):
        """Null must not become 0: the chain falls through to the schema default, which is
        what the placeholder promised the reader."""
        from lib.modules.module_base import ModuleBase                # noqa: PLC0415
        schemas = ModuleBase.discover_schemas(os.path.join(SRC, 'watchfuls'))
        mod = schemas.get('m365|__module__') or {}
        for field in ('sites_top', 'accounts_top', 'breakdown_page'):
            assert mod[field]['default'] > 0, field
            assert mod[field].get('inherit_blank') is True, field


class TestGroupsAreContiguous:
    """The pane emits a group header every time the group CHANGES while it walks
    `__field_order__`. Interleave two groups and the reader gets "Checks / Alerts / Checks /
    Alerts…" down the form — the same heading four times, each with a fragment under it.

    So a module's field order has to visit each group exactly once. It is the kind of thing
    nobody notices until a field is moved between groups and the order is left alone.
    """

    def test_no_module_repeats_a_group_header(self):
        offenders = []
        for name, schema in _schemas():
            lst = {k: v for k, v in (schema.get('list') or {}).items()
                   if isinstance(v, dict) and not k.startswith('__')}
            order = (schema.get('list') or {}).get('__field_order__')
            if not isinstance(order, list):
                continue
            seq = []
            for field in order:
                g = (lst.get(field) or {}).get('group', '')
                if not seq or seq[-1] != g:
                    seq.append(g)
            dupes = [g for g in set(seq) if seq.count(g) > 1]
            if dupes:
                offenders.append(f'{name}: {sorted(dupes)}')
        assert not offenders, ('these field orders jump back to a group they already left, so '
                               'its header is drawn twice: ' + '; '.join(offenders))

    def test_every_group_used_has_a_label(self):
        """An unlabelled group renders as a blank heading, which reads as a rendering bug."""
        import json as _json                                    # noqa: PLC0415
        wf = os.path.join(SRC, 'watchfuls')
        for name, schema in _schemas():
            used = {v.get('group') for v in (schema.get('list') or {}).values()
                    if isinstance(v, dict) and v.get('group')}
            if not used:
                continue
            lp = os.path.join(wf, name, 'lang', 'es_ES.json')
            if not os.path.isfile(lp):
                continue
            labels = (_json.load(io.open(lp, encoding='utf-8-sig')) or {}).get('group_labels') or {}
            missing = used - set(labels)
            assert not missing, f'{name}: grupos sin etiqueta {sorted(missing)}'

class TestAnAmountAndItsUnitAreOneQuestion:
    """"Warn under 50 GB" is one thing to decide, and it was two rows: the number on one and
    the unit on the next, leaving the reader to assemble it. A field declares which sibling
    holds its unit and the core draws that sibling attached to the box — the same field, in a
    better place.

    Declared, never guessed: pairing `*_min` with `*_unit` by name would work until a module
    ships a field the convention does not fit."""

    def test_the_pairing_is_declared(self):
        body = _read(RENDER)
        assert 'meta.unit_field' in body, 'the schema key is declared and read by nobody'
        assert 'function _unitSelect' in body

    def test_the_unit_loses_its_own_row(self):
        """Otherwise it appears twice: attached to the amount AND on a row of its own."""
        body = _read(RENDER)
        assert '_claimedUnits' in body
        assert '!_claimedUnits.has(k)' in body

    def test_the_unit_selector_has_a_stated_width(self):
        """Reported from a screenshot: the dropdown drew its chevron and no text. Bootstrap
        gives a `.form-select` inside an `.input-group` `flex:1 1 auto; width:1%`, so clearing
        only the growth leaves the 1% behind and the control collapses to ~13px — three
        options present, nowhere to draw them.

        The width has to be STATED. And it lives in a class, not inline, so the next control
        that needs it does not re-derive the same fix."""
        import os as _os                                          # noqa: PLC0415
        css = _read(_os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-unit-sel' in css, 'the unit selector has no class of its own'
        rule = css[css.index('.ss-unit-sel'):]
        rule = rule[:rule.index('}')]
        assert 'width:' in rule.replace(' ', '') or 'width :' in rule
        assert 'flex-grow-0' not in _read(RENDER),             'flex-grow-0 alone leaves the width:1% that collapsed it'
        assert 'ss-unit-sel' in _fn(_read(RENDER), '_unitSelect')

    def test_the_unit_still_writes_through_the_same_field(self):
        """It is the same config field — drawn elsewhere, stored identically. A bespoke write
        path is how the two copies start disagreeing."""
        assert 'updateField(' in _fn(_read(RENDER), '_unitSelect')

    def test_every_declared_unit_exists_and_has_options(self):
        """A `unit_field` pointing at a field that is missing, or that has no options, draws
        an empty select next to the amount — worse than the two rows it replaced."""
        for name, schema in _schemas():
            for scope in ('list', '__module__'):
                sec = schema.get(scope) or {}
                for field, meta in sec.items():
                    if not isinstance(meta, dict) or not meta.get('unit_field'):
                        continue
                    unit = sec.get(meta['unit_field'])
                    assert isinstance(unit, dict), f'{name}.{scope}.{field} → missing unit'
                    assert unit.get('options'), f'{name}.{scope}.{field} → unit has no options'

    def test_the_shipped_pairs_are_paired(self):
        """Every amount that has a unit beside it declares the pairing — the regression is a
        new amount+unit landing as two rows again."""
        for name, schema in _schemas():
            for scope in ('list', '__module__'):
                sec = schema.get(scope) or {}
                claimed = {m['unit_field'] for m in sec.values()
                           if isinstance(m, dict) and m.get('unit_field')}
                orphan = [k for k, v in sec.items()
                          if isinstance(v, dict) and k.endswith('_unit') and k not in claimed]
                assert not orphan, f'{name}.{scope}: units nobody claims → {orphan}'


