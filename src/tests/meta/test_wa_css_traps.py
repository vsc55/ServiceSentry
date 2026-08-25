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

    def test_a_list_section_can_ask_out_of_the_reading_width(self):
        """Reported from the screen, with an arrow drawn at the empty band: the tokens table
        was capped at the same 76rem as the forms, so it squeezed its own columns while a
        strip of page sat unused to its right.

        The escape is generic and driven by the ACTIVE pane — the body is shared by every
        section and only one is on screen at a time — so the next wide section opts in with
        the same class and no new rule. A `#acctab-tokens` selector here would be per-id CSS
        for layout, which is the thing this file exists to stop."""
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        m = re.search(r'\.ss-account-body:has\([^)]*\.ss-wide\)\s*\{([^}]*)\}', css)
        assert m, 'no escape from the reading width — a table section squeezes for nothing'
        assert 'max-width' in m.group(1) and 'none' in m.group(1)
        assert '#acctab' not in css, 'per-id CSS decides an account section layout'
        assert 'ss-wide' in self._account_page(), 'no section claims it'

    def test_a_list_section_drops_the_card_frame_as_well(self):
        """Reported from the screen: "the other tables are not in a card, and they have a
        filter section". The reading-width escape above was only half of it — a list boxed in
        a card inside a settings page is a frame drawn inside a frame, while every other list
        in the panel IS its section and runs to all four edges.

        `.ss-fullbleed` is already that class everywhere else, and it flattens the cards
        inside it on its own. What is shell-specific is the gutter: here it is padding on the
        scroll box rather than `.container-fluid`'s, so the shell drops it at the source
        instead of cancelling it a second time with the negative margins."""
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        m = re.search(r'\.ss-shell-main\s*>\s*\.ss-vscroll:has\([^)]*\.ss-fullbleed[^)]*\)\s*\{([^}]*)\}', css)
        assert m, 'a full-bleed pane inside the shell still sits in the shell gutter'
        assert 'padding: 0' in m.group(1)
        assert re.search(r'\.ss-shell-main\s+\.ss-fullbleed\s*\{[^}]*margin:\s*0', css), (
            'the container-fluid gutters are cancelled a second time inside the shell')
        assert 'ss-fullbleed' in self._account_page(), 'no account section claims it'

    def test_a_full_bleed_list_reaches_the_bottom_of_the_pane(self):
        """Reported from the screen: "in the other tables the bottom stretches down to the
        foot of the page".

        `.ss-vfill` only grows when its parent is a flex column, and between the shell and the
        pane sit two plain boxes — the reading-width body and the `.tab-content`. So the card
        stopped at the height of its rows and left the rest of the pane empty, which is the one
        thing full-bleed was supposed to fix. The chain is rebuilt only while a full-bleed pane
        is the open one, because those same boxes carry the form sections, which have to keep
        flowing and scrolling."""
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        chain = [m for m in re.finditer(r'([^{}]+)\{([^}]*)\}', css)
                 if '.ss-fullbleed' in m.group(1) and '> * > .tab-content' in m.group(1)]
        assert chain, 'nothing makes the boxes between the shell and a full-bleed pane fill'
        sel, body = chain[0].group(1), chain[0].group(2)
        assert 'display: flex' in body and 'flex: 1 1 auto' in body and 'min-height: 0' in body
        # The pane itself is part of the chain and NOT covered by its own `.ss-vfill`:
        # Bootstrap's `.tab-content > .active { display: block }` outranks a single class, so
        # a pane that carries the class still lays out as a block and nothing inside it grows.
        # Every list section outside the shell names the active pane explicitly for the same
        # reason.
        assert '> .tab-content > .tab-pane.active' in sel, (
            'the active pane is left out of the chain, so Bootstrap keeps it display:block')
        box = re.search(r'\.ss-shell-main\s*>\s*\.ss-vscroll:has\([^)]*\.ss-fullbleed[^)]*\)\s*\{([^}]*)\}', css)
        assert box and 'overflow: hidden' in box.group(1), (
            'the shell box still scrolls around a card that scrolls — two scrollbars, and a '
            'table header that scrolls away')
        # The first link, and the one that was missing: `.ss-vscroll` is `flex: 1 1 auto`
        # WITHOUT being a flex container, so telling its child to grow was a no-op — right in
        # the stylesheet, wrong on the screen, which is the only kind of bug this file catches.
        assert 'display: flex' in box.group(1), (
            'the shell scroll box is not a flex column, so nothing inside it can grow')

    def test_the_cards_are_capped_without_being_centred(self):
        """A cap so two cards of form fields sit side by side and no further — past that a
        password box a metre wide is not more readable. Left-aligned, which is the half the
        centred version got wrong."""
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        m = re.search(r'\.ss-account-body\s*\{([^}]*)\}', css)
        assert m, '.ss-account-body is gone — the cards stretch to whatever the monitor is'
        assert 'max-width' in m.group(1)
        assert 'margin' not in m.group(1), 'a margin here is how it gets centred again'
class TestACardCannotAskForAnAccentThatDoesNotExist:
    """Reported from the screen as "you are adding a gap between the filter bar and the title".

    There was no gap. The card's accent strip is 3px tall and `ss-accent-violet` had no colour
    rule, so it painted 3px of card background between the filter bar's hairline and the
    header's own band — a seam that reads as dead space, next to sections where the same 3px
    is a coloured line tying the two together.

    The stylesheet already has a fallback for an accent with no variant at all, written for
    exactly this ("an invisible strip reads as a broken card rather than as a missing rule").
    It cannot catch this one: the element DOES carry an `ss-accent-*` class, it just names a
    colour nobody defined. A typo in a variant name is not something CSS can refuse, so it is
    refused here instead."""

    def test_every_accent_a_template_asks_for_is_defined(self):
        used = set()
        for root, _dirs, files in os.walk(TPL):
            for f in files:
                if f.endswith('.html'):
                    used |= set(re.findall(r"accent:\s*'([a-z]+)'", _read(os.path.join(root, f))))
        defined = set(re.findall(r'\.ss-accent-([a-z]+)\s*\{', _read(CSS)))
        assert used, 'no card asks for an accent — the scan is looking in the wrong place'
        missing = used - defined
        assert not missing, f'accents named by a card but never given a colour: {missing}'


class TestARailReachesTheBottomOfItsCard:
    """Reported from the screen: the rail stopped after its two items and the rest of the
    card was empty.

    `.ss-railbox` is `flex: 1 1 auto`, which means nothing unless its parent is a flex
    COLUMN — and the list-table factory hands a view's body to a plain `.ss-vscroll`, which
    is a flex item without being a flex container. The stylesheet already knew that and fixed
    it for `> .ss-railbox`.

    Then a view put a summary header above its rail. The wrapper that holds both is one box
    between them, `> .ss-railbox` stopped matching, and the layout silently went back to what
    the rule existed to prevent. Nothing in the markup or the stylesheet was wrong to read —
    it is the shape of the tree that changed, which is why this is asked of both.
    """

    def _rule(self):
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        for m in re.finditer(r'\.ss-vscroll:has\(([^)]*)\)\s*\{([^}]*)\}', css):
            if 'railbox' in m.group(1):
                return m
        return None

    def test_the_scroll_box_around_a_rail_becomes_a_column(self):
        m = self._rule()
        assert m, 'nothing turns the body that holds a rail into a flex column'
        body = m.group(2)
        assert 'display: flex' in body and 'flex-direction: column' in body, (
            'the rail is told to grow inside a box that is not a flex container, which is a '
            'no-op — right in the stylesheet, wrong on the screen')
        assert 'overflow: hidden' in body, (
            'the box scrolls around a rail that scrolls: two scrollbars, and the rail head '
            'scrolls away with the page')

    def test_it_matches_a_rail_anywhere_below_it_and_not_only_a_child(self):
        """The regression itself. A view is entitled to put a header above its rail, and the
        rule has to keep holding when it does."""
        sel = self._rule().group(1)
        assert '>' not in sel, (
            'back to a child selector: one wrapper between the body and the rail and the '
            'rail draws at the height of its own items again')
        assert '.ss-railbox' in sel

    def test_nothing_between_the_body_and_the_rail_breaks_the_chain(self):
        """The other half: the rule passes the height DOWN, and a wrapper that is not a link
        in the fill chain keeps it. `.ss-vfill` is that link."""
        for path in _templates():
            src = _code(path)
            i = src.find('ss-railbox')
            if i < 0:
                continue
            j = src.rfind('return `', 0, i)
            assert j >= 0, path
            # The whole opening tag, not just a class attribute: a wrapper with NO class at
            # all is the shape this is about, and a pattern that required one would have
            # skipped exactly the case it exists to catch.
            for attrs in re.findall(r'<(?:div|section|nav|main)(|\s[^>]*)>', src[j:i]):
                assert 'ss-vfill' in attrs, (
                    f'{os.path.basename(path)}: <div{attrs}> sits between the body and the '
                    'rail without passing the height down')


class TestARowHoverThatPaintsTheWholeTable:
    """A hover meant for one row, applied to the container of forty.

    The configuration sheet lights up the field row under the cursor, which is right for a
    field — a label and its control on one line. The notification routing matrix is not one
    of those: it is a whole TABLE inside a single `cfg-field-wrap`, so the rule painted the
    wrapper and every row in it changed colour at once. Reported from the screen in exactly
    those words: "hovering one row changes the colour of all of them".

    A table brings its own row hover (`.table-hover` + `.ss-hover-rows`) and that is the one
    that means something, so the container's must stand aside — the same `:not(:has(table))`
    the dashboard widgets already use, for the same reason.
    """

    def _css(self):
        return _read(CSS)

    def test_the_field_hover_stands_aside_for_a_table(self):
        rule = [ln for ln in self._css().splitlines()
                if '.cfg-field-wrap' in ln and ':hover' in ln and 'background' in ln]
        assert rule, 'the field hover is gone — this guard needs updating with what replaced it'
        assert all(':not(:has(table))' in ln for ln in rule), rule

    def test_the_routing_matrix_is_still_one_wrap_around_a_table(self):
        """Which is what makes the guard necessary: change this to a wrap per ROW and the
        rule above stops mattering — but nothing would tell you it had."""
        src = _read(os.path.join(TPL, 'partials', 'cfg', 'notify', '_routing.html'))
        assert 'cfg-field-wrap' in src and '<table' in src

    def test_the_table_carries_its_own_row_hover(self):
        """Because the container no longer paints anything, this IS the hover now. Without
        it the fix would read as "the highlight disappeared".

        And it is the ACCENT one: this table's group headers are filled with the same grey a
        default hover uses, so the row under the cursor read as another heading rather than as
        a selection — reported in those words right after the first fix landed.
        """
        src = _read(os.path.join(TPL, 'partials', 'cfg', 'notify', '_routing.html'))
        assert 'table-hover' in src and 'ss-hover-accent' in src
        css = self._css()
        assert '.ss-hover-accent' in css, 'the class it asks for is not defined'
        # …and the two are actually different colours, which is the whole point.
        grey = css.split('.ss-hover-rows {')[1].split('}')[0]
        accent = css.split('.ss-hover-accent {')[1].split('}')[0]
        assert grey.strip() != accent.strip()
