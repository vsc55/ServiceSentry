#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A menu that opens where there is room for it, not where its parent happens to be.

A sidebar section with more than one view opens a flyout to its right. The flyout is
``position: fixed`` on purpose — the sidebar clips its overflow, and a menu drawn inside that
box would be cut off at the rail's edge — so its ``top``/``left`` are computed in JS from the
parent item's rectangle every time it opens.

Computed as *the parent's top*, which is only right while there is room below it. SNMP sits
near the foot of the rail and carries five views: the last entries were drawn past the bottom
of the screen, behind the taskbar. Unreachable, and — because ``position: fixed`` does not
scroll with anything — with no scrollbar anywhere to say that there was more menu.

The fix is the ordinary rule for a floating layer: the parent's rectangle is a *preference*,
the viewport is the constraint. Slide the menu up until it fits; when it is taller than the
screen at all, pin it and let it scroll. The same on the other axis, so a rail against the
right edge opens its menus to the left instead of off the screen.

Geometry is not a thing a Python test can measure — nothing here renders. What it pins is that
the code still *asks* the viewport, and the order it asks in: an element that is
``display: none`` has no box, so the class that opens the menu has to be on before anything is
measured.
"""

import os
from tests.helpers import _fn, _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
WIRING = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'init', '_sidebar.html')


def _place() -> str:
    return _fn(_read(WIRING), '_placeFlyout')


class TestTheViewportIsTheConstraint:

    def test_the_bottom_edge_is_read_and_not_assumed(self):
        """`window.innerHeight`, not the parent's rectangle alone. Without this the menu is
        placed correctly relative to its item and wrongly relative to the screen."""
        body = _place()
        assert 'window.innerHeight' in body, 'the placement never asks how tall the screen is'
        assert 'getBoundingClientRect()' in body, 'it no longer follows its parent at all'

    def test_a_menu_that_would_hang_off_the_bottom_slides_up(self):
        """The whole bug: the last views of a section low in the rail were behind the taskbar.
        Anchoring the BOTTOM to the viewport keeps every entry on screen and leaves the top
        alignment in place whenever it already fitted."""
        body = _place()
        assert 'vh - h' in body, 'nothing pulls the menu up when it overflows the bottom'
        assert 'if (top + h' in body, 'the overflow is never tested for'

    def test_a_menu_taller_than_the_screen_scrolls(self):
        """Sliding up cannot help past this point — there is no position where it fits. Pinned
        to the top with a cap and its own scrollbar, which is at least reachable."""
        body = _place()
        assert 'maxHeight = (vh' in body, 'a menu taller than the screen is still cut off'
        assert "overflowY = 'auto'" in body, 'capped with no way to reach the rest'

    def test_the_right_edge_is_the_same_problem(self):
        """One axis fixed and the other left alone is the same defect in a narrower window."""
        body = _place()
        assert 'window.innerWidth' in body, 'the horizontal overflow is unguarded'
        assert 'r.left - w' in body, 'it never opens to the left of its item'


class TestWhatMeasuringRequires:

    def test_a_previous_cramped_opening_leaves_nothing_behind(self):
        """The cap and the scrollbar are set on the element itself. Not cleared, the next
        opening measures a menu that is still wearing the last one's `max-height` — and keeps
        a scrollbar for content that now fits."""
        body = _place()
        assert "maxHeight = ''" in body and "overflowY = ''" in body, \
            'the inline cap is never reset, so the placement measures its own last answer'
        assert body.index("maxHeight = ''") < body.index('offsetHeight'), \
            'the reset happens after the measurement, which is the same as not resetting'

    def test_the_menu_is_open_before_it_is_measured(self):
        """`display: none` has no box: `offsetHeight` is 0 and every clamp above computes from
        zero. The class goes on first and the placement follows — an ordering, not a detail."""
        body = _fn(_read(WIRING), '_openFlyout')
        assert body.index("classList.add('ss-fly-open')") < body.index('_placeFlyout('), \
            'the menu is placed while it is still display:none, so it has no height to fit'
