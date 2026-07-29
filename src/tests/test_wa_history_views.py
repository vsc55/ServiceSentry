#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History has two views, and the second one is about the series it never talks about.

The section is a chart with a series list beside it, and the chart is the point: one series
at a time, or several overlaid. The sidebar is navigation — names and a coloured dot — which
is right for picking a series and hides two facts the index already carries:

* which series STOPPED recording. A check that was removed, renamed, or has been failing to
  produce a sample leaves its history behind, and the sidebar draws it exactly like a healthy
  one. You find out by clicking it and seeing an empty right-hand edge.
* which checks have the worst uptime. It is in every entry; the sidebar turns it into a
  three-colour dot, and you cannot sort dots.

So the inventory is one row per series with the numbers, sortable, and clicking a row goes
back to the chart with that series selected — which is what you were going to do next.

The guards below are mostly about the two views not drifting apart (one filter, one uptime
scale) and about the staleness rule being stated rather than hidden: a threshold nobody can
see is a badge nobody can trust.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
H = os.path.join(TPL, 'partials', 'history')
VIEWS = os.path.join(H, '_views.html')
RENDER = os.path.join(H, '_render.html')
SERIES = os.path.join(H, '_series.html')
INVENTORY = os.path.join(H, '_view_inventory.html')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _strip_comments(js: str) -> str:
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


class TestTheScanItself:

    def test_every_file_is_found(self):
        for p in (VIEWS, RENDER, SERIES, INVENTORY):
            assert os.path.isfile(p), p

    def test_the_registry_lists_both_views(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const HISTORY_VIEWS'):]
        reg = reg[:reg.index('];')]
        for vid in ('chart', 'inventory'):
            assert f"id: '{vid}'" in reg, f'{vid} is not in the registry'

    def test_the_bundle_includes_them_in_order(self):
        js = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        assert js.index('history/_views.html') < js.index('history/_render.html')
        assert js.index('history/_view_inventory.html') > js.index('history/_views.html')


class TestTheTwoViewsAreOneSection:

    def test_one_filter_drives_both(self):
        """Typing in either and switching must not silently change which series you are
        looking at."""
        body = _fn(_strip_comments(_read(SERIES)), '_historyOnSearch')
        assert '_historyIsChart()' in body
        assert '_historyRenderSeriesList()' in body and '_historyRenderInventory()' in body
        inv = _fn(_strip_comments(_read(VIEWS)), '_historyFilteredIndex')
        assert '_historyFilter' in inv

    def test_one_uptime_scale(self):
        """The table and the sidebar dot must not disagree about what counts as healthy."""
        body = _fn(_strip_comments(_read(VIEWS)), '_historyUptimeClass')
        assert '95' in body and '80' in body
        assert '_historyUptimeClass(' in _strip_comments(_read(INVENTORY))

    def test_the_chart_tools_are_hidden_in_the_inventory(self):
        """Compare, the range picker and auto-refresh act on a chart. Leaving them there
        would offer controls that do nothing when used."""
        src = _strip_comments(_read(RENDER))
        assert '${_historyIsChart() ? `<button class="btn btn-sm btn-secondary" id="history-compare-btn"' in src

    def test_switching_stops_the_auto_refresh(self):
        """It exists to redraw a chart that is no longer on screen; a page left on the
        inventory would poll for nothing."""
        body = _fn(_strip_comments(_read(VIEWS)), 'setHistoryView')
        assert '_historyStopTimer()' in body
        assert '_historyRenderLayout()' in body

    def test_the_chart_comes_back_the_way_it_was(self):
        """Switching away and back must redraw the selected series rather than dropping the
        user on the placeholder."""
        body = _fn(_strip_comments(_read(VIEWS)), '_historyRestoreAfterLayout')
        assert '_historyLoadChart()' in body
        assert '_historyShowPlaceholder()' in body

    def test_the_initial_render_does_not_chart_into_the_inventory(self):
        """renderHistory restores the last series; with no chart in the DOM there is nothing
        to draw into, no toolbar to show and no timer worth arming."""
        src = _strip_comments(_read(RENDER))
        assert 'if (!_historyIsChart()) return;' in src


class TestTheInventoryAnswersWhatTheDotCannot:

    def test_it_is_sortable(self):
        """"Which of my hundred checks are the worst" is the question, and you cannot sort
        dots."""
        src = _strip_comments(_read(INVENTORY))
        assert '_thSortInner(' in src and 'function _hInvSortBy' in src

    def test_its_columns_behave_like_every_other_table(self):
        """Reported: the columns did not fit their content and could not be resized. The table
        was hand-written markup rather than the panel's column machinery, so it got none of
        it — the browser shared the width evenly and the two name columns ended up as narrow
        as the number beside them."""
        src = _strip_comments(_read(INVENTORY))
        assert '_attachColFeatures(' in src, 'no reorder/resize/fit'
        assert 'ss-th-resizable' in src and 'ss-th-fit' in src
        assert 'data-col=' in src and 'draggable="true"' in src
        assert 'data-fit' in src, 'content-fit cells are not marked, so they stretch again'

    def test_the_saved_order_cannot_hide_a_column(self):
        """A saved order from an older build must drop ids that no longer exist and append the
        ones it has never seen, or a new column would be invisible to anyone who had ever
        dragged a header."""
        body = _fn(_strip_comments(_read(INVENTORY)), '_hInvOrdered')
        assert 'known.has(id)' in body and '_hInvOrder.includes(c.id)' in body

    def test_the_cells_follow_the_column_order(self):
        """A row that built its cells in a fixed order would put the values under the wrong
        titles the moment a column moved."""
        src = _strip_comments(_read(INVENTORY))
        assert 'function _hInvCell' in src
        assert 'cols.map(c =>' in _fn(src, '_hInvRow')

    def test_the_filter_sits_with_the_view_switcher(self):
        """It is the only control the inventory has, and its own row above the table spent a
        whole band on one input. The chart view keeps its copy in the series sidebar, where the
        list it filters is."""
        src = _strip_comments(_read(RENDER))
        i_input = src.index('id="history-series-filter"')
        i_switch = src.index('_historyViewSwitcher()')
        assert i_input < i_switch, 'the inventory filter is no longer beside the switcher'
        assert src.count('id="history-series-filter"') == 2, \
            'the two views no longer each have their own filter box'

    def test_it_opens_worst_first(self):
        """The reason to open this view is the bottom of the list, so it starts there."""
        src = _strip_comments(_read(INVENTORY))
        assert "let _hInvSort = 'uptime'" in src
        assert "let _hInvDir  = 'asc'" in src

    def test_a_stopped_series_is_marked(self):
        src = _strip_comments(_read(INVENTORY))
        assert '_historyIsStale(' in src
        assert "t('hist_stale')" in src

    def test_the_staleness_rule_is_stated_on_screen(self):
        """A threshold nobody can see is a badge nobody can trust."""
        src = _strip_comments(_read(INVENTORY))
        assert "t('hist_stale_hint')" in src
        for lang in ('en_EN', 'es_ES'):
            txt = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            m = re.search(r"'hist_stale_hint':\s*'([^']*)'", txt)
            assert m, lang
            assert '24' in m.group(1), f'{lang}: the hint no longer names the threshold'

    def test_never_recorded_is_not_drawn_as_very_old(self):
        """A series with no last sample has no age; "—" and "412d" are different statements."""
        body = _fn(_strip_comments(_read(VIEWS)), '_historyAgeText')
        assert "return '—'" in body

    def test_a_row_opens_its_chart(self):
        """This is a list you read to decide what to look at; making the user find a small
        link at the end of the row would add a step to the only thing anybody does here."""
        src = _strip_comments(_read(INVENTORY))
        assert '_historyOpenFromInventory(' in src
        body = _fn(src, '_historyOpenFromInventory')
        assert "setHistoryView('chart')" in body, 'selecting a series leaves you on the list'
        assert '_historyCollapsed.delete(mod)' in body, \
            'the chart opens with its series hidden inside a collapsed group'


class TestTheLabelsExist:

    def test_both_views_are_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for vid in ('chart', 'inventory'):
                assert f"'hist_view_{vid}':" in src, f'{lang} does not name the {vid} view'

    def test_every_column_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('hist_col_series', 'hist_col_points', 'hist_col_uptime',
                        'hist_col_last', 'hist_col_value', 'hist_stale', 'hist_stale_hint'):
                assert f"'{key}':" in src, f'{lang} is missing {key}'
