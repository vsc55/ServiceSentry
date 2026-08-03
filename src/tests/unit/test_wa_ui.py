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


# ──────────────────────────── Dark mode ────────────────────────────


# ──────────────────────────── Config dark mode ─────────────────────


# ──────────────────────────── Internationalisation ─────────────────


# ──────────────────────────── UI reorganisation ────────────────────


# ──────────────────────── Overview as its own page ─────────────────


