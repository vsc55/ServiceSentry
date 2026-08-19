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

**A button the colour of the thing it sits on.** ``btn-dark`` is not theme-blind — it is
correct in the light theme and nearly invisible in the dark one, where it lands within a
shade or two of the card surface (#181818 / #212121 / #2a2a2a). Reported from a screenshot of
the auto-refresh split button: with the interval off, the control disappeared into the header
and only the little caret gave away that anything was there. A refresh button nobody can see
while it is off is a button nobody finds to turn on.

The replacement is ``.ss-btn-graphite``, a solid dark button one step up the same neutral
greyscale the dark theme is built from — quiet, which is right for an off state, without
becoming the card it sits on. Grey and not a tinted dark on purpose: a blue-ish slate was
tried first and read as a colour that had wandered in from another palette.

The checks are deliberately narrow and mechanical — the vocabulary that is banned and the
class that replaced it — not "does this look right", which no test can answer.
"""

import os
import re
from tests.helpers import _read

TPL = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                   'lib', 'web_admin', 'templates')
CSS = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
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


def _code(path: str) -> str:
    """Markup and script only. The comment that explains why a class was abandoned names it,
    so a guard reading the prose would flag the very file that fixed the problem."""
    src = re.sub(r'\{#.*?#\}', '', _read(path), flags=re.S)
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return re.sub(r'^\s*//.*$', '', src, flags=re.M)


class TestTheScanItself:

    def test_templates_are_found(self):
        assert sum(1 for _ in _templates()) > 50


class TestNoControlWearsTheSurfaceColour:
    """Reported from a screenshot: the auto-refresh split button, with the interval off, was a
    `btn-dark` on a dark card — within a shade of the surface, so only its caret showed."""

    def test_no_button_uses_btn_dark(self):
        bad = [os.path.relpath(path, TPL) for path in _templates()
               if re.search(r'btn-dark\b', _code(path))]
        assert not bad, (
            'these controls wear btn-dark, which in the dark theme is nearly the card surface '
            'they sit on: ' + ', '.join(sorted(set(bad)))
            + ' — use .ss-btn-graphite, the panel’s dark solid button')

    def test_the_auto_refresh_off_state_uses_the_graphite_button(self):
        """Named explicitly because it is where it was found, and because the off state is the
        one a silent revert would hide again: nobody notices a button that is only wrong while
        it is doing nothing."""
        # In core/, not in a section: six sections draw this control, so it is not the
        # property of whichever one happened to write it first.
        src = _read(os.path.join(TPL, 'partials', 'core', '_auto_refresh.html'))
        m = re.search(r'const btnCls = `btn btn-sm \$\{[^`]*`', src)
        assert m, 'the auto-refresh button classes moved — this guard needs re-aiming'
        assert 'ss-btn-graphite' in m.group(0)

    def test_the_graphite_button_is_not_one_of_the_surfaces(self):
        """The whole point of it: a dark button that is still a button. If it ever gets defined
        in terms of a surface variable it is back to being invisible on that surface."""
        css = _read(CSS)
        m = re.search(r'\.btn\.ss-btn-graphite\s*\{([^}]*)\}', css)
        assert m, '.ss-btn-graphite is gone — the off state has nothing to wear'
        body = m.group(1)
        assert 'background-color:' in body and 'color:' in body
        for surface in ('--bs-body-bg', '--bs-secondary-bg', '--bs-tertiary-bg'):
            assert surface not in body, f'the graphite button is painted with {surface}'

    def test_it_stays_on_the_neutral_ramp(self):
        """A tinted dark was tried first and read as a colour from another palette: the dark
        theme is a neutral greyscale, so its one dark button has to be grey too — which for a
        hex triplet means all three channels equal."""
        css = _read(CSS)
        m = re.search(r'\.btn\.ss-btn-graphite\s*\{([^}]*)\}', css)
        assert m
        for hexval in re.findall(r'#([0-9a-fA-F]{6})', m.group(1)):
            r, g, b = hexval[0:2], hexval[2:4], hexval[4:6]
            assert r == g == b, f'#{hexval} is tinted — the dark button drifted off the greys'


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


class TestAnSvgWithNoSizeFillsWhateverItIsGiven:
    """The QR is shipped with a `viewBox` and no width or height on purpose — a square sized
    by the server is one that does not fit somebody's phone at arm's length. The cost of that
    decision is that it inherits its container, and an unconstrained container is the whole
    dialog: at `modal-lg` it drew 800px wide and pushed the key and the confirmation field
    below the fold, so the one thing the screen exists to show was the one thing off it.

    Reported on screen, which is where this class of thing is always found. The guard is on
    the CLASS rather than on the markup, because the fix has to hold for the next place that
    shows one."""

    def test_the_qr_class_caps_its_width(self):
        css = _read(CSS)
        m = re.search(r'\.ss-qr\s*\{([^}]*)\}', css)
        assert m, '.ss-qr is gone — the QR would fill whatever box it lands in'
        body = m.group(1)
        assert 'width' in body, '.ss-qr sets no width, which is the bug it exists to prevent'
        # `min(...)` and not a flat width: a phone narrower than the cap must get the width it
        # has rather than a square wider than the dialog it is in.
        assert 'min(' in body, '.ss-qr must cap the width WITHOUT overflowing a narrow screen'

    def test_the_svg_inside_it_is_told_to_scale(self):
        """Capping the box does nothing on its own: an SVG with no width is not laid out by
        its parent's width unless it is told to take it."""
        css = _read(CSS)
        m = re.search(r'\.ss-qr\s+svg\s*\{([^}]*)\}', css)
        assert m, '.ss-qr svg has no rule — the box would be capped and the square would not'
        assert 'width' in m.group(1) and 'height' in m.group(1)

    def test_every_qr_in_the_markup_goes_through_it(self):
        """A second place that drops an SVG into a dialog without the class inherits the bug
        rather than the fix."""
        loose = []
        for path in _templates():
            src = _read(path)
            for m in re.finditer(r'\$\{\s*(?:d|out|res)\.svg\s*\}', src):
                window = src[max(0, m.start() - 200):m.start()]
                if 'ss-qr' not in window:
                    loose.append(os.path.relpath(path, TPL))
        assert not loose, ('a QR is drawn without .ss-qr in: ' + ', '.join(sorted(set(loose))))


class TestARuleThatHidesABarNothingElseDrives:
    """`#infraSubTabs, #accessSubTabs, #ipbanSubTabs, #tab-events .nav-tabs { display: none }`
    hides those sub-tab bars because the SIDEBAR carries the same sub-tabs — the panes still
    switch, from another control. That is safe there and only there: a bar that nothing else
    duplicates is, once hidden, half a page with no way in.

    /account is exactly that case. It has no sidebar sub-items, so its own bar is the only
    route to the security half — the password and the second factor. The guard is on the RULE
    rather than on the markup because the failure is silent: the pane renders, the fields are
    in the DOM, `getElementById` finds them, and there is simply no control on screen that
    brings them up.
    """

    def _hiding_selectors(self):
        """Every selector in the stylesheet whose block hides what it matches."""
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        out = []
        for m in re.finditer(r'([^{}]+)\{([^}]*)\}', css):
            if re.search(r'display\s*:\s*none', m.group(2)):
                out.extend(part.strip() for part in m.group(1).split(','))
        return out

    def test_the_scan_finds_the_rule_it_is_about(self):
        assert any('#accessSubTabs' == s for s in self._hiding_selectors()), \
            'the sidebar-driven bars are no longer hidden — this guard is reading nothing'

    def test_the_account_nav_is_not_swept_into_it(self):
        for sel in self._hiding_selectors():
            assert '#accountTabs' not in sel, \
                f'{sel} hides the account section list — its security half becomes unreachable'
            assert not ('#tab-account' in sel and 'nav' in sel), \
                f'{sel} hides the account section list — its security half becomes unreachable'

    def test_the_account_page_still_ships_that_nav(self):
        """Renaming the id without touching the check above would leave the check passing on
        an id that no longer exists."""
        src = _code(os.path.join(TPL, 'partials', 'account', '_page.html'))
        assert 'id="accountTabs"' in src, 'the account section list is gone or renamed'
        assert 'ss-rail' in src


class TestASettingsPageThatFillsItsPane:
    """`/account` is laid out with the panel's own rail shell — the one Configuration and
    Modules use — and not with a layout of its own. Two of those were built first and both
    were reported from the screen: a 640px card stack with `mx-auto`, which on a wide monitor
    left more empty page than page, and a horizontal tab bar over it, sitting where the
    section title goes.

    The guard is on the shape rather than on the look: a `max-width` is fine and a `mx-auto`
    with one is the thing that was wrong, because it puts the settings in a column down the
    middle of a frame that is supposed to be filled."""

    def _account_page(self) -> str:
        return _code(os.path.join(TPL, 'partials', 'account', '_page.html'))

    def test_it_hangs_on_the_shared_shell(self):
        src = self._account_page()
        for cls in ('ss-shell', 'ss-rail', 'ss-rail-item', 'ss-shell-main'):
            assert cls in src, f'{cls} is gone — the account page has a layout of its own again'

    def test_it_is_not_a_centred_column(self):
        assert 'mx-auto' not in self._account_page(),             'the account page centres itself again — the shell has to fill the pane'

    def test_the_cards_are_capped_without_being_centred(self):
        """A cap so two cards of form fields sit side by side and no further — past that a
        password box a metre wide is not more readable. Left-aligned, which is the half the
        centred version got wrong."""
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        m = re.search(r'\.ss-account-body\s*\{([^}]*)\}', css)
        assert m, '.ss-account-body is gone — the cards stretch to whatever the monitor is'
        assert 'max-width' in m.group(1)
        assert 'margin' not in m.group(1), 'a margin here is how it gets centred again'
