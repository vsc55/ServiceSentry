#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration is an index down the side, and only that.

Seven sub-tabs held twenty-seven cards, and they answered exactly one question well: "show me
the settings about X". Finding a setting cost seven tabs, and they said nothing about the six
you were not looking at — least of all which ones this install had actually changed, which is
the first question of any diagnosis, the one asked before a log is opened.

The index replaced them outright. Not as a view among others: a second navigator over the same
cards would be one more thing to keep in step with this one, for a question this one already
answers. So the guards here defend two things — that there is exactly ONE navigator, and that
it is a PASS over the DOM `renderConfig()` produced, never a second renderer. Two renderers of
the same two hundred fields would drift, and the drift would only ever be noticed when
something was already wrong.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'cfg')
VIEWS = os.path.join(CFG, '_views.html')
RENDER = os.path.join(CFG, '_render.html')
PANE = os.path.join(CFG, '_pane.html')
CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')


def _read(path: str) -> str:
    return io.open(path, encoding='utf-8-sig').read()


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


class TestThereIsOneNavigator:
    """The index is not a view; it IS the section.

    Both were shipped for a while — the index and the old sub-tabs behind a switcher — and the
    second one earned nothing: the same cards, reachable a second way, with its own state to
    keep in step and its own set of bugs (a card whose sub-panes the index had to hide, a panel
    that loaded from a click on a tab that the index never clicked). Deleting it deleted them.
    """

    def test_the_view_registry_and_its_switcher_are_gone(self):
        body = _read(VIEWS)
        for forbidden in ('CFG_VIEWS', 'createViewState(', '.switcher(', 'setConfigView'):
            assert forbidden not in body, f'a second navigator survives ({forbidden})'
        assert 'cfgViewSwitch' not in _read(PANE), 'the toolbar still offers a switcher'

    def test_the_renderer_builds_no_tab_strip(self):
        """The body is the cards, in the layout's order — no nav, no panes. A pane is a place
        for the index to fail to look inside, which is exactly how it failed before."""
        body = _fn(_read(RENDER), 'renderConfig')
        for forbidden in ('nav-tabs', 'nav-pills', 'tab-pane', 'data-bs-toggle="tab"'):
            assert forbidden not in body, f'the tab strip is being rebuilt ({forbidden})'

    def test_the_body_is_the_cards_in_the_layouts_order(self):
        body = _fn(_read(RENDER), 'renderConfig')
        assert 'for (const card of _lay.cards) _body += _cardHtml[card.id]' in body

    def test_it_is_wired_into_the_shell(self):
        inc = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                 '_js_sections.html'))
        assert 'partials/cfg/_views.html' in inc
        assert inc.index('partials/cfg/_render.html') < inc.index('partials/cfg/_views.html'), \
            'the index must load after the renderer it post-processes'


class TestEverySectionIsACard:
    """Notifications was one card with four sub-tabs inside it, and that nesting caused three
    separate bugs in a row: the layout id pointed at the routing MATRIX (one panel of four), so
    following it showed a table and called it the whole of Notifications; revealing the chosen
    node re-hid everything it contained; and Templates loaded from a click on a tab the index
    never clicked, so it sat on "Loading…" for ever.

    They are eight sections. A section that can only be reached by two clicks and a nav the
    index has to hide is a section pretending to be a card."""

    def test_the_notifications_tab_is_eight_cards(self):
        import sys
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        from lib.config.layout import CARDS
        ids = [c['id'] for c in CARDS if c['tab'] == 'notifs']
        assert ids == ['notif_settings', 'notifications', 'events', 'telegram',
                       'email', 'msteams', 'webhook', 'notif_templates'], ids

    def test_each_one_renders_under_its_own_layout_id(self):
        """`#cfgcol_<id>` is the whole contract between the layout and the DOM: the index finds
        a section by its layout id or it does not find it at all."""
        body = _read(RENDER)
        for card in ('notif_settings', 'notifications', 'events', 'telegram',
                     'email', 'msteams', 'webhook', 'notif_templates'):
            assert f"_cardHtml['{card}']" in body, f'{card} is never built'
        # …and the four bespoke ones open a card with that exact id.
        notify = os.path.join(CFG, 'notify')
        emitted = ''.join(_read(os.path.join(notify, f)) for f in os.listdir(notify)
                          if f.endswith('.html'))
        for card in ('notif_settings', 'notifications', 'email', 'msteams', 'webhook'):
            assert f"'cfgcol_{card}'" in emitted, f'cfgcol_{card} is not emitted'

    def test_nothing_hides_behind_a_nav_of_its_own(self):
        """The nav that used to switch between the four panels is what the index kept having to
        reach through. There is nothing left to reach through."""
        for name in os.listdir(os.path.join(CFG, 'notify')):
            if not name.endswith('.html'):
                continue
            body = _read(os.path.join(CFG, 'notify', name))
            assert 'nav-pills' not in body and 'data-bs-toggle="pill"' not in body, name


class TestTheIndex:
    """An index of every section, beside the one being edited."""

    def test_it_is_built_from_the_layout(self):
        """`lib.config.layout` is the single source of truth for placement. An index with its
        own list of sections is a second map, and it goes stale the first time a card moves."""
        body = _fn(_read(VIEWS), '_cfgViewRail')
        assert 'CONFIG_LAYOUT' in body
        for guess in ("'general'", "'notifs'", "'auth'"):
            assert guess not in body, f'a tab id is hardcoded ({guess})'

    def test_cards_are_shown_and_hidden_never_rebuilt(self):
        """Switching section is a toggle: every field keeps its handlers, its tooltips and
        whatever the admin had already typed into it. It also keeps every card in the DOM, so
        the search box still has all of them to search."""
        body = _fn(_read(VIEWS), '_cfgViewRail')
        assert "style.display = 'none'" in body
        for forbidden in ('_fieldRow(', 'renderField('):
            assert forbidden not in body

    def test_a_section_is_found_by_its_layout_id(self):
        body = _fn(_read(VIEWS), '_cfgCardNode')
        assert "'#cfgcol_' + CSS.escape(card.id)" in body
        assert "closest('.cfg-card')" in body, 'a section that is a block of cards is lost'

    def test_it_counts_what_departs_from_stock(self):
        """The number is why the index earns its width: it says WHERE this install is not the
        shipped configuration, before anything is opened. Env-locked counts — the deployment
        decided it, so it is not stock either."""
        body = _fn(_read(VIEWS), '_cfgCardChangedCount')
        assert '_cfgIsDefault(' in body and 'data-env-locked' in body

    def test_a_section_never_shows_its_id_as_a_name(self):
        """"notifications" on screen is the layout leaking through it. Title, then the
        section's label, then the tab's — the id is the last resort, not the second."""
        body = _fn(_read(VIEWS), '_cfgPathIndex')
        assert 'tabLabel[card.tab] || card.id' in body

    def test_the_chosen_section_is_remembered(self):
        """Configuration is edited in visits: you come back to the section you were in."""
        assert 'ss_cfg_rail_card' in _read(VIEWS)

    def test_a_card_that_fetches_declares_its_own_loader(self):
        """Notification templates renders as "Loading…" and fills itself from the API. It used
        to start that fetch from the click on its sub-tab, and the day the sub-tab stopped
        existing it loaded for ever with nothing on screen to say why.

        A card that needs data says so in its own markup; the index calls it. The next card
        built that way needs no change here — which is the point."""
        assert "data-cfg-load=\"_notifTplLoad\"" in _read(RENDER)
        rail = _fn(_read(VIEWS), '_cfgViewRail')
        assert '_cfgCardLoad(el)' in rail
        load = _fn(_read(VIEWS), '_cfgCardLoad')
        assert "getAttribute('data-cfg-load')" in load
        assert 'dataset.cfgLoaded' in load, 'it would re-fetch on every pass'


class TestItSitsBesideTheSection:

    def test_the_index_is_not_inside_the_body_it_indexes(self):
        """Reported three times as "the rail does not reach the bottom". It could not: it was
        inside the body, under the toolbar, so it began where the body began and ended where it
        ended. It runs the full height of the pane now — and the toolbar sits over the DETAIL,
        because reload, save and search are about what is being edited, not about the index of
        what could be."""
        body = _fn(_read(VIEWS), '_cfgViewRail')
        assert "closest('.tab-pane')" in body
        assert "'cfg-shell'" in body
        css = _read(CSS)
        i = css.index('.cfg-shell {')
        assert 'min-height: 0' in css[i:css.index('}', i)], \
            'without min-height:0 a flex child refuses to shrink and the column overflows'

    def test_the_detail_reuses_what_was_rendered(self):
        """The toolbar and the body are MOVED beside the index, not copied — a copy would be a
        second set of the same inputs and a second Save button, and only one of each would be
        the one that works."""
        body = _fn(_read(VIEWS), '_cfgViewRail')
        assert 'main.appendChild(c)' in body
        for forbidden in ('innerHTML = c.innerHTML', 'cloneNode'):
            assert forbidden not in body, f'the detail is copied ({forbidden})'

    def test_the_shell_is_built_once(self):
        """`renderConfig` runs again on every reload and on every save. Building the column
        each time would leave a stack of them holding the same toolbar."""
        body = _fn(_read(VIEWS), '_cfgViewRail')
        assert "pane.querySelector(':scope > .cfg-shell')" in body
        assert 'if (!shell) {' in body

    def test_it_reaches_the_frame_on_every_side(self):
        """Reported twice from screenshots with the gaps painted red: page background down the
        index's left, under its foot, and above its head. The content container's gutters, its
        `pb-3` and its top padding were showing through — the index is a piece of the frame,
        not content sitting inside it.

        The SHELL is what bleeds, not the toolbar inside it: `.ss-bleed-top` cancels the same
        paddings, and two cancellations put the bar .75rem above the header and a gutter past
        both sides."""
        css = _read(CSS)
        i = css.index('.cfg-shell {')
        block = css[i:css.index('}', i)]
        assert '-.75rem' in block, 'the container top padding still shows above it'
        assert 'var(--bs-gutter-x' in block, 'the container gutters still show beside it'
        assert '-1rem' in block, 'the container pb-3 still shows under it'
        assert '.cfg-main > .ss-bleed-top { margin: 0; }' in css, \
            'the toolbar cancels the same padding a second time'

    def test_the_index_scrolls_on_its_own(self):
        """It is as tall as the configuration; an index that scrolls away with the detail stops
        being an index exactly when the detail gets long."""
        css = _read(CSS)
        assert '.cfg-rail' in css and 'overflow-y: auto' in css


class TestItIsAPassNotARenderer:

    def test_it_renders_no_field(self):
        """The whole point: one renderer. An index that built its own field would be free to
        disagree with the card beside it about the same option."""
        body = _read(VIEWS)
        for forbidden in ('_fieldRow(', 'renderField(', 'fieldCtl('):
            assert forbidden not in body, f'the index renders its own fields ({forbidden})'

    def test_the_renderer_applies_it_last(self):
        body = _fn(_read(RENDER), 'renderConfig')
        assert '_cfgApplyView()' in body
        assert body.index('_cfgApplyView()') < body.index('_filterConfig(_cfgSearchTerm)'), \
            'the search filter must run after the index, or the index undoes it'

    def test_each_pass_undoes_the_last(self):
        """A pass that hides and moves nodes has to be undone before the next one runs, or two
        of them compose into a third nobody designed."""
        body = _fn(_read(VIEWS), '_cfgApplyView')
        assert 'data-cfg-hidden-by-view' in body


class TestTheSearchAndTheIndexShareOneScreen:
    """Both decide which cards are on screen, so they have to agree about who is deciding."""

    def test_searching_looks_across_every_section(self):
        """The index shows one section; the search must not be confined to it. Every card is in
        the DOM precisely so that a search can reach the thirty-three that are hidden."""
        body = _fn(_read(RENDER), '_filterConfig')
        assert "container.querySelectorAll" in body
        assert 'cfgcol_' in body

    def test_emptying_the_box_hands_the_screen_back(self):
        """Not "show all thirty-four cards at once" — that is nobody's idea of a configuration
        screen. An empty box means the search is over, and what the section looks like when
        nobody is searching is the index."""
        body = _fn(_read(RENDER), '_filterConfig')
        assert '_cfgApplyView()' in body

    def test_picking_a_section_ends_the_search(self):
        """Otherwise the section opens with most of its fields still hidden by a filter whose
        box is collapsed out of sight."""
        body = _fn(_read(VIEWS), 'setConfigRailCard')
        assert "_filterConfig('')" in body
