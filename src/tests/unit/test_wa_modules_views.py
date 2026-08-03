#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modules has four layouts now, and they must stay four layouts — not four renderers.

The section had one: a grid of cards, each expanding its configuration inside a 420px cell.
That layout already admitted the cell was too small — it carried a "full screen" button that
reopened the same body in a modal, which is a workaround for the container, not a feature. So
three more were written to compare against it: list-and-detail, a dense table, and compact
status tiles with a full-width editor.

**A view is chrome and navigation. Nothing else.** What a module's configuration looks like is
`renderModuleBody()`, used verbatim by every view. The moment a view renders a field itself,
there are four places to fix a field bug and three of them will be missed. That is the rule
this file exists to hold, and most of what follows is one form of it:

* no view builds a module's body — they call the shared renderer;
* no view decides on its own what an "item" is, or whether a module is unavailable, or who
  may edit it — `_modFacts()` answers that once;
* the switcher, the filter and the selection are section state, not per-view state, so
  changing view keeps what you had typed and selected.

The other half is about the things a layout change quietly breaks: the view-only permission,
the deep-link that auto-expands a freshly added item, and a module whose dependencies are
missing — which must not be offered an editor whose fields cannot take effect.
"""

import io
import os
import re

MOD = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                   'lib', 'web_admin', 'templates', 'partials', 'modules')
VIEW_FILES = {
    'cards':   '_list.html',
    'split':   '_view_split.html',
    'table':   '_view_table.html',
    'compact': '_view_compact.html',
}


def _read(name: str) -> str:
    return io.open(os.path.join(MOD, name), encoding='utf-8-sig').read()


def _core() -> str:
    return _read('_views.html')


def _registry() -> list:
    m = re.search(r'const MOD_VIEWS = \[(.*?)\];', _core(), re.S)
    assert m, 'the view registry is gone'
    return re.findall(r"\{\s*id:\s*'([^']+)'.*?label_key:\s*'([^']+)'.*?render:\s*'([^']+)'",
                      m.group(1), re.S)




class TestAViewIsChromeOnly:
    """The rule the whole split rests on."""

    def test_no_view_builds_a_module_body_itself(self):
        """Every view shows a configuration through the one renderer. A view that assembled
        fields would be a fourth copy of the form, and a field bug would then have four
        homes and three of them would be missed."""
        for view, fname in VIEW_FILES.items():
            src = _read(fname)
            if view == 'cards':
                continue        # the shared renderer lives in this file
            assert 'renderModuleBody(' not in src or '_modRenderBodyInto' in src, (
                f'{fname} calls the body renderer directly; go through _modRenderBodyInto so '
                'the view-only case is applied in one place')

    def test_the_view_only_case_is_applied_in_one_place(self):
        """`_applyReadonly` on a body the user may not edit. Four views remembering to call
        it is three chances to forget, and forgetting means offering an editor that silently
        discards what is typed into it."""
        body = re.search(r'function _modRenderBodyInto\(.*?\n\}', _core(), re.S)
        assert body and '_applyReadonly' in body.group(0)
        for view, fname in VIEW_FILES.items():
            if view == 'cards':
                continue
            assert '_applyReadonly' not in _read(fname), \
                f'{fname} applies the read-only rule itself'

    def test_no_view_counts_items_itself(self):
        """What counts as an "item" was written twice before this split and the two copies
        were already the kind of rule that drifts."""
        counter = re.search(r'function _modItemCounts\(.*?\n\}', _core(), re.S)
        assert counter, 'the shared counter is gone'
        for fname in VIEW_FILES.values():
            src = _read(fname)
            assert 'Object.keys(cfg[k]).length' not in src, \
                f'{fname} counts items on its own again'

    def test_no_view_decides_availability_itself(self):
        """`__missing_deps__` / `__unsupported__` are read in one function. A view that read
        them again could disagree with the list next to it about whether a module works."""
        for fname in VIEW_FILES.values():
            src = _read(fname)
            for flag in ('__missing_deps__', '__unsupported__', '__partial_deps__'):
                assert flag not in src, f'{fname} reads {flag} directly instead of _modFacts'








