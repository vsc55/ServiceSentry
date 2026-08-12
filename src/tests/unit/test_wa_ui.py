#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UI routes: /, /api/v1/me, /api/v1/health, /lang/<code>.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_ui.py`` lives in ``tests/integration/test_wa_ui.py``."""

import pytest


# ──────────────────── Package-contributed web assets ────────────────────


# ──────────────────────── SPA shell stylesheet ────────────────────────

class TestPaneDisplayRules:
    """The SPA shell shows exactly one pane at a time via Bootstrap's
    `.tab-content > .tab-pane { display: none }`.  That rule is class-based (0-1-0), so ANY
    unqualified `#tab-*` rule setting `display` (1-0-0) outranks it and pins that pane on
    screen underneath every other section — which is what History did: once opened, its tall
    pane stayed rendered below Syslog/Servers/Services, pushing them off the viewport and
    dragging the sticky sidebar away.  Layout rules for a pane must be scoped to `.active`."""

    def _css(self):
        from pathlib import Path
        import lib.web_admin as wa
        return (Path(wa.__file__).parent / 'static' / 'css' / 'web_admin.css').read_text(
            encoding='utf-8')

    def test_no_unqualified_pane_display_rule(self):
        import re
        css = self._css()
        # Selector blocks whose selector list contains a bare `#tab-<name>` (no `.active`,
        # no descendant/child part) — those are top-level SPA panes.
        for sel, body in re.findall(r'([^{}]+)\{([^}]*)\}', css):
            selectors = [s.strip() for s in sel.split(',')]
            bare_pane = [s for s in selectors if re.fullmatch(r'#tab-[a-z0-9-]+', s)]
            if bare_pane and re.search(r'(^|;)\s*display\s*:', body):
                pytest.fail(
                    f'{bare_pane[0]} sets `display` unqualified — it beats Bootstrap\'s '
                    f'.tab-pane{{display:none}} and pins the pane on screen. Scope it to '
                    f'{bare_pane[0]}.active')

    def test_history_fullbleed_display_is_scoped(self):
        """The History pane's full-bleed flex layout stays, but only while active."""
        assert '#tab-history.active {' in self._css()


# ─────────────────── Collapsing the sidebar, and un-collapsing it ───────────────────

class TestCollapsingIsExpandingBackwards:
    """Reported twice, about two different parts of the same column: expanding does something
    and collapsing just blinks.

    Both had the same cause. `display: none` cannot be transitioned, so hiding a thing drops it
    in one frame, while showing it lands it in a column that is still growing and the .15s
    width appears to bring it in. One motion, two different-looking directions, decided by
    which way the button was pressed.

    So nothing in the navigation is hidden by `display` any more: the label and the caret fade
    over the same .15s, kept in flow and clipped by the sidebar's own `overflow: hidden`, and
    the icon holds its position instead of being re-centred — a row that rearranges itself
    underneath a fade is the jump the fade was meant to remove.
    """

    def _css(self):
        from pathlib import Path                                        # noqa: PLC0415
        import lib.web_admin as wa                                      # noqa: PLC0415
        return (Path(wa.__file__).parent / 'static' / 'css' / 'web_admin.css').read_text(
            encoding='utf-8')

    def test_nothing_in_the_nav_is_hidden_by_display(self):
        css = self._css()
        for sel in ('.ss-layout.ss-mini .ss-sb-label',
                    '.ss-layout.ss-mini .ss-sb-caret'):
            i = css.index(sel + ' {')
            block = css[i:css.index('}', i)]
            assert 'opacity: 0' in block, f'{sel} does not fade'
            assert 'display' not in block, f'{sel} is hidden by display, which cannot animate'
        for sel in ('.ss-sb-label {', '.ss-sb-caret {'):
            i = css.index(sel)
            assert 'transition' in css[i:css.index('}', i)], f'{sel} has nothing to animate'

    def test_the_icon_does_not_move_when_the_label_goes(self):
        """Re-centring the icon in the 56px rail moved it while the label beside it was still
        fading. The padding it already has puts it within a pixel of that centre — measured in a
        browser: 19px from the edge in both states."""
        css = self._css()
        i = css.index('.ss-layout.ss-mini .ss-sb-item {')
        block = css[i:css.index('}', i)]
        assert 'justify-content' not in block, 'the row re-centres itself under the fade'
        assert 'padding: .55rem 1rem' in block
        item = css.index('.ss-sb-item {')
        assert 'transition: padding' in css[item:css.index('}', item)]

    def test_the_brand_row_is_the_documented_exception(self):
        """It centres what is left of it, so a label that merely faded would keep its width
        there and push the hamburger — the control that expands the column again — off the
        edge."""
        css = self._css()
        assert '.ss-layout.ss-mini .ss-sb-brand-text { display: none; }' in css


# ──────────────────────────── Dark mode ────────────────────────────


# ──────────────────────────── Config dark mode ─────────────────────


# ──────────────────────────── Internationalisation ─────────────────


# ──────────────────────────── UI reorganisation ────────────────────


# ──────────────────────── Overview as its own page ─────────────────


