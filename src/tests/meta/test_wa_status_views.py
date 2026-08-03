#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Status has four layouts, and they must all agree about which check is failing.

Status is a monitoring surface, so its layouts differ in one thing: how fast they answer
"what is broken right now". The card grid answers it slowly — you scroll past everything
green to find the two that are not — so three more sit beside it: a summary with the totals
and problems ordered first, a flat table of checks, and a wall of tiles.

**What must never differ is what a check MEANS.** Whether a result is ok / warning / error,
what its display name is, and the value-vs-threshold decoration its module declares in
`__status_render__` are decided once and every view draws from that. A view that read
`status` and `severity` for itself would be free to disagree with the card next to it about
the same check — and on a page whose whole job is to say what is wrong, two panels
contradicting each other is worse than either being wrong alone.

The distinction that costs the most to lose is **warning vs error**. A soft threshold breach
is amber, not red; colouring both red is how a page full of "everything is on fire" stops
being read at all, and it is exactly the sort of thing that gets re-derived slightly
differently in a fourth place.

The rest is about what a redraw must not do: switching view, filtering, or ticking "only
problems" all look at the SAME data, so none of them may re-fetch — on a page that
auto-refreshes, a redraw that fetches also races its own timer.
"""

import io
import os
import re

ST = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                  'lib', 'web_admin', 'templates', 'partials', 'status')
I18N = os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0], 'lib', 'i18n', 'lang')
VIEW_FILES = {
    'cards':   '_checks.html',
    'summary': '_view_summary.html',
    'table':   '_view_table.html',
    'heatmap': '_view_heatmap.html',
}


def _read(name: str) -> str:
    return io.open(os.path.join(ST, name), encoding='utf-8-sig').read()


def _core() -> str:
    return _read('_views.html')


def _strip_comments(js: str) -> str:
    """Code only. A guard that searches the prose too trips over the comment explaining the
    very rule it is checking — which is exactly how this one first failed."""
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _registry() -> list:
    m = re.search(r'const STATUS_VIEWS = \[(.*?)\];', _core(), re.S)
    assert m, 'the view registry is gone'
    return re.findall(r"\{\s*id:\s*'([^']+)'.*?label_key:\s*'([^']+)'.*?render:\s*'([^']+)'",
                      m.group(1), re.S)


class TestTheScanItself:

    def test_the_registry_is_found(self):
        assert len(_registry()) >= 2

    def test_every_view_file_exists(self):
        for f in VIEW_FILES.values():
            assert os.path.isfile(os.path.join(ST, f))


class TestEveryViewAgreesOnWhatACheckIs:

    def test_a_check_state_is_decided_in_one_place(self):
        body = _fn(_core(), '_stCheckFacts')
        assert 'severity' in body and "=== 'warning'" in body

    def test_no_view_reads_the_raw_result_itself(self):
        """`status === true` in a view is a second opinion about the same check."""
        for fname in VIEW_FILES.values():
            src = _read(fname)
            assert 'info?.status' not in src and 'v?.status' not in src, \
                f'{fname} reads a raw status again instead of _stCheckFacts'

    def test_no_view_re_derives_the_warning_rule(self):
        """The distinction that costs most to lose: amber is not red."""
        for fname in VIEW_FILES.values():
            src = _read(fname)
            assert "severity) === 'warning'" not in src and "severity || '') === 'warning'" not in src, \
                f'{fname} decides what a warning is on its own'

    def test_the_schema_decoration_is_rendered_once(self):
        """`__status_render__` is a module's own declaration; four readers of it is four
        chances to show a different number for the same value."""
        assert 'function _stExtraHtml' in _core()
        for fname in VIEW_FILES.values():
            assert 'MODULE_STATUS_RENDER' not in _read(fname), \
                f'{fname} interprets the render directives itself'

    def test_the_palette_is_shared(self):
        """Two colours drifting apart is how a page stops being scannable."""
        assert re.search(r'const ST_PAL = \{', _core())
        for fname in VIEW_FILES.values():
            src = _read(fname)
            assert '#fee2e2' not in src and '#dcfce7' not in src, \
                f'{fname} carries its own state colours'

    def test_a_phantom_row_is_excluded_once(self):
        """An entry without `status` is bookkeeping, not a check. Each view filtering for
        itself is how one of them starts showing a row the others do not."""
        assert "'status' in v" in _fn(_core(), '_stCheckEntries')
        for fname in VIEW_FILES.values():
            assert "'status' in v" not in _read(fname), f'{fname} filters phantom rows itself'


class TestTheControlsSitWithWhatTheyControl:
    """They started in a row of their own above the results, which read as a strip of
    leftover chrome. The obvious home was the Scheduler toolbar — visibly half empty — and
    that is the one place they must not go: it is drawn only for a user with `checks_run`,
    and filtering or switching view is reading, not running. Putting them there would take
    both controls away from exactly the people who can only look."""

    def test_there_is_one_header_and_every_view_uses_it(self):
        assert 'function _stResultsHeader' in _core()
        for fname in VIEW_FILES.values():
            assert '_stResultsHeader(' in _read(fname), \
                f'{fname} builds its own bar; the three controls would drift apart'

    def test_no_view_builds_the_totals_bar_itself(self):
        for fname in VIEW_FILES.values():
            assert '_stTotalsHtml(' not in _read(fname), \
                f'{fname} lays out the totals again instead of using the shared header'

    def test_the_controls_do_not_depend_on_the_run_permission(self):
        """The Scheduler widget is gated on `canRun`. The header must not be drawn inside
        that gate, or a read-only user loses the filter and the view switcher."""
        body = _strip_comments(_fn(_read('_checks.html'), 'renderStatus'))
        gate = body.index('if (canRun) {')
        assert 'stSearch' not in body, 'the filter is back in the section chrome'
        assert '_stResultsHeader' not in body[gate:], \
            'the results header is drawn inside the checks_run gate'

    def test_a_view_may_add_one_thing_of_its_own(self):
        """The heatmap needs a colour legend; that is a property of that view, not of the
        bar. It passes it in rather than rebuilding the bar around it."""
        assert re.search(r'function _stResultsHeader\(tt, extra', _core())
        assert '_stResultsHeader(tt, _stLegend())' in _read('_view_heatmap.html')


class TestTheSummaryEarnsItsName:
    """It very nearly did not have one. With the totals bar moved into a header every view
    shows, the summary was the card grid in a different order — two of four views differing
    by a sort. It now spends page on a module in proportion to what that module has to say."""

    def test_a_failing_module_gets_a_card(self):
        body = _fn(_read('_view_summary.html'), '_stViewSummary')
        assert 'st.err || st.warn' in body
        assert '_renderOneStatusCard(' in body

    def test_a_passing_module_collapses_to_a_line(self):
        """Twelve modules that are fine should cost twelve lines, not twelve cards — the
        failures are what belongs above the fold."""
        src = _read('_view_summary.html')
        assert 'function _stCleanRow' in src and 'function _stCleanList' in src
        body = _fn(src, '_stViewSummary')
        assert '_stCleanList(' in body

    def test_that_line_is_still_a_way_in(self):
        """Wanting to look at a module that is passing is normal and must not require
        changing view."""
        assert '_stSummaryToggle(' in _read('_view_summary.html')
        body = _fn(_read('_view_summary.html'), '_stViewSummary')
        assert '_stSummaryOpen.has(mod)' in body

    def test_what_you_opened_is_not_remembered(self):
        """A summary that slowly filled up with everything ever opened would be the grid
        again with extra steps."""
        src = _read('_view_summary.html')
        assert 'const _stSummaryOpen = new Set()' in src
        assert 'localStorage' not in src, 'the expansion is being persisted'

    def test_a_module_with_no_items_is_not_called_passing(self):
        """It ran nothing. Reporting OK for it would be the page's own small lie."""
        body = _fn(_read('_view_summary.html'), '_stCleanRow')
        assert 'st.total === 0' in body

    def test_it_no_longer_merely_reorders_the_grid(self):
        """The regression that would bring back two views differing by a sort."""
        body = _fn(_read('_view_summary.html'), '_stViewSummary')
        assert 'clean' in body, 'the summary draws every module the same way again'


class TestLookingIsNotFetching:

    def test_switching_view_redraws_the_data_it_has(self):
        """It is a way of LOOKING at the last result, not a way of getting a new one."""
        body = _fn(_core(), 'setStatusView')
        assert '_stDrawResults()' in body
        assert 'apiGet' not in body

    def test_filtering_redraws_too(self):
        for fn in ('_stFilter', '_stToggleProblems'):
            body = _fn(_core(), fn)
            assert '_stDrawResults()' in body and 'apiGet' not in body, f'{fn} re-fetches'

    def test_the_payload_is_kept_for_that(self):
        assert '_stLastData' in _core()
        assert '_stLastData = data' in _read('_checks.html')

    def test_the_draw_step_is_separate_from_the_load(self):
        checks = _read('_checks.html')
        assert 'function _stDrawResults' in checks
        assert '_stDrawResults();' in _fn(checks, 'renderStatus')


class TestTheOrderIsPartOfTheAnswer:

    def test_problems_come_first(self):
        """A page whose first screen is green while the failure sits three rows below has
        made you scroll to learn something it already knew."""
        body = _fn(_core(), '_stVisible')
        assert 'rank' in body and 's.err' in body

    def test_the_baseline_view_is_not_reordered(self):
        """The cards view is what the other three are compared against; sorting it would
        change the very thing being compared."""
        assert 'sort = true' in _core()
        assert '_stVisible(data, false)' in _read('_checks.html')

    def test_the_filter_still_applies_to_it(self):
        """Filtering is section state, not a property of a layout."""
        body = _fn(_read('_checks.html'), '_stViewCards')
        assert '_stVisible(' in body


class TestOnlyProblemsIsHonest:

    def test_it_survives_a_reload(self):
        """If that is how you work, you should not have to say so on every visit."""
        core = _core()
        assert '_ST_PROBLEMS_KEY' in core
        assert re.search(r'let _stOnlyProblems = localStorage\.getItem\(_ST_PROBLEMS_KEY\)', core)
        assert '_ST_PROBLEMS_KEY' in _fn(core, '_stToggleProblems'), 'toggling does not store it'

    def test_the_totals_beside_it_still_report_everything(self):
        """What makes remembering it safe. A remembered filter that hides most of the page
        is only acceptable while the line next to the switch keeps stating the whole set:
        the page can be filtered, but it cannot understate how much there is."""
        header = _fn(_core(), '_stResultsHeader')
        assert '_stTotalsHtml(tt)' in header and '_stProblemsToggle()' in header
        assert '_stOnlyProblems' not in _fn(_core(), '_stTotals')

    def test_the_search_term_is_not_remembered(self):
        """The difference from the switch above: the totals say nothing about a text filter,
        so a page opening with one silently applied could not admit to it."""
        assert re.search(r"let _stFilterTerm = '';", _core())
        assert not re.search(r'localStorage\.\w+Item\([^)]*[Ff]ilter[Tt]erm', _core())

    def test_it_hides_the_passing_CHECKS_too(self):
        """**The bug this class grew for.** Keeping only the modules that have a problem is
        not enough: a module with one error and eight passing checks still listed all nine,
        so on the table view — the one where it matters most — the switch looked broken."""
        assert 'function _stShownRows' in _core()
        for fname in ('_view_table.html', '_view_heatmap.html', '_checks.html'):
            assert '_stShownRows(' in _read(fname), \
                f'{fname} lists every row of a module that has a problem'

    def test_the_counts_still_include_them(self):
        """The header must keep saying "6/9 OK". Hiding the passing checks must not also
        hide that they exist — "this module has one check and it failed" is a different
        claim from the true one."""
        body = _fn(_core(), '_stModStats')
        assert '_stOnlyProblems' not in body, 'the tally is being filtered as well'
        assert '_stOnlyProblems' not in _fn(_core(), '_stTotals')

    def test_the_empty_state_says_which_emptiness_it_is(self):
        """"No checks at all" and "nothing matches your filter" are different news."""
        body = _fn(_core(), '_stEmptyState')
        assert '_stOnlyProblems' in body and '_stFilterTerm' in body
        assert 'st_no_problems' in body and 'status_empty' in body


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        keys = [label for _id, label, _fn in _registry()] + [
            'st_view', 'st_search', 'st_only_problems', 'st_checks', 'st_check']
        for lang in ('es_ES', 'en_EN'):
            src = io.open(os.path.join(I18N, f'{lang}.py'), encoding='utf-8-sig').read()
            for k in keys:
                assert f"'{k}'" in src, f'{lang} has no label for {k}'
