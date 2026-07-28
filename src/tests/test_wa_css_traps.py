#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markup that does not do what the class name suggests.

Two traps, both found the same afternoon by looking at the Status table, both invisible in
review and obvious on screen.

**A class that ignores the theme.** The panel ships light and dark and remembers which you
chose, so a component that decides its own colours is right half the time. Bootstrap's
``.table-light`` sets a light background AND dark text regardless of ``data-bs-theme``, so
in dark mode the check table wore a white strip with black letters across the top — the only
light thing on the page. It was in three templates by the time anyone looked: two written
the same week from the same habit, the third old enough that nobody saw it any more. That is
the argument for a guard rather than three fixes.

**A cell that stops being a cell.** ``d-flex`` on a ``<td>`` takes it out of
``display: table-cell``, so it no longer takes part in the row's height and its bottom border
draws at the height of its own content. The row separator then breaks at that one column
while every other table in the panel keeps a straight line.

The checks are deliberately narrow and mechanical — the vocabulary that is banned and the
class that replaced it — not "does this look right", which no test can answer.
"""

import io
import os
import re

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'lib', 'web_admin', 'templates')
CSS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'lib', 'web_admin', 'static', 'css', 'web_admin.css')

# Only what is theme-blind WHEREVER it appears.
#
# `bg-light` is deliberately NOT here, and the reason is worth stating: a `badge bg-light
# text-dark` sitting inside a primary button is light against the BUTTON, not against the
# page, so it is correct in both themes. Banning it outright would have flagged five
# templates that are right and taught the next person to disable the test.
#
# `table-light` and `text-bg-light` have no such defence: a table header and a badge sitting
# on a card are both page furniture, and both were found wearing daylight on a dark page.
_THEME_BLIND = ('table-light', 'text-bg-light')


def _templates():
    for root, _dirs, files in os.walk(TPL):
        for f in files:
            if f.endswith('.html'):
                yield os.path.join(root, f)


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


class TestTheScanItself:

    def test_templates_are_found(self):
        assert sum(1 for _ in _templates()) > 50


class TestATableCellStaysATableCell:
    """Not a theme bug, but found chasing one and it belongs with the other "the browser is
    not doing what the class name suggests" traps.

    `d-flex` on a `<td>` takes it out of `display: table-cell`. The cell stops taking part in
    the row's height, so its bottom border draws at the height of its own content — and the
    row separator visibly breaks at that one column while every other table in the panel
    keeps a straight line. The flex goes on a wrapper INSIDE the cell.
    """

    def test_no_cell_is_turned_into_a_flex_container(self):
        bad = []
        for path in _templates():
            for m in re.finditer(r'<td[^>]*class="([^"]*)"', _read(path)):
                if re.search(r'\bd-flex\b', m.group(1)):
                    bad.append(f'{os.path.relpath(path, TPL)}: {m.group(1)}')
        assert not bad, (
            'these <td> elements are flex containers, so their row separator breaks at that '
            'column: ' + ', '.join(bad) + ' — wrap the content in a span instead')


class TestNoTemplatePinsALightSurface:

    def test_none_of_the_theme_blind_classes_is_used(self):
        """A component that picks its own background is right in one theme and wrong in the
        other; there is no version of it that is right in both."""
        bad = []
        for path in _templates():
            src = _read(path)
            for cls in _THEME_BLIND:
                # `class="… table-light …"` only — not a mention inside a comment or a name
                # that merely contains the word.
                if re.search(r'class="[^"]*\b' + re.escape(cls) + r'\b', src):
                    bad.append(f'{os.path.relpath(path, TPL)}: {cls}')
        assert not bad, (
            'these pin a light surface regardless of the theme: ' + ', '.join(bad)
            + ' — use a Bootstrap variable (--bs-tertiary-bg …) or .ss-thead/.ss-thead-sticky')

    def test_the_replacement_exists_and_is_theme_driven(self):
        """The class the tables use instead has to take its colour FROM the theme, or this
        guard would just have moved the problem behind a nicer name."""
        css = _read(CSS)
        for cls in ('.ss-thead', '.ss-thead-sticky'):
            m = re.search(re.escape(cls) + r'\s*\{([^}]*)\}', css)
            assert m, f'{cls} is gone — the tables that use it would have no header colour'
            body = m.group(1)
            assert 'var(--bs-' in body, f'{cls} hardcodes a colour again'
            # A background alone is too subtle at this size: in the dark theme the first
            # attempt used --bs-tertiary-bg and the column titles floated over the data with
            # nothing separating them. The rule under the header is what reads as "titles
            # end here".
            assert 'border-bottom' in body, f'{cls} separates the titles by shade alone'

    def test_the_tables_that_had_it_use_the_replacement(self):
        """Named explicitly: these three are where it was found, and a silent revert to
        `table-light` in any of them is the regression this file exists for."""
        for rel in ('partials/status/_view_table.html',
                    'partials/modules/_view_table.html',
                    'partials/cfg/auth/_group_role_map.html'):
            src = _read(os.path.join(TPL, *rel.split('/')))
            assert re.search(r'<thead class="ss-thead(-sticky)?"', src), \
                f'{rel} no longer uses the theme-aware header'
