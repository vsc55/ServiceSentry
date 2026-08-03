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


class TestTheScanItself:

    def test_the_registry_is_found(self):
        assert len(_registry()) >= 2

    def test_every_view_file_exists(self):
        for f in VIEW_FILES.values():
            assert os.path.isfile(os.path.join(MOD, f))




class TestTheSectionOwnsTheState:

    def test_the_switcher_is_driven_by_the_registry(self):
        """Adding a view must be one entry, not an entry plus a button plus a branch."""
        core = _core()
        # The enumeration moved into the shared `_viewSwitcher` (core/_utils.html) once six
        # sections had grown their own copy of the same button group — the registry each of
        # them keeps is the part that differs, and it is the argument. The rule is unchanged:
        # a view is one entry, never an entry plus a button plus a branch.
        assert '_viewSwitcher(MOD_VIEWS' in core, 'the switcher enumerates the views by hand again'
        pane = _read('_pane.html')
        assert 'id="modViewSwitcher"' in pane
        assert 'setModulesView(' not in pane, 'a view is hardcoded in the markup'

    def test_the_chosen_view_survives_a_reload(self):
        assert re.search(r"localStorage\.(get|set)Item\(_MOD_VIEW_KEY", _core())

    def test_the_filter_is_shared_by_every_view(self):
        """Typing a filter and switching view must not silently show everything again."""
        core = _core()
        assert 'function _modVisibleNames' in core and '_modMatches' in core
        for fname in VIEW_FILES.values():
            assert 'toLowerCase().includes' not in _read(fname), \
                f'{fname} filters on its own; the term would mean two things'

    def test_the_filter_matches_id_and_display_name(self):
        """Half the time you remember one and half the time the other."""
        body = re.search(r'function _modMatches\(.*?\n\}', _core(), re.S).group(0)
        assert 'f.name' in body and 'f.pretty' in body


class TestWhatALayoutChangeBreaksQuietly:

    def test_the_render_entry_point_is_still_one_function(self):
        """Everything that mutates modules calls renderModules() — a dozen call sites in
        actions/ and clusters/. The views hang off it; they do not replace it."""
        src = _read('_list.html')
        assert re.search(r'^function renderModules\(\)', src, re.M)
        assert 'MOD_VIEWS.find(' in src, 'renderModules no longer dispatches to a view'

    def test_an_unknown_stored_view_falls_back(self):
        """A stale localStorage value (a view that was removed) must not leave the section
        blank — which is what dispatching to `undefined` would do."""
        assert 'MOD_VIEWS.some(v => v.id === stored)' in _core()
        assert re.search(r'typeof draw === .function. \? draw : _modViewCards', _read('_list.html'))

    def test_the_expand_modal_is_still_refreshed(self):
        """It shows a module's body too. Without this, an item added while it is open
        appears in the list behind and not in the modal in front."""
        src = _read('_list.html')
        assert 'function _modSyncExpandModal' in src
        assert '_modSyncExpandModal(' in re.search(
            r'function renderModules\(\).*?\n\}', src, re.S).group(0)

    def test_the_auto_expand_deep_link_is_preserved(self):
        """Adding an item sets _autoExpandItemPath so the next render opens and scrolls to
        it. The capture has to happen before any HTML is generated, because generating it is
        what consumes the flag."""
        body = re.search(r'function renderModules\(\).*?\n\}', _read('_list.html'), re.S).group(0)
        i_capture = body.index('_savedAutoExpand = _autoExpandItemPath')
        assert i_capture < body.index('MOD_VIEWS.find(')

    def test_the_count_badge_keeps_its_id_in_every_view(self):
        """`_refreshModuleCount()` updates it in place after an item switch, without a full
        re-render. A view that drew the count without the id would freeze it."""
        assert "id=\"modcount-" in _core()
        for fname in VIEW_FILES.values():
            src = _read(fname)
            assert 'modcount-' not in src or fname == '_list.html', \
                f'{fname} draws its own count badge instead of the shared one'

    def test_an_unavailable_module_is_not_offered_an_editor(self):
        """Missing dependencies or an unsupported platform: the fields cannot take effect, so
        a form that looks editable is worse than saying why there is none."""
        for fname in ('_view_split.html', '_view_compact.html', '_view_table.html'):
            assert 'unavailable' in _read(fname), f'{fname} ignores the unavailable case'
        split = _read('_view_split.html')
        i_guard = split.index('if (f.unavailable)')
        i_body = split.index('_modRenderBodyInto(body, name)')
        assert i_guard < i_body, 'the split view renders the editor before checking'


class TestTheSelectionIsHonest:

    def test_a_selection_that_is_no_longer_shown_falls_back(self):
        """Deleted, or filtered away: leaving the detail pane on it would show a module with
        nothing highlighting it in the list beside."""
        body = re.search(r'function _modSelected\(.*?\n\}', _read('_view_split.html'), re.S).group(0)
        assert 'names.includes(stored)' in body and 'names[0]' in body

    def test_the_compact_editor_closes_when_its_module_goes(self):
        body = re.search(r'function _modViewCompact\(.*?\n\}', _read('_view_compact.html'),
                         re.S).group(0)
        assert 'names.includes(editing)' in body


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        keys = [label for _id, label, _fn in _registry()] + ['mod_view', 'mod_search']
        for lang in ('es_ES', 'en_EN'):
            src = io.open(os.path.join(os.path.dirname(os.path.dirname(MOD)), '..', '..',
                                       'i18n', 'lang', f'{lang}.py'),
                          encoding='utf-8-sig').read()
            for k in keys:
                assert f"'{k}'" in src, f'{lang} has no label for {k}'
