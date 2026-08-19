#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A widget that is reporting trouble tints its whole surface.

The accent bar every stat card already had is 3px at the top of one tile among twenty, and a
dashboard is scanned, not read. Asked for from the panel: "can the widgets that detect errors
change their background colour when they go warning or error".

Two rules hold the design together, and both are here because the obvious implementation
breaks them:

**The state travels with the widget's own data.** A stat card says `state` in the content it
serves; a table says `state_rows` in its view, meaning "having rows IS the problem". The core
never holds a list of which widgets are allowed to go red — which matters because a
module-contributed widget has to be able to do this by saying the same word, and because the
accent colour is NOT a usable proxy for it: at the time this was written the fail2ban card was
amber when the jail was *enabled*, so tinting by accent would have painted a permanent warning
over a service working exactly as intended. That accent has since been corrected — but the
argument stands, because an accent is chosen to make a card readable and a state says whether
something is wrong, and nothing keeps those two in step.

**The tint is applied through the variable the cards already paint themselves from.**
`--ss-surface-bg` is redefined on the widget wrapper, so the CSS knows nothing about any card's
markup. Repainting the card directly would need one selector per card shape, and the next shape
added would silently stay grey.
"""

import os
import re

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'overview')
WIDGETS = os.path.join(TPL, '_widgets.html')
RENDER = os.path.join(TPL, '_render.html')
CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')


def _js(name: str) -> str:
    return _strip_comments(_fn(_read(WIDGETS), name))


class TestTheStateComesFromTheData:

    def test_a_stat_card_is_tinted_from_its_own_content(self):
        src = _js('_dwStatFetch')
        assert '_dwApplyState(' in src, 'the fetched content never reaches the tint'
        assert '.state' in src, 'the tint is not read from the content the widget served'

    def test_a_table_is_tinted_only_when_it_says_rows_are_the_problem(self):
        """Every table has rows. Only a table of active issues is in trouble for it."""
        src = _js('_dwTableFetch')
        assert 'view.state_rows' in src, 'tables are tinted without asking whether rows mean it'
        assert 'length ? view.state_rows' in src, (
            'an empty table of problems must clear the tint, not keep the last one')

    def test_the_two_states_are_the_only_two(self):
        """`ok` is deliberately not a state: green is the absence of a problem, and twenty
        cards painting themselves for being fine is a dashboard with no signal in it."""
        src = _js('_dwApplyState')
        assert set(re.findall(r"'dw-state-(\w+)'", src)) == {'error', 'warn'}

    def test_the_core_names_no_widget(self):
        """The whole point of the data-driven design: a module's widget gets this by saying
        the same word, without the core learning its name."""
        for name in ('_dwApplyState', '_dwStateClass'):
            src = _js(name)
            for wid in ('checks', 'incidents', 'syslog', 'servers', 'modules'):
                assert f"'{wid}'" not in src, f'{name} names the {wid} widget'


class TestTheTintSurvivesARedraw:

    def test_a_rebuilt_grid_keeps_it(self):
        """A drag, a resize or a filter rebuilds the grid from cache. Without this the tint
        vanishes on the first interaction and returns at the next poll — a flicker with no
        cause, which is worse than never having tinted."""
        assert '_dwStateClass(' in _read(RENDER), 'the rebuilt grid drops the state class'
        src = _js('_dwState')
        assert '_dwStatContent[id]' in src and '_dwTableRows[id]' in src, (
            'the state is not derived from what was last fetched')

    def test_content_swapped_in_place_is_re_stated(self):
        """Three paths rewrite `.dw-content` and never touch the wrapper's classes: the
        soft auto-refresh, a module widget's scope change, and its level filter. Each one
        can change what the card is reporting."""
        assert '_dwRefreshState(dw)' in _read(RENDER), 'the auto-refresh leaves a stale tint'
        layout = _read(os.path.join(TPL, '_layout.html'))
        assert layout.count('_dwRefreshState(dw)') >= 2, (
            'changing a module widget scope or level leaves the previous state painted')

    def test_a_spacer_is_never_asked(self):
        """A spacer has no data and no view. Asking it must be a no-op rather than an
        exception thrown mid-render, which would blank the whole dashboard."""
        src = _js('_dwState')
        assert '_dwIsSpacer(id)' in src
        assert "if (!view) return ''" in src


class TestAModulesWidgetTintsItselfToo:
    """Not a second mechanism: a module already publishes a `state` per entry — it is what
    sorts its rows worst-first and colours its usage ring — so the tint is the worst of the
    ones that instance is actually showing."""

    def test_it_reuses_the_rank_the_rows_are_sorted_by(self):
        src = _js('_dwModuleState')
        assert '_dwMwRank(' in src, 'a second severity scale for the same states'
        assert '_dwMwSortFilter(' in src, 'the level filter is ignored'

    def test_it_only_looks_at_what_that_instance_shows(self):
        """A card scoped to one kind must not go red for a kind it is not displaying, or
        the tint stops describing the card it is painted on."""
        src = _js('_dwModuleState')
        for token in ('mws', 'mwlvl', 'def.scope'):
            assert token in src, f'{token} is not taken into account'

    def test_the_dispatcher_sends_module_widgets_there(self):
        assert '_dwIsModuleWidget(id)' in _js('_dwState')


class TestTheCssTouchesNoCardMarkup:

    def test_the_tint_goes_through_the_surface_variable(self):
        css = _read(CSS)
        m = re.search(r'\.dw-state-warn\s*\{([^}]*)\}', css)
        assert m, 'no .dw-state-warn rule'
        assert '--ss-surface-bg' in m.group(1), (
            'the rule paints something directly instead of redefining the variable every '
            'card already reads — that needs one selector per card shape')

    def test_both_states_have_a_rule(self):
        css = _read(CSS)
        assert re.search(r'\.dw-state-error\s*\{[^}]*--ss-surface-bg', css)

    def test_it_is_a_class_and_not_a_widget_id(self):
        """The panel's rule: reusable classes for layout behaviour, never per-id CSS."""
        css = _read(CSS)
        for rule in re.findall(r'^[^\n{]*\.dw-state-\w+[^\n{]*\{', css, re.M):
            assert '#' not in rule, f'per-id selector in a widget-state rule: {rule.strip()}'
