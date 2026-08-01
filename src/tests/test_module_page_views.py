#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A module section may have more than one VIEW of itself.

The row/section layout answers "is everything all right"; a table of who holds what
answers "where is it all going". Those are two questions about one subsystem, and the
mistake worth guarding against is answering them with two SECTIONS: two sidebar entries,
two permissions to keep in step, two panes, two routes — for a thing the reader thinks of
as one place.

So a section declares its views (`__page__.views`) and they share everything but a
sub-path: `/module/m365` and `/module/m365/storage` are the same pane, the same permission and the same
descriptor. The sidebar entry becomes a parent with a flyout, which is the pattern
Infrastructure and Access already use — the third implementation of a menu is where they
start disagreeing.

Everything here is generic: the core reads `slug/icon/label/kind/action` and never learns
what a view of a module MEANS. The labels come from the module's own lang file, the same
rule the section title follows.
"""

import io
import json
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core')
SIDEBAR = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', '_sidebar.html')
SB_INIT = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'init', '_sidebar.html')
TABLE = os.path.join(CORE, '_module_table.html')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _code(src: str) -> str:
    """Code only — jinja, block and line comments stripped."""
    src = re.sub(r'\{#.*?#\}', '', src, flags=re.S)
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return re.sub(r'^\s*//.*$', '', src, flags=re.M)


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


def _spec(**over):
    d = {'id': 'x', 'icon': 'bi-x', 'order': 1, 'views': [
        {'slug': 'a', 'icon': 'bi-a', 'label': 'view_a'},
        {'slug': 'b', 'icon': 'bi-b', 'label': 'view_b', 'kind': 'table', 'action': 'act'},
    ]}
    d.update(over)
    return d


class TestTheCatalogReadsViews:

    def test_a_view_is_normalised_to_the_generic_keys(self):
        from lib.modules.discovery.pages import _page_spec
        views = _page_spec('m', _spec())['views']
        assert [v['slug'] for v in views] == ['a', 'b']
        assert views[1]['kind'] == 'table' and views[1]['action'] == 'act'
        assert views[0]['kind'] == 'rows', 'the default layout is the one that existed'

    def test_one_view_is_no_menu(self):
        """A parent with a single child is a menu that wastes a click: a section with one
        view is the plain item it always was."""
        assert _one(_spec(views=[{'slug': 'only'}])) == []

    def test_a_malformed_view_costs_its_own_entry_and_nothing_else(self):
        """One bad declaration must never take the section down with it."""
        views = _one(_spec(views=[{'slug': 'ok'}, {'slug': 'NOT A SLUG'}, 'junk',
                                  {'slug': 'ok'}, {'slug': 'two'}]))
        assert [v['slug'] for v in views] == ['ok', 'two']

    def test_a_section_without_views_is_untouched(self):
        from lib.modules.discovery.pages import _page_spec
        assert _page_spec('m', {'id': 'm'})['views'] == []

    def test_the_shipped_module_declares_its_two_views(self):
        from lib.modules.discovery.pages import module_pages_catalog
        page = next(p for p in module_pages_catalog(os.path.join(SRC, 'watchfuls'))
                    if p['id'] == 'm365')
        assert [v['slug'] for v in page['views']] == ['status', 'storage']

    def test_a_view_names_itself_in_the_modules_own_lang_file(self):
        """The same rule the section title follows: no core string may name a module's
        view. A module that ships no translation still gets a usable menu entry."""
        from lib.modules.discovery.pages import module_pages_catalog
        page = next(p for p in module_pages_catalog(os.path.join(SRC, 'watchfuls'))
                    if p['id'] == 'm365')
        labels = {v['slug']: v['label_i18n'] for v in page['views']}
        assert labels['storage']['es_ES'] == 'Almacenamiento'
        assert labels['storage']['en_EN'] == 'Storage'

    def test_no_core_file_names_a_module_view(self):
        """The strings above live in the module. If one of them appears in core CODE the
        ownership has quietly flipped.

        Comments are stripped first: they are where a core file is supposed to name a real
        example, and a guard that reads the prose trips over the very rule it checks."""
        for path in (SIDEBAR, SB_INIT, TABLE, os.path.join(CORE, '_module_page.html')):
            body = _code(_read(path))
            for word in ('storage_report', 'm365', 'Almacenamiento'):
                assert word not in body, f'{os.path.basename(path)} names {word!r}'


def _one(d):
    from lib.modules.discovery.pages import _page_spec
    return _page_spec('m', d)['views']


class TestAViewIsASubPathNotASection:

    def test_the_section_url_gains_one_route_not_one_per_view(self):
        """Two views must not become two sections: one extra rule serves them all, so a
        module adding a third view adds no route, no pane and no permission."""
        body = _read(os.path.join(SRC, 'lib', 'web_admin', 'routes', 'pages.py'))
        assert "_page['url'] + '/<view>'" in body
        assert body.count('add_url_rule') == 2, 'a per-view route crept in'

    def test_the_view_route_is_reachable(self, client):
        from tests.conftest import _login                       # noqa: PLC0415
        _login(client)
        assert client.get('/module/m365/storage').status_code == 200
        assert client.get('/module/m365').status_code == 200

    def test_an_unknown_view_still_lands_on_the_section(self):
        """A stale bookmark should land somewhere rather than nowhere: the slug is resolved
        on the client, and an unknown one falls back to the section's first view."""
        body = _fn(_read(SB_INIT), '_sbPageView')
        assert 'views[0].slug' in body

    def test_the_pane_is_shared(self):
        """One pane for the section: a view is a layout of it, not a second page."""
        body = _fn(_read(SB_INIT), '_sbPaneIdFromPath')
        assert '_sbSectionOf(path)' in body

    def test_a_two_segment_path_never_borrows_a_pane(self):
        """`/module/m365/storage` resolves only because `storage` is one of m365's declared views.
        Any other two-segment path must stay unknown rather than open a section at random."""
        body = _fn(_read(SB_INIT), '_sbSectionOf')
        assert "views || []).some(v => v.slug === slug)" in body

    def test_no_url_is_composed_from_a_page_id(self):
        """Reported after the move to `/module/`: the flyout still pushed `/m365/storage`.
        Where a section lives is the SERVER's decision, and a URL built in the client from the
        id goes stale the moment that changes — silently, because pushState never 404s."""
        body = _read(SB_INIT)
        assert "'/' + pageId" not in body, 'a section URL is being composed from its id'
        assert '_sbPageUrl(pageId)' in _fn(body, '_navPageView')

    def test_the_address_bar_names_the_view(self):
        """A section with views is always showing one of them; a URL that omits it reopens
        somebody else's view when the link is shared."""
        assert "base + '/' + slug" in _fn(_read(SB_INIT), '_sbPaneUrl')


class TestTheMenuIsTheOneThatAlreadyExists:

    def test_views_reuse_the_flyout_pattern(self):
        """Infrastructure and Access already have a hover flyout. A third implementation of
        one menu is where the three start disagreeing."""
        body = _read(SIDEBAR)
        assert 'ss-sb-flywrap' in body and '{% for v in p.views %}' in body

    def test_a_view_reuses_the_single_highlight_machinery(self):
        """`data-subtab` on purpose: exactly one sub-item is ever lit across the sidebar,
        and a second mechanism for that job is how two of them end up both lit."""
        assert 'data-subtab="#view-' in _read(SIDEBAR)

    def test_the_choice_is_remembered_per_section(self):
        assert "ss_active_view_" in _fn(_read(SB_INIT), '_navPageView')

    def test_the_url_wins_over_the_remembered_view(self):
        """A shared link must land where it says, not where the reader was last."""
        body = _fn(_read(SB_INIT), '_sbPageView')
        assert body.index('fromUrl') < body.index('saved')


class TestTheTableViewIsGeneric:

    def test_the_core_reads_only_the_declared_kinds(self):
        """`text`, `num`, `pct` — the module formats, because bytes-versus-rows-versus-
        seconds is knowledge the core does not have."""
        body = _fn(_read(TABLE), '_mptCell')
        assert "col.kind === 'pct'" in body and "col.kind === 'num'" in body

    def test_a_value_may_sort_by_one_number_and_read_as_another(self):
        """"3.0 TB" has to sort as its bytes, and the core must not learn what a byte is:
        the module sends `{v, s}` and the core sorts by `v` and prints `s`."""
        assert "raw.v" in _fn(_read(TABLE), '_mptVal')
        assert "raw.s" in _fn(_read(TABLE), '_mptText')

    def test_the_table_is_built_once(self):
        """The factory publishes its handlers under global names; a second table for the
        same view would leave two of them answering to one set."""
        body = _fn(_read(TABLE), '_mptEnsure')
        assert 'if (st.made) return key' in body

    def test_the_columns_come_from_the_module(self):
        body = _fn(_read(TABLE), '_mptEnsure')
        assert 'st.columns.map' in body
        for guess in ('used', 'quota', 'tenant', 'bytes'):
            assert f"'{guess}'" not in body, f'the core knows about a {guess!r} column'

    def test_one_failing_item_does_not_cost_the_others_their_rows(self):
        """A tenant whose credentials expired must not blank the table for the rest."""
        body = _fn(_read(TABLE), '_mptLoad')
        assert 'failed.push' in body and 'continue' in body

    def test_a_live_view_says_when_it_was_read(self):
        """It has no history and no cache, so the only honest thing it can carry is the
        moment it asked."""
        assert 'st.at' in _fn(_read(TABLE), '_mptEnsure')

    def test_it_is_wired_into_the_shell(self):
        inc = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                 '_js_sections.html'))
        assert 'partials/core/_module_table.html' in inc


class TestTheInventoryHasMoreThanOneLayout:
    """A table answers "which one", sorted and filtered; it is a poor answer to "how is it
    distributed", because comparing forty numbers in a column is work the reader should not
    be doing."""

    def test_the_layouts_reuse_the_sections_own_vocabulary(self):
        """`createViewState` + `_viewSwitcher` are what every other section switches views
        with. A fourth way to draw a two-button group is three too many."""
        body = _read(TABLE)
        assert 'createViewState(' in body and '.switcher(' in body

    def test_the_extra_layouts_draw_every_filtered_row(self):
        """They are read as a SHAPE, and a shape cut at row 25 is a different shape."""
        assert "mode: 'summary'" in _read(TABLE)

    def test_they_are_offered_only_when_the_module_says_what_to_draw(self):
        """Which of six columns is the magnitude is module knowledge; a bar of the wrong
        column is worse than no bar."""
        body = _fn(_read(TABLE), '_mptEnsure')
        assert 'st.layout ? _mptViews(key).mode() : ' in body
        assert 'st.layout ? _mptViews(key).switcher' in body

    def test_a_bar_is_a_share_of_the_largest_row(self):
        """Of the total, forty rows would each be a sliver and the comparison the layout
        exists for would be lost."""
        assert 'v / max * 100' in _fn(_read(TABLE), '_mptBarRow')

    def test_a_group_reports_a_share_and_never_an_invented_total(self):
        """The core cannot add "3.0 TB" to "512 MB" — it does not know what either is — and
        reconstructing a unit from a sample row would be inventing a measurement."""
        body = _fn(_read(TABLE), '_mptShare')
        assert "+ '%'" in body

    def test_groups_are_ordered_by_weight(self):
        """A group nobody fills is not where the reader should start."""
        assert 'total(b[1]) - total(a[1])' in _fn(_read(TABLE), '_mptBody')


class TestTheFiltersAreDeclaredToo:

    def test_a_column_asks_for_its_own_dropdown(self):
        body = _fn(_read(TABLE), '_mptEnsure')
        assert 'st.columns.filter(c => c.filter)' in body

    def test_its_choices_are_the_values_actually_present(self):
        """A filter offering choices that match nothing is a filter that wastes a click —
        and it is also how the core would end up with a vocabulary of its own."""
        assert '_mptChoices(st, c.id)' in _fn(_read(TABLE), '_mptEnsure')
        body = _fn(_read(TABLE), '_mptChoices')
        assert 'seen.includes(v)' in body

    def test_the_free_text_still_reaches_every_column(self):
        """An inventory is searched by whatever the reader remembers of the row, not by a
        field they have to pick first."""
        assert 'st.columns.some(' in _fn(_read(TABLE), '_mptEnsure')

    def test_the_table_waits_for_its_columns_before_being_built(self):
        """Reported from a screenshot: only the search box appeared. The filter bar is built
        ONCE, from the fields it sees at that moment, and the table was being created before
        the module's columns had arrived — so its dropdowns were decided while there were no
        columns to declare them."""
        body = _fn(_read(TABLE), '_mptLoad')
        assert body.index('if (!st.made)') < body.index('_mptEnsure(pageId')

    def test_a_changed_field_set_rebuilds_the_bar_and_nothing_else(self):
        """Dropping the node is how the factory is told to build it again — and only when the
        fields really changed, so typing in the search box is never interrupted for nothing."""
        body = _fn(_read(TABLE), '_mptLoad')
        assert "sig !== st.filterSig" in body and ".ss-filterbar')?.remove()" in body

    def test_the_shipped_module_declares_the_two_axes(self):
        from watchfuls.m365 import Watchful
        filt = {c[0] for c in Watchful._STORAGE_COLS if c[3]}
        assert filt == {'tenant', 'kind'}


class TestTheRendererPicksTheView:

    def test_the_view_is_resolved_once(self):
        """From the URL, in one place — every layer below it is told, never left to guess."""
        body = _fn(_read(os.path.join(CORE, '_module_page.html')), 'renderModulePage')
        assert '_mpActiveView(spec)' in body
        assert "view.kind === 'table'" in body

    def test_a_section_with_no_views_behaves_exactly_as_before(self):
        body = _fn(_read(os.path.join(CORE, '_module_page.html')), '_mpActiveView')
        assert 'if (!views.length) return null' in body


class TestTheStorageViewOfM365:

    def test_the_action_is_declared(self):
        from watchfuls.m365 import Watchful
        assert 'storage_report' in Watchful.WATCHFUL_ACTIONS
        assert 'storage_report' in Watchful.READ_ONLY_ACTIONS, \
            'it only reads Microsoft, so modules_view is enough'

    def test_the_declared_action_exists(self):
        """A view naming an action nobody implements is a menu entry that opens an error."""
        from lib.modules.discovery.pages import module_pages_catalog
        from watchfuls.m365 import Watchful
        page = next(p for p in module_pages_catalog(os.path.join(SRC, 'watchfuls'))
                    if p['id'] == 'm365')
        for view in page['views']:
            if view['action']:
                assert callable(getattr(Watchful, view['action'], None))

    def test_the_schema_is_still_valid_json(self):
        sp = os.path.join(SRC, 'watchfuls', 'm365', 'schema.json')
        assert isinstance(json.load(io.open(sp, encoding='utf-8-sig'))['__page__']['views'],
                          list)


class TestAViewIsAPlaceYouCanLandOn:
    """The landing-page menu asks "where do you want to be sent after login", and a section
    with two views is two answers to that.

    It listed one, named it "m365", and — the part nobody would have noticed — sent you to the
    admin panel anyway if you picked it: the redirect resolved landing ids against the CORE
    page tuple, which module sections were never in. The setting saved, the login ignored it,
    and nothing on screen said so."""

    def test_a_section_with_views_is_offered_once_per_view(self):
        from lib.web_admin.constants import landing_pages
        ids = [p['id'] for p in landing_pages()]
        assert 'm365/status' in ids and 'm365/storage' in ids
        assert 'm365' not in ids, \
            'the bare section is "whichever view is first", which is not a place you can name'

    def test_a_section_with_one_view_stays_one_option(self):
        from lib.web_admin.constants import landing_pages
        assert 'azure' in [p['id'] for p in landing_pages()]

    def test_each_option_carries_the_modules_own_name(self):
        """"m365" in a menu of proper names is the registry leaking through the screen. The
        section names itself in the MODULE's lang file — the core owns no string naming a
        module — so the label is composed, not looked up in the core catalog."""
        from lib.web_admin.constants import landing_options
        by_id = {p['id']: p for p in landing_options('es_ES')}
        assert by_id['m365/storage']['label'].startswith('Microsoft 365')
        assert by_id['m365/storage']['label'] != 'm365/storage'
        assert by_id['azure']['label'] == 'Azure'

    def test_every_option_points_at_a_url_that_exists(self):
        from lib.web_admin.constants import landing_pages
        for p in landing_pages():
            assert p['url'].startswith('/'), p
        by_id = {p['id']: p for p in landing_pages()}
        assert by_id['m365/storage']['url'] == '/module/m365/storage'

    def test_a_landing_saved_before_views_existed_still_resolves(self):
        """Validation is not the same question as the menu: "m365" is a working URL and it is
        what every landing chosen before that section grew a second view says. Rejecting it on
        the next save of an unrelated field would be the list calling a live setting invalid."""
        from lib.web_admin.constants import home_page_ids
        ids = home_page_ids()
        assert 'm365' in ids and 'm365/storage' in ids

    def test_the_login_redirect_resolves_module_destinations(self):
        """The bug this class exists for: `_landing_url` read the core tuple, so every module
        destination it was offered fell through to the admin panel."""
        src = _read(os.path.join(SRC, 'lib', 'web_admin', 'mixins', 'auth.py'))
        i = src.index('def _landing_url')
        body = src[i:src.index('\n    def ', i)]
        assert 'landing_pages()' in body and 'home_pages()' in body
        assert 'HOME_PAGES' not in body, 'the core half only — module landings resolve to /admin'
