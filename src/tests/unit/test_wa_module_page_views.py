#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module pages get four layouts, and they belong to the CORE, not to a module.

A module contributes a top-level section by declaring ``__page__`` and answering with a
fixed shape — sections of rows, each row with a state, a message and whatever the check
measured. Because the shape is fixed, the layouts are core furniture: Microsoft 365 and
Azure get them from the same code, and a module contributing a page tomorrow gets them
without writing any front-end at all.

That is the point worth defending, and it was nearly lost. M365 shipped its own renderer —
declared in its schema, living in ``web/_ui.html`` — which had started as a copy of the
core's and then stopped tracking it: by the time anyone looked, the core had grown grouping
by measurement and the copy had not. It was not a different design, it was an older one. So
the layouts went into the core renderer and the copy was dropped, rather than a fourth
renderer being written beside it.

What follows is that rule and its consequences: no view invents how a row looks, the filter
and the view choice belong to the PAGE (wanting the table for Azure and the board for M365
at once is normal), and looking at a result never costs a Graph call — refreshing a module
page queries Microsoft, so a layout switch that re-fetched would charge the reader for a
decision about presentation.
"""

import io
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
CORE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core')
PAGE = os.path.join(CORE, '_module_page.html')
VIEWS = os.path.join(CORE, '_module_page_views.html')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _strip_comments(js: str) -> str:
    """Code only. A guard that searches the prose too trips over the comment explaining the
    very rule it is checking — which is exactly how this one first failed elsewhere."""
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _registry() -> list:
    m = re.search(r'const MP_VIEWS = \[(.*?)\];', _read(VIEWS), re.S)
    assert m, 'the view registry is gone'
    return re.findall(r"\{\s*id:\s*'([^']+)'.*?label_key:\s*'([^']+)'.*?render:\s*'([^']+)'",
                      m.group(1), re.S)


class TestTheScanItself:

    def test_the_registry_is_found(self):
        assert len(_registry()) >= 2

    def test_both_files_are_wired_into_the_shell(self):
        inc = _read(os.path.join(os.path.dirname(CORE), '_js_sections.html'))
        assert 'partials/core/_module_page.html' in inc
        assert 'partials/core/_module_page_views.html' in inc


class TestTheLayoutsBelongToTheCore:

    def test_no_shipped_module_declares_its_own_page_renderer(self):
        """A module CAN ship one — the mechanism stays — but none does today, and the one
        that did had drifted into an older copy of the core's. A new one appearing is worth
        a conversation, not a silent second implementation."""
        import json                                          # noqa: PLC0415
        wf = os.path.join(SRC, 'watchfuls')
        offenders = []
        for entry in sorted(os.listdir(wf)):
            sp = os.path.join(wf, entry, 'schema.json')
            if not os.path.isfile(sp):
                continue
            try:
                decl = (json.load(io.open(sp, encoding='utf-8-sig')) or {}).get('__page__')
            except ValueError:
                continue
            if isinstance(decl, dict) and decl.get('render'):
                offenders.append(f"{entry} -> {decl['render']}")
        assert not offenders, (
            'these ship their own page renderer instead of using the core one: '
            + ', '.join(offenders) + ' — the core one already lays out this exact shape')

    def test_the_retired_renderer_is_really_gone(self):
        """Deleted, not merely unreferenced: a dead copy left in the tree is the one the
        next person edits."""
        assert not os.path.exists(os.path.join(SRC, 'watchfuls', 'm365', 'web', '_ui.html'))


class TestAViewIsChromeOnly:

    def test_no_view_draws_a_row_itself(self):
        """`_mpRow` renders a row for all four. A view that assembled one would be free to
        disagree with the view beside it about the same check."""
        assert 'function _mpRow(' in _read(PAGE)
        views = _read(VIEWS)
        # The board and the table lay rows out differently ON PURPOSE (a triage line, a
        # table cell), but neither may re-decide what a row's state or metrics look like.
        assert '_MP_STATE_CLS[' in views, 'the shared state palette is unused'
        assert 'function _mpMetrics' not in views, 'a view re-implements the measurements'

    def test_the_measurements_are_rendered_once(self):
        assert 'function _mpMetrics' in _read(PAGE)
        assert _read(VIEWS).count('_mpMetrics(') >= 1

    def test_the_filter_is_applied_in_one_place(self):
        views = _read(VIEWS)
        assert 'function _mpShownRows' in views
        assert 'function _mpVisibleSections' in views
        # No view may filter with its own predicate.
        assert views.count("r.state !== 'ok'") <= 2, 'a view filters rows on its own'


class TestTheRingIsDeclaredNotGuessed:
    """A usage ring needs to know which two measurements are the used-vs-total pair, and
    that is module knowledge: `used` is a percentage while `used_bytes` is an absolute, and
    summing the first across sites would be meaningless. So the module names the pair and the
    core divides — the same arrangement as `group_by`, which tells the core which measurement
    is worth grouping on without telling it what any of them mean."""

    def test_the_core_only_draws_what_it_was_told(self):
        body = _fn(_read(PAGE), '_mpRowChart')
        assert 'spec.used' in body and 'spec.total' in body
        # No metric name may be baked into the core.
        for guess in ('used_bytes', 'total_bytes', 'free_bytes', 'quota'):
            assert guess not in body, f'the core knows about {guess!r}'

    def test_a_missing_total_never_becomes_a_number(self):
        """A ring computed from a missing total is a confident-looking zero — a 0.0% that
        reads as a measurement and is not one."""
        body = _fn(_read(PAGE), '_mpRowChart')
        assert 'total > 0' in body

    def test_a_missing_total_says_so_instead_of_vanishing(self):
        """Drawing nothing is its own small failure: the reader sees a ring on the row above,
        none here, and has to leave the page to find out why — which is exactly what happened
        with OneDrive, whose "whole" is a limit nobody had configured. An empty ring occupies
        the same space and makes no claim."""
        body = _fn(_read(PAGE), '_mpRowChart')
        assert '_mpRingEmpty(spec)' in body, 'a row with no total renders nothing again'
        empty = _fn(_read(PAGE), '_mpRingEmpty')
        assert 'page_chart_no_total' in empty, 'the placeholder does not say why it is empty'
        assert 'spec.total' in empty, \
            'the tooltip does not name the missing measurement, which is what points at ' \
            'the setting behind it'

    def test_the_placeholder_shows_no_percentage(self):
        """Anything numeric in it would be read as data."""
        empty = _fn(_read(PAGE), '_mpRingEmpty')
        assert '%' not in empty.split('aria-label')[-1], 'the empty ring shows a figure'

    def test_it_is_drawn_per_row_not_per_section(self):
        """Adding the sites up answers "how full is all of SharePoint", which nobody asked,
        and hides the one that matters — which site is filling up."""
        body = _fn(_read(PAGE), '_mpRowChart')
        assert 'row.metrics' in body
        assert 's.rows' not in body, 'the ring aggregates the section again'
        assert '_mpRowChart(chart, row)' in _fn(_read(PAGE), '_mpRow')

    def test_every_view_shows_it(self):
        """A figure that appears in one layout and not the next makes the layouts disagree
        about the same record."""
        views = _read(VIEWS)
        for fn in ('_mpViewSplit', '_mpViewBoard', '_mpViewTable'):
            assert '_mpRowChart(' in _fn(views, fn) or '_mpRow(' in _fn(views, fn),                 f'{fn} draws rows without the ring'

    def test_the_module_declares_its_pairs(self):
        src = io.open(os.path.join(SRC, 'watchfuls', 'm365', 'page.py'),
                      encoding='utf-8-sig').read()
        assert '_CHARTS' in src and "'used': 'used_bytes'" in src

    def test_each_declared_pair_is_what_that_check_publishes(self):
        """**The mistake this catches.** The three storage sections do not agree on a name:
        the site check reports `total_bytes`, the tenant and OneDrive ones `limit_bytes`.
        Declaring one spelling for all three drew nothing on two of them — silently, because
        a missing measurement is correctly treated as "no ring"."""
        import re as _re                                      # noqa: PLC0415
        m365 = os.path.join(SRC, 'watchfuls', 'm365')
        page = io.open(os.path.join(m365, 'page.py'), encoding='utf-8-sig').read()
        block = _re.search(r'_CHARTS = \{(.*?)\n    \}', page, _re.S)
        assert block, 'the chart declarations are gone'
        # Every check file, found rather than listed: naming two of them by hand is how this
        # went blind the moment a third appeared.
        published = ''
        for f in sorted(os.listdir(m365)):
            if f.startswith('checks_') and f.endswith('.py'):
                published += io.open(os.path.join(m365, f), encoding='utf-8-sig').read()
        assert published, 'no check files found — the scan is looking in the wrong place'
        pairs = _re.findall(r"'(\w+)':\s*\{'used': '(\w+)',\s*'total': '(\w+)'", block.group(1))
        assert pairs, 'no pair parsed — the declaration changed shape'
        for section, used, total in pairs:
            for metric in (used, total):
                assert f"'{metric}'" in published, (
                    f'{section} declares a ring over {metric!r}, which no check publishes')

    def test_it_is_only_offered_when_the_rows_carry_both(self):
        src = io.open(os.path.join(SRC, 'watchfuls', 'm365', 'page.py'),
                      encoding='utf-8-sig').read()
        assert "chart['used'], chart['total']" in src, \
            'the section declares a ring even when its rows have no such measurements'

    def test_the_label_is_centred_by_declaration(self):
        """Not by a hand-tuned offset: that is right at exactly one font size, and it stops
        being right the moment the ring is resized — which is what happened."""
        body = _fn(_read(PAGE), '_mpRowChart')
        assert 'dominant-baseline="central"' in body and 'text-anchor="middle"' in body
        assert 'y="18"' in body, 'the label is nudged off the geometric centre again'

    def test_the_ring_takes_its_colour_from_the_row(self):
        """Not from a threshold of its own. A fixed "fuller is worse" scale is right for a
        disk and wrong for anything else: 91% of licences idle is a warning the check already
        made, and a red ring beside an amber row is two signals disagreeing about one
        record."""
        body = _fn(_read(PAGE), '_mpRowChart')
        assert 'row.state' in body, 'the ring judges the number itself again'
        assert 'pct >= 90' not in body, 'a usage threshold is back in the core'

    def test_it_needs_no_charting_library(self):
        """One ring does not justify a dependency, and the page's CSP forbids fetching one."""
        body = _fn(_read(PAGE), '_mpRowChart')
        assert '<svg' in body and 'stroke-dasharray' in body


class TestTheStateBelongsToThePage:

    def test_the_view_choice_is_per_page(self):
        """Wanting the table for Azure and the board for M365 at the same time is normal;
        one shared setting would make each visit undo the other."""
        body = _fn(_read(VIEWS), '_mpViewId')
        assert "'ss_page_view_' + pageId" in body

    def test_the_filter_is_per_page_too(self):
        for fn in ('_mpFilterTerm', '_mpOnlyProblems'):
            assert 'pageId' in _fn(_read(VIEWS), fn)

    def test_switching_view_does_not_refetch(self):
        """Refreshing a module page queries Microsoft. A layout switch that re-fetched
        would charge the reader for a decision about presentation."""
        body = _fn(_read(VIEWS), 'setModulePageView')
        assert '_mpRender(' in body
        assert 'apiGet' not in body and 'apiPost' not in body


class TestTheBoardIsASummaryNotAFilteredList:
    """It shows every section as a figure and only the failing rows underneath, which reads
    like a filter that is stuck on. It is not: the tiles ARE the whole set, the list below is
    headed "needs attention", and a tile is the way into its section.

    The switch has to bite on the tiles too, though. It did not, so in the one view where
    "only problems" has the least left to hide it also appeared to do nothing at all."""

    def test_the_tiles_are_filtered_like_everything_else(self):
        body = _fn(_read(VIEWS), '_mpViewBoard')
        assert 'shown.map(' in body, 'the tiles are drawn from the unfiltered list again'
        assert re.search(r'sections\.map\(', body) is None

    def test_the_attention_list_is_only_the_failures(self):
        """That part IS deliberate — it is what the heading says."""
        body = _fn(_read(VIEWS), '_mpViewBoard')
        assert "r.state !== 'ok'" in body
        assert 'page_needs_attention' in body

    def test_a_tile_leads_somewhere(self):
        """A number you cannot follow is a dead end; clicking one opens that section where
        its rows live."""
        assert 'function _mpOpenSection' in _read(VIEWS)
        assert '_mpOpenSection(' in _fn(_read(VIEWS), '_mpTile')


class TestATileIsBoundedAndReadsAsOne:
    """A grid of figures with no edges is a grid of ambiguous figures.

    The tiles dropped .ss-card's border and pushed the state badge to the far right with
    ms-auto — which is the maximum distance from the number it qualifies and the minimum
    from the NEXT tile's label. With no boundary between them, the badge read as belonging
    to the neighbour, and the reader could not tell which item each icon was about.
    """

    def test_the_tile_keeps_its_boundary(self):
        body = _strip_comments(_fn(_read(VIEWS), '_mpTile'))
        assert 'ss-card' in body, 'the tile is a bounded surface, not a floating figure'
        assert 'border-0' not in body, (
            'border-0 removes the only thing separating one tile from the next')

    def test_the_state_badge_is_not_pushed_away_from_its_number(self):
        body = _strip_comments(_fn(_read(VIEWS), '_mpTile'))
        assert 'ms-auto' not in body, (
            'ms-auto puts the badge as far from its own figure as the tile allows')

    def test_the_badge_and_the_label_share_an_edge(self):
        """Label, state and number in one column: the association is forced by position,
        not left to the reader's guess about which gap is the boundary."""
        body = _strip_comments(_fn(_read(VIEWS), '_mpTile'))
        badge = body.index('badge text-bg-')
        figure = body.index('counts.ok')
        assert badge < figure, 'the badge leads the figure, aligned with the label above it'


class TestTheTwoPanesLineUp:
    """The section list started straight in while the detail beside it had a title, so the
    first entry sat level with that title and the two halves read as two unrelated things
    that happened to be adjacent.

    Both headers now come from ONE class with a fixed height, which is the only way this
    stays true: the two sides hold different content — a small label on the left, a title and
    a badge on the right — so left to themselves they are as tall as whatever they contain,
    and matching padding would only align them by luck."""

    def test_both_panes_have_a_header(self):
        body = _fn(_read(VIEWS), '_mpViewSplit')
        assert body.count('ss-pane-head') == 2, 'one of the two panes starts without a header'

    def test_the_list_header_is_labelled(self):
        assert 'page_sections' in _fn(_read(VIEWS), '_mpViewSplit')

    def test_the_two_headers_are_typographic_peers(self):
        """Each names its pane, so neither is a caption for the other. Sizing the left one
        down made the pair read as a label over a heading instead of as two columns of one
        thing."""
        body = _fn(_read(VIEWS), '_mpViewSplit')
        m = re.search(r'<div class="ss-pane-head([^"]*)">\$\{esc\(t\(.page_sections', body)
        assert m, 'the sections header changed shape'
        assert 'ss-fs-2' not in m.group(1) and 'text-muted' not in m.group(1),             'the sections header is smaller than the title it sits beside again'

    def test_the_class_fixes_the_height(self):
        css = io.open(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'),
                      encoding='utf-8-sig').read()
        m = re.search(r'\.ss-pane-head\s*\{([^}]*)\}', css)
        assert m, 'the shared pane header is gone'
        assert 'min-height' in m.group(1), \
            'the two panes are back to being as tall as their content'


class TestOnlyProblemsIsHonest:

    def test_it_hides_the_passing_rows(self):
        assert "r.state !== 'ok'" in _fn(_read(VIEWS), '_mpShownRows')

    def test_the_counts_beside_it_still_report_everything(self):
        """The badge still says 4/8 while the list shows the four that are not OK: hiding
        the passing rows must not also hide that they exist."""
        body = _fn(_read(VIEWS), '_mpResultsHeader')
        assert 'counts.ok' in body and 'counts.total' in body
        assert '_mpShownRows' not in body, 'the totals are being filtered as well'

    def test_a_section_emptied_by_the_filter_is_dropped(self):
        """An empty card headed "Licenses" tells you nothing except that you filtered."""
        assert 'rows.length' in _fn(_read(VIEWS), '_mpVisibleSections')


class TestARowCanSayWhatItIsMadeOf:
    """A check reports one number for a whole — SharePoint's total across every site — and the
    question that always follows is which parts account for it. Answering it with one check
    per part does not scale (a tenant has hundreds of sites) and buries the total among them,
    so a row may carry a `breakdown` the page unfolds on demand.

    It is CORE furniture for the same reason the layouts are: the shape is fixed, so a module
    contributing one tomorrow — a datastore's tables, a cluster's nodes — needs no front-end.
    """

    def test_the_core_renders_it(self):
        src = _read(PAGE)
        assert 'function _mpBreakdown' in src
        assert '_mpBreakdown(row)' in _fn(src, '_mpRow'), 'a row no longer offers it'

    def test_it_stays_folded_until_asked_for(self):
        """The list is long by nature — it is the part, not the summary — so opening it is a
        decision, not the default."""
        body = _fn(_read(PAGE), '_mpBreakdown')
        assert 'data-bs-toggle="collapse"' in body

    def test_the_core_reads_only_the_percentage(self):
        """`text` arrives formatted by the module: bytes versus rows versus seconds is exactly
        the knowledge the core does not have, the same reason the ring is declared and never
        guessed."""
        body = _fn(_read(PAGE), '_mpBreakdownRow')
        assert 'parseFloat(it.pct)' in body
        assert 'esc(it.text' in body, 'the core started formatting the value itself'

    def test_a_truncated_list_says_so(self):
        """A list that silently stopped at the top few would read as "these are all of them",
        which is the one thing an inventory must not imply.

        It lives in the footer with the pager: `more` is what the MODULE never sent, so it
        stays text — the core has nowhere to fetch it from."""
        body = _fn(_read(PAGE), '_mpBdFoot')
        assert 'st.more' in body and 'page_breakdown_more' in body

    def test_the_rest_of_the_rows_are_a_repaint_and_not_a_request(self):
        """The two bounds are different questions: the module decides what is worth STORING
        every cycle, the core what is worth DRAWING at once. The rows past the first page are
        already in the payload, so growing the list must not go anywhere to get them."""
        body = _fn(_read(PAGE), '_mpBdMore')
        assert 'st.items.slice(0, st.shown)' in body
        assert 'apiGet' not in body and 'apiPost' not in body and 'fetch(' not in body

    def test_growing_the_list_leaves_the_row_alone(self):
        """Re-rendering the page would collapse the breakdown the click just expanded, so the
        pager repaints its own list and footer and nothing else."""
        body = _fn(_read(PAGE), '_mpBdMore')
        assert "getElementById(id + '-list')" in body
        assert '_mpRender' not in body

    def test_an_expanded_list_survives_a_refresh(self):
        """A live refresh repaints the whole page. A list that folded itself back up on every
        auto-refresh would be worse than no paging at all."""
        body = _fn(_read(PAGE), '_mpBreakdown')
        assert '_mpBd[id] ? _mpBd[id].shown : page' in body

    def test_a_module_can_state_its_own_page_size(self):
        """A list of 6 partitions and one of 500 tables do not read the same, so `page` is
        declared like `chart` is — and 25 is what declaring nothing means."""
        body = _fn(_read(PAGE), '_mpBreakdown')
        assert "parseInt(b.page, 10) || _MP_BD_PAGE" in body

    def test_the_bar_cannot_leave_its_track(self):
        """A part bigger than the whole is possible — a site over its quota, a table over its
        tablespace — and an unclamped width would draw outside the row."""
        body = _fn(_read(PAGE), '_mpBreakdownRow')
        assert 'Math.max(0, Math.min(100' in body


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        keys = [label for _id, label, _fn2 in _registry()] + [
            'page_view', 'page_search', 'page_checks', 'page_section', 'page_needs_attention',
            'page_breakdown_more']
        for lang in ('es_ES', 'en_EN'):
            src = io.open(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'),
                          encoding='utf-8-sig').read()
            for k in keys:
                assert f"'{k}'" in src, f'{lang} has no label for {k}'
