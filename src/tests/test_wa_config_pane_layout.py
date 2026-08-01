#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Configuration header has to stay on screen for the WHOLE section.

The toolbar (title, Reload, Save + its unsaved-changes badge) and the search box are the
controls you reach for *because* you scrolled: you find a field, change it, and press Save.
They were pinned with ``position: sticky``, and that pinned them for about one screenful —
then the header slid up and out, exactly where the config list gets long enough to need it.

Sticky was never going to work here, and the reason is a rule this panel sets deliberately
elsewhere: an **active tab-pane is a flex column bounded by the viewport**
(``.container-fluid > .tab-content > .tab-pane.active`` — ``flex: 1 1 auto; min-height: 0``
inside a ``.ss-main`` that is ``height: 100vh``). A sticky element only travels as far as its
containing block, and that block is one screen tall no matter how long the content is. The
content overflows it; the header goes with the block.

The mechanism that does work is the one the rest of the panel already uses: the header keeps
its natural height and the body below it becomes the scroller (``.ss-vscroll``). Then the
header cannot scroll away — there is no scrolling underneath it to carry it off.

So these tests pin the shape, not the pixels: which element scrolls, and that the header is
not left depending on sticky again.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'cfg', '_pane.html')
CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')


def _pane() -> str:
    return io.open(PANE, encoding='utf-8-sig').read()


def _css() -> str:
    return io.open(CSS, encoding='utf-8-sig').read()


def _code(html: str) -> str:
    """Markup only — the Jinja comment explaining the fix names ``position:sticky``."""
    return re.sub(r'\{#.*?#\}', '', html, flags=re.S)


class TestTheScanItself:

    def test_the_pane_is_found(self):
        assert 'id="tab-config"' in _pane()

    def test_the_fill_helpers_exist(self):
        css = _css()
        assert '.ss-vscroll {' in css and '.ss-vfill   {' in css


class TestTheBodyScrolls:

    def test_the_config_body_is_the_scroller(self):
        m = re.search(r'id="config-container"[^>]*class="([^"]*)"', _pane())
        assert m, 'config-container has no class — it cannot be the scroll box'
        assert 'ss-vscroll' in m.group(1), (
            'the config list does not scroll on its own, so the page scrolls instead and '
            'takes the header with it')

    def test_the_scroller_has_a_gutter(self):
        """Plain flowing cards, not a table: without it the scrollbar sits on the content's
        right edge and the last card touches the frame."""
        m = re.search(r'id="config-container"[^>]*class="([^"]*)"', _pane())
        assert 'ss-scroll-pad' in m.group(1)
        assert '.ss-scroll-pad {' in _css()

    def test_the_gutter_is_not_baked_into_the_scroll_helper(self):
        """`.ss-vscroll` is used by table bodies that want neither padding — a generic
        helper that carries one section's taste stops being reusable."""
        m = re.search(r'\.ss-vscroll \{([^}]*)\}', _css())
        assert m and 'padding' not in m.group(1)


class TestTheSeamBetweenHeaderAndBody:
    """Where the pinned header meets the moving body is the one edge a user actually looks
    at, and both ways of getting it wrong were visible in the same screenshot."""

    def test_the_header_card_has_no_bottom_margin(self):
        """A 1rem strip of page background sat between the card and the scrolling body, and
        rows sliding underneath surfaced *in* it — a floating seam that read as a bug. The
        card's own border is the boundary."""
        head = _pane().split('id="config-container"')[0]
        search_box = re.search(r'<div class="([^"]*)" id="cfgSearchBox"', head)
        assert search_box, 'the search box is gone — this guard needs updating'
        assert 'mb-' not in search_box.group(1), (
            'the header card has a bottom margin again, so there is a gap of page '
            'background for scrolled rows to appear in')

    def test_the_header_sits_on_the_edge_not_inside_the_padding(self):
        """It is the top of the section, not a card floating in it: full width, flush with
        the frame, square on top — and rounded only at the bottom, which is the line the
        body disappears under."""
        head = _pane().split('id="config-container"')[0]
        assert 'ss-bleed-top' in head
        rules = re.search(r'\.ss-bleed-top > :first-child \{(.*?)\}', _css(), re.S)
        assert rules, 'the squared-off top is gone'
        assert 'border-top-left-radius: 0' in rules.group(1)
        assert 'border-top-right-radius: 0' in rules.group(1)

    def test_the_bottom_stays_rounded(self):
        head = _pane().split('id="config-container"')[0]
        assert 'rounded-bottom-3' in head, (
            'the card lost its bottom curve — that curve is what reads as "the body slides '
            'under here"')

    def test_the_bleed_cancels_exactly_the_padding_above_it(self):
        """The negative top margin is arithmetic against two paddings in the shell. If
        either changes, the bar stops being flush and nothing else would say so."""
        dash = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'dashboard.html'),
                       encoding='utf-8-sig').read()
        assert 'class="container-fluid pt-2' in dash, 'the container padding changed'
        assert 'class="tab-content pt-1"' in dash, 'the tab-content padding changed'
        # pt-2 (.5rem) + pt-1 (.25rem)
        assert re.search(r'\.ss-bleed-top \{ margin: -\.75rem', _css()), \
            'the bleed no longer cancels .75rem — the header will not sit flush'

    def test_the_cut_is_faded_not_sliced(self):
        m = re.search(r'id="config-container"[^>]*class="([^"]*)"', _pane())
        assert 'ss-scroll-fade' in m.group(1)
        assert '.ss-scroll-fade {' in _css()

    def test_the_fade_is_not_baked_into_the_scroll_helper(self):
        """Same reason as the gutter: `.ss-vscroll` is shared with table bodies that have
        their own sticky header row and must not be masked."""
        m = re.search(r'\.ss-vscroll \{([^}]*)\}', _css())
        assert m and 'mask' not in m.group(1)

    def test_the_fade_is_short(self):
        """Long enough to soften the edge, short enough never to hide a row being read."""
        m = re.search(r'\.ss-scroll-fade \{(.*?)\}', _css(), re.S)
        px = {int(v) for v in re.findall(r'#000 (\d+)px', m.group(1))}
        assert px and max(px) <= 16, f'the fade covers {max(px)}px of real content'


class TestTheHeaderDoesNotGoBackToSticky:

    def test_the_header_is_not_positioned(self):
        """It is held in place by being outside the scroller, which is what makes it hold
        for the whole section instead of for one screenful."""
        assert 'position:sticky' not in _code(_pane()).replace(' ', ''), (
            'the Configuration header is sticky again — inside a viewport-bounded pane that '
            'pins it for one screen and then lets it scroll away')

    def test_the_pane_is_still_a_flex_column(self):
        """The whole arrangement rests on it: without the column, the body has no height to
        scroll within and the header has nothing holding it."""
        css = _css()
        m = re.search(r'\.container-fluid > \.tab-content > \.tab-pane\.active \{([^}]*)\}', css)
        assert m, 'the rule that makes an active pane a bounded flex column is gone'
        body = m.group(1)
        assert 'flex-direction: column' in body and 'min-height: 0' in body

    def test_the_shell_is_the_bounded_one(self):
        """`.ss-main` being a fixed 100vh scroll container is exactly why a pane inside it is
        one screen tall — the fact that made sticky unable to work."""
        m = re.search(r'\.ss-main\s+\{([^}]*)\}', _css())
        assert m and 'height: 100vh' in m.group(1) and 'overflow-y: auto' in m.group(1)


class TestTheSearchBoxIsCollapsed:
    """It is for finding one setting among many — not something you need in view the rest of
    the time. Hiding it used to cost one thing: a filter left on while the box was closed showed
    a fraction of the configuration with nothing on screen saying why. Closing it now clears the
    term, so that state cannot happen at all."""

    def test_it_starts_closed(self):
        head = _pane().split('id="config-container"')[0]
        m = re.search(r'<div class="collapse([^"]*)" id="cfgSearchBox"', head)
        assert m, 'the search box is not a collapse, or its id changed'
        assert 'show' not in m.group(1), 'it opens by default again'

    def test_the_toggle_targets_it(self):
        head = _pane().split('id="config-container"')[0]
        assert 'data-bs-target="#cfgSearchBox"' in head
        assert 'aria-expanded="false"' in head, 'the closed state is not announced'
        assert 'aria-controls="cfgSearchBox"' in head

    def test_closing_the_box_clears_the_filter(self):
        """**The trap, closed at the source.** A filter left running from a control that is no
        longer on screen leaves most of the configuration hidden and looks like data loss. It
        used to be survivable because a warning dot sat on the toggle; clearing the term is
        better, and the dot went with the state it warned about — a badge for something that
        cannot happen is one more thing to keep true."""
        wiring = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                      'init', '_wiring.html'), encoding='utf-8-sig').read()
        i = wiring.index("getElementById('cfgSearchBox')?.addEventListener('hidden.bs.collapse'")
        assert "_filterConfig('')" in wiring[i:i + 400]
        assert 'badgeCfgFilter' not in _pane(), 'a badge for a state that cannot happen'

    def test_the_toolbar_closes_the_card_when_the_box_is_hidden(self):
        """With nothing under it, the bar IS the bottom of the card and has to be shaped like
        one — a square bottom edge with nothing below reads as a panel that failed to render."""
        m = re.search(r'\.ss-toolbar\.ss-toolbar-attached:has\(\+ \.collapse:not\(\.show\)\) \{(.*?)\}',
                      _css(), re.S)
        assert m, 'the collapsed case does not restore the bottom radius'
        assert 'border-bottom-left-radius' in m.group(1)
        assert 'border-bottom-right-radius' in m.group(1)

    def test_the_rounded_bottom_is_visible_in_light_mode_too(self):
        """Reported as "the light toolbar is missing its rounded bottom corners". It was not:
        the radius is theme-independent, and both themes had it.

        What differs is the only thing that can DRAW that curve. `.ss-bleed-top` removes the
        side and top borders, so the bottom border is the whole shape — and the dark theme
        redefines --bs-border-color to a value LIGHTER than the bar it sits on, while the
        light theme inherits Bootstrap's #dee2e6 against a #e9ecef bar. Two greys a dozen
        points apart render a corner nobody can see.

        Guarded because the next person to read the CSS will find a radius that is already
        correct and conclude there is nothing to fix — which is exactly what makes a contrast
        bug like this come back.
        """
        m = re.search(r'\[data-bs-theme="light"\] \.ss-bleed-top > \* \{(.*?)\}', _css(), re.S)
        assert m, 'the light theme no longer strengthens the pinned header border'
        assert 'border-color' in m.group(1)
        assert 'var(--bs-border-color)' not in m.group(1), \
            'it points back at the theme default — the value the corner disappeared against'

    def test_the_shadow_follows_the_rounded_corner(self):
        """A box-shadow traces the border-radius of the element that DECLARES it. The shadow
        is declared on the wrapper; the rounded bottom belongs to the child inside it. So the
        corner looked rounded while its own shadow broke off square right beside it.

        The wrapper draws nothing itself — no background, no border — so the radius exists
        purely to shape the shadow, which is exactly the kind of line a later cleanup deletes
        as dead. Hence this guard, and the comment beside it.
        """
        # The selector carries more than one rule (a margin reset elsewhere), so pick the one
        # that actually casts the shadow rather than whichever comes first in the file.
        blocks = [b for b in re.findall(r'\.cfg-main > \.ss-bleed-top \{(.*?)\}', _css(), re.S)
                  if 'box-shadow' in b]
        assert blocks, 'the pinned header no longer casts the shadow this guards'
        body = blocks[0]
        assert 'border-bottom-left-radius' in body and 'border-bottom-right-radius' in body, \
            'the shadow is back to tracing a square corner under a rounded one'
        assert 'border-radius-lg' in body, \
            'the radius no longer matches the toolbar and the search box, which both use lg'

    def test_opening_it_puts_the_cursor_in_it(self):
        wiring = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                      'init', '_wiring.html'), encoding='utf-8-sig').read()
        assert "'shown.bs.collapse'" in wiring and "getElementById('cfgSearch')" in wiring


class TestTheControlsAreStillThere:
    """A layout change must not quietly drop a control out of the header."""

    def test_the_header_holds_them_all(self):
        src = _pane()
        head = src.split('id="config-container"')[0]
        for ident in ('btnReloadConfig', 'btnSaveConfig', 'badgeConfigDirty', 'cfgSearch'):
            assert f'id="{ident}"' in head, f'{ident} is no longer above the scrolling body'
