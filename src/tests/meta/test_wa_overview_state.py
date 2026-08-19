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
accent colour is NOT a usable proxy: the fail2ban card is amber when the jail is *enabled*, so
tinting by accent would paint a permanent warning over a service working exactly as intended.

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
        src = _js('_dwStateClass')
        assert '_dwStatContent[id]' in src and '_dwTableRows[id]' in src, (
            'the class is not derived from what was last fetched')

    def test_it_answers_nothing_for_a_widget_with_no_view(self):
        """Spacers and module widgets have no `view`; asking them for a state must be a
        no-op rather than an exception thrown mid-render, which would blank the dashboard."""
        assert "if (!view) return ''" in _js('_dwStateClass')


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
