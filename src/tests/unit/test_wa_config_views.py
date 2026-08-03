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

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
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


def _card_open() -> str:
    """`cfgCardOpen` is nested inside `renderConfig`, so it has no closing brace at column 0
    for `_fn` to stop at. Read it up to the sibling it is always followed by."""
    src = _read(RENDER)
    i = src.index('function cfgCardOpen')
    return src[i:src.index('const cfgCardClose', i)]


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
        body = _fn(_read(VIEWS), '_cfgFieldIsChanged')
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
        """One call, because the filter now runs INSIDE it: `renderConfig` used to apply the
        index and then re-apply the search, which only worked while the two happened to be
        idempotent in that order."""
        body = _fn(_read(RENDER), 'renderConfig')
        assert '_cfgApplyView()' in body
        assert '_filterConfig(' not in body, 'two entry points decide what is on screen'

    def test_each_pass_undoes_the_last_before_the_filter_runs(self):
        """A pass that hides nodes has to be undone before the next one runs, or two of them
        compose into a third nobody designed. The ORDER is the part that was wrong: the index
        marks the sections it hides, and restoring those marks AFTER the filter handed
        visibility straight back to every section the filter had just hidden — the same
        sections, hidden twice for different reasons — so the index saw all thirty-four
        survive and listed them."""
        body = _fn(_read(VIEWS), '_cfgApplyView')
        assert 'data-cfg-hidden-by-view' in body
        assert body.index('data-cfg-hidden-by-view') < body.index('_cfgFilterPass(c)') \
            < body.index('_cfgViewRail(c)'), 'restore, filter, index — in that order'


class TestTheSearchAndTheIndexShareOneScreen:
    """Both decide which cards are on screen, so they have to agree about who is deciding."""

    def test_searching_looks_across_every_section(self):
        """The index shows one section; the search must not be confined to it. Every card is in
        the DOM precisely so that a search can reach the thirty-three that are hidden."""
        body = _fn(_read(RENDER), '_cfgFilterPass')
        assert 'rounded-3' not in body, 'the search matches a frame instead of a section'
        assert "querySelectorAll('.cfg-field-wrap')" in body

    def test_the_filter_and_the_index_mean_the_same_thing_by_section(self):
        """Reported: with "only modified" on and "idioma" typed, Templates stayed in the index
        with no matches and nothing to show. It is two cards inside a wrapper, and the wrapper —
        the thing the index actually lists — is not a `.cfg-card`, so the filter, which walked
        `.cfg-card`, never decided about it and it survived untouched.

        Both now walk `_cfgCardNode`, which is what the index navigates by. Two passes with two
        ideas of what a section is will always disagree about one of them, and it will be the
        one built slightly differently from the rest."""
        body = _fn(_read(RENDER), '_cfgFilterPass')
        assert '_cfgCardNode(container, card)' in body
        assert "container.querySelectorAll('.cfg-card')" not in body

    def test_emptying_the_box_hands_the_screen_back(self):
        """Not "show all thirty-four cards at once" — that is nobody's idea of a configuration
        screen. An empty box means the search is over, and what the section looks like when
        nobody is searching is the index."""
        body = _fn(_read(RENDER), '_filterConfig')
        assert '_cfgApplyView()' in body

    def test_the_index_becomes_the_result_list(self):
        """Reported: the sheet answered "here it is" and the index went on listing all
        thirty-four sections beside it, as if nothing had been asked. While a search is running
        the index IS the result list — only the sections that matched, each with how many of
        its options did — and a group with nothing in it does not appear at all.

        The badge changes colour with its meaning: "matched here" and "departs from stock" are
        different questions, and one badge meaning either depending on a box elsewhere on the
        screen means neither."""
        body = _fn(_read(VIEWS), '_cfgViewRail')
        assert 'const searching' in body
        assert "all.filter(card => _cfgCardNode(c, card).style.display !== 'none')" in body
        assert '_cfgMatchCount(el)' in body
        assert "'text-bg-info'" in body and "'text-bg-warning'" in body

    def test_a_search_that_matched_nothing_says_so(self):
        """Silence where the results would be reads as "the index broke", which is the wrong
        thing to have the reader wondering about."""
        body = _fn(_read(VIEWS), '_cfgViewRail')
        assert 'cfg_search_no_section' in body
        for lang in ('es_ES', 'en_EN'):
            assert "'cfg_search_no_section'" in _read(
                os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))

    def test_only_one_pass_decides_which_rows_are_on_screen(self):
        """The search and "only what changed" are two conditions on the same question, so they
        compose inside `_filterConfig`. They used to be two passes taking turns overwriting each
        other's `display`, where the visible result depends on which ran last — not a rule
        anybody could predict from the screen."""
        body = _fn(_read(RENDER), '_cfgFilterPass')
        assert '_cfgFieldIsChanged(wrap)' in body and 'hit &&' in body
        head = _fn(_read(VIEWS), '_cfgSheetHead')
        assert 'style.display' not in head, 'the header pass hides rows again'

    def test_changed_is_defined_once(self):
        """Written out three times, they agreed only by luck: the day one learned about
        env-locked and the others did not, the count and the list it was counting stopped
        matching."""
        body = _read(VIEWS)
        assert body.count('function _cfgFieldIsChanged') == 1
        assert '_cfgFieldIsChanged(w)' in _fn(body, '_cfgCardChangedCount')

    def test_only_what_changed_is_a_switch_in_the_toolbar(self):
        """A switch, not a button: it is a MODE that stays on while you work, and a switch is
        the one control that shows its own state without being pressed. It reports the mode even
        when something else set it — the count badge in a section header is the same switch, and
        a control that tracks only its own clicks starts lying the first time anything else
        turns the mode on."""
        pane = _read(PANE)
        assert 'chkCfgChangedOnly' in pane and 'form-switch' in pane
        assert 'toggleConfigChangedOnly()' in pane
        body = _fn(_read(RENDER), '_cfgFilterPass')
        assert 'sw.checked = changedOnly' in body, 'the switch never reflects the mode'
        for lang in ('es_ES', 'en_EN'):
            assert "'cfg_changed_only_short'" in _read(
                os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))

    def test_the_mode_narrows_what_is_listed_without_changing_how_it_is_navigated(self):
        """Two different things narrow this screen and they narrow different parts of it.

        SEARCHING replaces the navigation — asking "where is X" and being shown one section at
        a time is not an answer — so the sheet becomes a result list. "Only what changed" is a
        mode: everything is navigated exactly as before, one section at a time picked from the
        index, and all it does is drop sections with no changes out of the index and options
        still at their shipped value out of the section. A mode that also changes how you move
        around has stopped being a mode and become a different screen."""
        rail = _fn(_read(VIEWS), '_cfgViewRail')
        assert 'for (const card of (searching ? cards : all))' in rail, \
            'the mode took over the navigation, not just the listing'
        assert 'const filtering = searching || _cfgChangedOnly' in rail, \
            'the index is not narrowed by the mode'
        assert 'if (filtering && !cards.length)' in rail

    def test_a_section_with_nothing_left_to_show_is_not_where_you_land(self):
        """The section you were in may hold no changes at all. An empty sheet beside an index
        that lists other sections reads as a fault rather than as an answer."""
        rail = _fn(_read(VIEWS), '_cfgViewRail')
        assert 'if (!searching && cards.length && !cards.some(' in rail

    def test_the_switch_runs_through_the_one_redraw(self):
        """Everything that changes what is on screen goes through `_cfgApplyView`, because
        the ORDER — restore, filter, index — is the part that is easy to get wrong and was."""
        toggle = _fn(_read(VIEWS), 'toggleConfigChangedOnly')
        assert '_cfgApplyView()' in toggle

    def test_putting_the_box_away_ends_the_search(self):
        """Closing the box is how you say you are done searching. A term left running from a
        control that is no longer on screen leaves the panel showing a fraction of itself with
        nothing visible to explain why — a state that used to need a warning dot on the toggle
        to be survivable, and now cannot happen, so the dot went with it. A badge for an
        impossible state is one more thing to keep true."""
        wiring = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                    'init', '_wiring.html'))
        i = wiring.index("getElementById('cfgSearchBox')?.addEventListener('hidden.bs.collapse'")
        assert "_filterConfig('')" in wiring[i:i + 400]
        assert 'badgeCfgFilter' not in _read(PANE) and 'badgeCfgFilter' not in _read(RENDER)

    def test_picking_a_section_ends_the_search(self):
        """Otherwise the section opens with most of its fields still hidden by a filter whose
        box is collapsed out of sight."""
        body = _fn(_read(VIEWS), 'setConfigRailCard')
        assert "_filterConfig('')" in body


class TestASectionIsASheetNotACard:
    """The frame, the chevron and the colour accent were right when seven tabs showed several
    cards at once. With one section on screen the box is a frame inside a frame, the chevron
    collapses the only thing there, and the accent distinguishes it from nothing — the index
    already says which section you are in, and says it better."""

    def test_the_card_frame_is_gone(self):
        body = _card_open()
        for forbidden in ('rounded-3', 'cfg-card-accent', 'cfg-chevron', 'data-bs-toggle="collapse"'):
            assert forbidden not in body, f'the section is still drawn as a card ({forbidden})'

    def test_nothing_remembers_a_collapse_that_cannot_happen(self):
        """`renderConfig` used to save which cards were open so a re-render could restore them.
        There is nothing to restore: a sheet cannot be shut."""
        body = _fn(_read(RENDER), 'renderConfig')
        assert 'prevState' not in body

    def test_fail2ban_keeps_its_cards(self):
        """`.cfg-card` is also the fail2ban section's chrome, and that screen still shows
        several at once — where a frame, a header and a chevron all earn their keep. Every
        sheet rule is scoped under `.cfg-sheet` so it cannot reach them."""
        css = _read(CSS)
        for rule in ('.cfg-sheet .cfg-card', '.cfg-sheet .cfg-fields .cfg-field-wrap'):
            assert rule in css, rule
        ipban = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                   'ipban', '_render.html'))
        assert 'cfg-card-header' in ipban and 'cfg-chevron' in ipban

    def test_the_header_says_what_the_section_is(self):
        body = _card_open()
        for part in ('cfg-sheet-title', 'cfg-sheet-count', 'cfg-sheet-desc'):
            assert part in body, part

    def test_the_count_is_computed_once(self):
        """The index already counts what departs from stock for every section. A header
        computing it again is a second place for the same number to be wrong — so the header
        ships empty and the pass that draws the index fills it."""
        head = _fn(_read(VIEWS), '_cfgSheetHead')
        assert '_cfgCardChangedCount(el)' in head
        open_body = _card_open()
        assert '_cfgCardChangedCount' not in open_body

    def test_the_count_filters_the_sheet(self):
        """Reading "3 modified" and then hunting for the three is the work the number was
        supposed to save, so the count is a button: it turns on the same filter the toolbar
        offers. Env-locked survives it — the deployment moved it, and it is the one an admin
        cannot move back from this screen."""
        assert 'toggleConfigChangedOnly' in _card_open(), 'the count is not clickable'
        assert 'data-env-locked' in _fn(_read(VIEWS), '_cfgFieldIsChanged')

    def test_an_unset_option_is_not_an_edited_one(self):
        """Reported: the bind address sat empty with 0.0.0.0 greyed behind it, and the row was
        marked as edited. Blank is how "not set" is stored, and not set IS the default — the
        placeholder had been saying exactly that. Comparing the two as text made every unset
        option look like a change away from a value it was never given.

        `0` and `false` are real answers and go on being compared."""
        body = _fn(_read(VIEWS), '_cfgIsDefault')
        assert "if (cur === undefined || cur === null || cur === '') return true;" in body

    def test_a_locked_option_is_marked_wherever_it_is_drawn(self):
        """The env/file lock used to be bolted onto the wrapper by `renderScalarFields`, which
        only bespoke cards go through. The same option was therefore marked in one kind of card
        and unmarked in another, and everything reading the mark — the count, the accent —
        disagreed with itself depending on where the option happened to live."""
        fr = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                '_field_render.html'))
        i = fr.index('return `<div class="cfg-field-wrap${_wrapCls}"')
        assert '_lockAttr' in fr[i - 400:i + 200], 'the wrapper does not carry the lock mark'
        assert "_rawFHtml.replace(/^<div /, '<div data-env-locked" not in fr, \
            'one caller still marks it on its own'

    def test_every_row_says_whether_it_is_stock_or_edited(self):
        """The header counts them and the index counts them per section, but neither answers it
        for the row in front of you — and "is this 60 mine or theirs?" is asked one option at a
        time, in the middle of changing something else.

        Two signals, because a colour alone is not one: an accent down the left edge to scan a
        column by, and the row's own "restore" button going dim and inert when there is nothing
        to restore. That button always sat there offering a no-op on stock rows; reporting the
        state costs nothing and answers the reader who cannot use the colour."""
        mark = _fn(_read(VIEWS), '_cfgMarkRow')
        assert "classList.toggle('cfg-row-changed'" in mark
        assert 'reset.disabled = !changed' in mark, 'the button still offers a no-op'
        assert 'cfg_at_default' in mark
        css = _read(CSS)
        i = css.index('.cfg-sheet .cfg-fields .cfg-field-wrap.cfg-row-changed {')
        assert 'box-shadow: inset' in css[i:css.index('}', i)], \
            'a border here shifts the marked row against the ones around it'
        assert '_cfgMarkRow(wrap)' in _fn(_read(RENDER), '_cfgFilterPass'), \
            'the mark is not refreshed by the pass that already walks every row'

    def test_the_four_hand_written_selects_are_declared_instead(self):
        """Audited on request: five rows drew their own control instead of going through
        `renderField`. Four of them were selects the registry could describe completely — and
        a hand-written control quietly misses whatever the shared one learns next. These four
        missed the env/file lock, so an option pinned in `config.json` looked editable and the
        save was discarded server-side without a word.

        They are declared now (options, per-option labels, default, and `on_change` for the
        sibling to refresh) and the shared renderer draws them."""
        import sys as _sys
        if SRC not in _sys.path:
            _sys.path.insert(0, SRC)
        from lib.core.config.service import build_config_schema
        sch = build_config_schema()
        for path in ('web_admin|audit_sort', 'web_admin|audit_sort_dir',
                     'email|provider', 'msteams|delivery'):
            meta = sch.get(path) or {}
            assert meta.get('options'), f'{path}: no options in the schema'
            assert meta.get('options_i18n'), f'{path}: option labels still live in the JS'
        for path in ('web_admin|audit_sort_dir', 'email|provider', 'msteams|delivery'):
            assert (sch[path]).get('on_change'), f'{path}: its side-effect is undeclared'
        # …and the markup that used to draw them is gone.
        for body, gone in ((_read(RENDER), 'auditSortOpts'),
                           (_read(os.path.join(CFG, 'notify', '_email.html')), 'pvOpts'),
                           (_read(os.path.join(CFG, 'notify', '_msteams.html')), 'delOpts')):
            assert gone not in body, f'{gone}: the hand-written select survives'
        assert 'configData.web_admin.audit_sort' not in _read(RENDER), \
            'an option is written behind updateField’s back'

    def test_the_shared_renderer_can_carry_a_side_effect(self):
        """The one thing a select could need that the registry could not say, and the reason
        four of them were hand-written. The function name belongs to whoever needs it, not to
        the core — the same rule a module follows when it names its own action."""
        body = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                  '_field_render.html'))
        assert 'meta.on_change' in body
        for guess in ('_emailProviderChanged', '_msteamsDeliveryChanged', '_applyAuditSortDir'):
            assert guess not in body, f'the core learned a caller’s function name ({guess})'

    def test_a_list_of_numbers_is_vocabulary_not_a_hand_written_box(self):
        """The last hand-written row. The renderer knew a list of STRINGS (`multi`) and an array
        it stored as strings, so an option holding numbers had nowhere to land and was written
        out here — missing the env/file lock and repeating its own default as a literal
        placeholder. `int_list` is that missing word; the shared renderer draws it now.

        The list is the REFERENCE for the row above it: `_refreshTableRowChoices` re-reads it
        after every save, so editing it changes what the other option can be set to."""
        body = _read(RENDER)
        assert "renderField('table_rows_options'" in body
        assert "const _psPath" not in body, 'the hand-written control survives'
        fr = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                '_field_render.html'))
        assert 'meta.int_list' in fr and "'updateIntArray'" in fr
        save = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'actions',
                                  '_save.html'))
        assert '_refreshTableRowChoices()' in save, 'the reference list stops refreshing on save'

    def test_the_row_counts_are_declared_once_in_the_registry(self):
        """`[25, 50, 100, 200, 0]` was a literal in three files, so changing it meant finding
        all three — and "one copy per side, with a guard" is still two copies. It is a registry
        option now, so its default has exactly one home and reaches the panel the way every
        other default does."""
        import sys as _sys
        if SRC not in _sys.path:
            _sys.path.insert(0, SRC)
        from lib.config.spec import cfg_default, registry_defaults
        assert cfg_default('web_admin|table_rows_options') == [15, 25, 50, 100, 200, 0]
        assert 'web_admin|table_rows_options' in registry_defaults(), \
            'the panel never receives it'
        consts = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                    '_constants.html'))
        assert 'PAGE_SIZE_CHOICES' not in consts, 'the panel keeps a copy of its own'
        assert "CONFIG_REGISTRY_DEFAULTS['web_admin|table_rows_options']" in consts
        for name in ('lib/core/config/service.py', 'lib/web_admin/app.py'):
            assert 'PAGE_SIZE_CHOICES' not in _read(os.path.join(SRC, *name.split('/'))), name

    def test_clearing_a_list_option_means_its_default(self):
        """Reported: emptying the row-count list produced "must be a list of non-negative
        integers". Clearing yielded an EMPTY list, which the server rejects outright — it was
        the only thing clearing could produce, and it contradicted the rule the rest of this
        screen teaches and this box's own greyed placeholder states.

        Blank is the default here too, and at its default the box is drawn empty — which is
        what makes "clear it to get the default back" true rather than a claim."""
        ops = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'actions',
                                 '_field_ops.html'))
        i = ops.index('function updateIntArray')
        assert 'cfgDefaultFor(pathStr)' in ops[i:i + 700], 'an empty list is still saved'
        fr = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                '_field_render.html'))
        assert 'const _shown = (_isInts && csv === _dfltCsv)' in fr, \
            'the box prints its default as a value, so clearing looks like a change'
        # The server keeps rejecting an empty list — nothing can produce one now, and that is
        # the last line of defence rather than the first thing a reader meets.
        svc = _read(os.path.join(SRC, 'lib', 'core', 'config', 'service.py'))
        assert "raise AdminOpError('invalid_table_rows_options')" in svc

    def test_no_table_carries_a_second_default(self):
        """Reported: `let _syslogPageSize = _tableRowsDefault || 50;`. Two faults in one line.
        It ran at PARSE time, before the config had loaded, so the admin's choice never reached
        it — the number was decided by the declaration and nothing could change it. And `|| 50`
        turned 0 into fifty, when 0 is "show all": a real answer, silently overruled.

        Every table reads the configured value on first use, and nothing supplies a number of
        its own beside it."""
        base = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials')
        for rel in ('syslog/_columns.html', 'clusters/_modal.html', 'servers/_monitoring.html',
                    'actions/_save.html', 'init/_wiring.html'):
            body = _read(os.path.join(base, *rel.split('/')))
            assert '_tableRowsDefault || ' not in body, f'{rel}: a second default beside it'
            assert '_tableRowsDefault ?? ' not in body, f'{rel}: a second default beside it'
        poll = _read(os.path.join(base, 'syslog', '_poll.html'))
        assert 'if (_syslogRows === null) _syslogRows = _tableRowsDefault;' in poll, \
            'the syslog table still decides its rows before the config exists'
        consts = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                    '_constants.html'))
        assert "_tableRowsDefault = CONFIG_REGISTRY_DEFAULTS['web_admin|table_rows_default']" in consts

    def test_options_are_named_for_what_they_hold_not_how_it_is_stored(self):
        """`max_rows` was the same mistake as `page_size`: table vocabulary for what an admin is
        actually setting, which is a number of MESSAGES. The store keeps `prune(max_rows=…)` —
        at that layer they really are rows, and renaming it there would have been the opposite
        error."""
        import sys as _sys
        if SRC not in _sys.path:
            _sys.path.insert(0, SRC)
        from lib.config.spec import CFG_BY_PATH
        assert 'syslog|max_messages' in CFG_BY_PATH
        assert 'syslog|max_rows' not in CFG_BY_PATH
        store = _read(os.path.join(SRC, 'lib', 'services', 'syslog', 'store', 'messages.py'))
        assert 'max_rows' in store, 'the store layer lost the word that is right for it'

    def test_a_shared_field_name_says_which_section_it_is_in(self):
        """"Default role (new items)" named neither who gets the role nor when, and four
        providers shared it. Each says its own thing now — LDAP/OIDC/SAML2 assign it when no
        group maps, SCIM when a user is provisioned — because a label keyed only by bare name
        is a label the next section with that field will inherit whether it fits or not."""
        from lib.i18n import TRANSLATIONS
        for lang in ('es_ES', 'en_EN'):
            labels = TRANSLATIONS[lang]['labels']
            for path in ('ldap|default_role', 'oidc|default_role', 'saml2|default_role',
                         'scim|default_role', 'scim|token', 'msteams_channels|name'):
                assert labels.get(path), f'{lang}: {path} still inherits a bare name'
            assert labels['scim|default_role'] != labels['ldap|default_role'], \
                'provisioning and "no group matched" are not the same moment'

    def test_the_pagination_options_say_what_they_count(self):
        """"Page size" reads as something about the size of the page; it names neither tables
        nor records. They are a pair — one is the list of row counts a table's chooser offers,
        the other is which of them a table opens on — so they are named as one."""
        import sys as _sys
        if SRC not in _sys.path:
            _sys.path.insert(0, SRC)
        from lib.config.spec import CFG_BY_PATH
        assert 'web_admin|table_rows_default' in CFG_BY_PATH
        assert 'web_admin|table_rows_options' in CFG_BY_PATH
        for gone in ('web_admin|default_page_size', 'web_admin|page_sizes'):
            assert gone not in CFG_BY_PATH, f'{gone} survives in the registry'

    def test_a_ui_preference_has_a_default_too(self):
        """Sort order and page sizes are not in `spec.py` at all — they are UI preferences by
        design — so a check that read only the registry found no default for them and reported
        them as edited for ever. And `audit_sort_dir` had no default in either map, which made
        its restore button call a function that bailed on the spot: a control that looks live,
        does nothing, and says nothing about it."""
        body = _fn(_read(VIEWS), '_cfgIsDefault')
        assert 'cfgDefaultFor(path)' in body
        assert 'CONFIG_REGISTRY_DEFAULTS' not in body, 'half the answer, again'
        consts = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                                    '_constants.html'))
        for key in ("'web_admin|audit_sort'", "'web_admin|audit_sort_dir'",
                    "'web_admin|table_rows_options'"):
            assert key in consts, f'{key} has no default anywhere'

    def test_a_row_that_is_not_a_registry_option_still_answers(self):
        """Reported: fail2ban's exposed services had no restore button and never reported an
        edit. Each row there is a record in its own store, written through its own endpoint,
        so the registry has nothing to compare it against — a reason to behave differently on
        the WIRE, not on the screen. A reader has no way to know which rows are backed by which
        store and should not need one.

        `data-cfg-changed` lets such a row answer for itself, through the same predicate as
        everything else, so the card stops being a hole in every total."""
        pred = _fn(_read(VIEWS), '_cfgFieldIsChanged')
        assert "w.hasAttribute('data-cfg-changed')" in pred
        assert '[data-cfg-changed]' in _fn(_read(VIEWS), '_cfgCardChangedCount'), \
            'the section count still skips it'
        card = _read(os.path.join(CFG, '_ipban.html'))
        assert 'data-cfg-changed="${overridden' in card
        assert '_ipbanSvcSetAction(${jsStr(s.id)},' in card and 'reset_field' in card, \
            'the row has no way back to the service default'
        assert '_cfgRefreshMarks' in card, 'changing a row leaves the counts behind'
        assert '.cfg-sheet tr.cfg-row-changed > td:first-child' in _read(CSS), \
            'a box-shadow on a <tr> is not painted in every engine'

    def test_pending_is_its_own_state(self):
        """"Edited" and "edited and not yet saved" answer different worries — one about this
        install, one about the last thirty seconds. Collapsed into one colour, a row you just
        typed into looks exactly like one somebody configured last year. Pending wins while it
        lasts, including when the edit takes the option back TO its default: that is still a
        change waiting to be written."""
        mark = _fn(_read(VIEWS), '_cfgMarkRow')
        assert '_dirtyFields.has(path)' in mark
        assert "classList.toggle('cfg-row-dirty', dirty)" in mark
        assert "classList.toggle('cfg-row-changed', changed && !dirty)" in mark
        assert '.cfg-sheet .cfg-fields .cfg-field-wrap.cfg-row-dirty {' in _read(CSS)

    def test_putting_a_value_back_undoes_the_pending_state(self):
        """Reported: change the audit sort direction and put it back, and the row stays marked
        as pending with Save still lit.

        Two causes, and the second is the bigger one. The pending set only ever grew, so a path
        stayed staged after being undone — which also means the save wrote a value the server
        already held. And `markDirty` decides the Save button by comparing the whole of
        `configData` against an "as loaded" baseline taken BEFORE `renderConfig` seeds the
        options the server never sent; from the first render the two differed by dozens of keys
        nobody had touched. The button stayed off only because nothing compared them until the
        first edit — after that, putting the value back could never turn it off, because the
        difference was never the value."""
        ops = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'actions',
                                 '_field_ops.html'))
        assert '_dirtyFields.delete(pathStr)' in ops, 'the pending set only grows'
        mirror = _fn(_read(RENDER), '_cfgMirrorSeeded')
        assert 'in _serverConfigData[sec]' in mirror, \
            'seeding still reads as an edit against the baseline'
        assert '_cfgMirrorSeeded()' in _fn(_read(RENDER), 'renderConfig')

    def test_an_option_the_server_never_sent_still_has_something_to_return_to(self):
        """Reported after the first fix: the audit sort field stayed marked as edited on the way
        back, while its sibling was fine. The sibling happens to be seeded at render time; this
        one is only ever read as `wa.audit_sort || 'time'`, so the key never existed — and a
        comparison against `undefined` can never match anything a reader can type.

        What the server would use for an option it never stored is that option's default, so
        that is what "unchanged" means for it. And once the value has been typed, the key exists
        on one side and not the other, which the whole-object comparison behind the Save button
        reads as a change: it is written into the baseline too, but only where the two values
        are already equal, so a real edit can never be accepted as the new "as loaded" state."""
        ops = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'actions',
                                 '_field_ops.html'))
        assert 'was === undefined' in ops and 'cfgDefaultFor(pathStr)' in ops
        i = ops.index('_dirtyFields.delete(pathStr);')
        assert 'setPath(_serverConfigData, parts' in ops[i:i + 700], \
            'the key exists on one side only, so Save stays lit'

    def test_a_record_saved_by_its_own_endpoint_is_saved_state(self):
        """Webhooks, Teams channels and the scheduler interval are records with their own
        routes: the panel writes them to the server and then syncs the in-memory copy so the
        screen agrees. Only the copy was synced — and the Save button is decided by comparing
        that copy against the baseline, so creating a webhook lit "unsaved changes" for
        something already written. Clicking Save then sent nothing (it sends `_dirtyFields`,
        which these never enter) and could not put the light out."""
        adopt = _fn(_read(RENDER), '_cfgAdoptSection')
        assert '_serverConfigData[section] = deepClone(configData[section])' in adopt
        for name, section in ((os.path.join(CFG, 'notify', '_webhooks.html'), 'webhooks'),
                              (os.path.join(CFG, 'notify', '_msteams.html'), 'msteams_channels')):
            body = _read(name)
            assert body.count(f"_cfgAdoptSection('{section}')") >= 3, \
                f'{section}: create, delete and toggle must all tell the baseline'
        daemon = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'status',
                                    '_daemon.html'))
        assert "_cfgAdoptSection('monitoring')" in daemon

    def test_the_baseline_is_only_ever_given_keys_it_lacks(self):
        """A real edit changes a key BOTH sides already have, so adding only what is missing
        cannot swallow one. Overwriting a value the baseline holds would silently accept an
        edit as the new "as loaded" state — the save button would go out with the change still
        unwritten."""
        mirror = _fn(_read(RENDER), '_cfgMirrorSeeded')
        assert 'if (!(k in _serverConfigData[sec]))' in mirror

    def test_the_marks_and_the_counts_follow_an_edit_and_a_save(self):
        """Reported: a row you had just changed went on claiming to be stock, and stayed wrong
        through the save — until you left the section and came back. A number that is only
        right at certain moments is worse than no number, because nobody can tell which moment
        they are in.

        Not a re-render and not a re-filter: the fields keep their DOM, so focus, caret and
        half-typed values survive, and the rows on screen do not shift under the hands of
        someone in the middle of typing."""
        refresh = _fn(_read(VIEWS), '_cfgRefreshMarks')
        assert '_cfgMarkRow' in refresh and '_cfgViewRail(c)' in refresh
        assert '_cfgFilterPass' not in refresh, 'editing would move the rows out from under you'
        ops = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'actions',
                                 '_field_ops.html'))
        assert '_cfgRefreshMarks()' in ops, 'an edit leaves its own row saying the opposite'
        save = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'actions',
                                  '_save.html'))
        i = save.index("_serverConfigData = deepClone(configData);")
        assert '_cfgRefreshMarks()' in save[i:i + 700], \
            'a clean save leaves every row wearing the colour of an unsaved change'

    def test_the_tooltip_is_updated_through_bootstrap(self):
        """`title` is moved into Bootstrap's own store on init and never read again, so writing
        it here leaves the tip saying the old thing and adds a second, native tooltip under it.
        """
        mark = _fn(_read(VIEWS), '_cfgMarkRow')
        assert 'setContent' in mark and 'data-bs-original-title' in mark

    def test_the_description_comes_from_the_layout(self):
        """Placement is decided in `lib.config.layout`; a renderer inventing its own key name
        would be a section able to describe itself differently from how the registry does."""
        head = _fn(_read(VIEWS), '_cfgSheetHead')
        assert 'card.desc_key' in head
        assert "'cfg_desc_" not in head, 'the key is spelled in the frontend'

    def test_every_section_has_a_description(self):
        import sys as _sys
        if SRC not in _sys.path:
            _sys.path.insert(0, SRC)
        from lib.config.layout import config_layout
        cards = config_layout()['cards']
        missing = [c['id'] for c in cards if 'desc_key' not in c]
        assert not missing, f'sections with no one-line description: {missing}'

    def test_a_description_is_registered_by_writing_it(self):
        """By convention (`cfg_desc_<id>`), not by a key spelled out on every entry: thirty-four
        cards would otherwise be thirty-four chances to add a section and forget the line."""
        body = _read(os.path.join(SRC, 'lib', 'config', 'layout.py'))
        assert "'cfg_desc_' + d['id']" in body


class TestTheHeaderIsPinned:
    """One sheet. Three were built to be compared on real data — a plain list, one with every
    hint in view instead of behind an (i), and this one — and the two that lost took their CSS,
    their strings and their switcher with them the day it was decided. Three ways to draw the
    same rows is what this screen was rebuilt to stop doing.

    What is pinned is which section you are editing and how much of it this install has moved:
    the two things a long list of options makes you scroll back up to check."""

    def test_only_one_sheet_survives(self):
        body = _read(VIEWS)
        for forbidden in ('CFG_SHEETS', 'setConfigSheet', 'ss_cfg_sheet', '_cfgSheetSwitcher'):
            assert forbidden not in body, f'a layout switcher survives ({forbidden})'
        assert 'cfgSheetSwitch' not in _read(PANE), 'the toolbar still offers a choice'
        css = _read(CSS)
        for forbidden in ('.cfg-sheet-wide', '.cfg-sheet-flat', '.cfg-sheet-sticky'):
            assert forbidden not in css, f'a losing layout left its CSS behind ({forbidden})'
        for lang in ('es_ES', 'en_EN'):
            assert 'cfg_sheet_' not in _read(os.path.join(SRC, 'lib', 'i18n', 'lang',
                                                          f'{lang}.py')), \
                'a losing layout left its strings behind'

    def test_a_pinned_header_covers_what_passes_under_it_and_nothing_else(self):
        """Reported three times from screenshots, each about a pinned thing not sitting right.

        `.ss-scroll-fade` masks the top 10px of the scroll box — exactly where the header pins —
        so the header was fading itself and rows showed through. The scroll box also opens with
        padding there, which put a strip of page background between the header and the toolbar.
        And it wears the toolbar's colour: chrome a shade off the surface it floats over reads
        as a rendering seam, not as a header.

        What it must NOT do is reach past the rows it covers. Bootstrap's `.row` overflows by
        half a gutter, but the columns pad it straight back, so nothing visible passes outside;
        stretching the header to cover that gutter only made it paint over the pane's own edge,
        which looks like a mistake rather than like chrome."""
        css = _read(CSS)
        i = css.index('.cfg-sheet .cfg-sheet-head {')
        block = css[i:css.index('}', i)]
        assert 'position: sticky' in block and 'top: 0' in block
        assert 'margin:' not in block, 'the header reaches past the rows, over the pane edge'
        assert 'var(--ss-card-header-bg' in block, \
            'chrome a shade off the surface it floats over reads as a seam, not a header'
        assert '.cfg-sheet.ss-scroll-fade { -webkit-mask-image: none; mask-image: none; }' in css
        assert '.cfg-sheet.ss-scroll-pad { padding-top: 0; }' in css, \
            'the scroll box opens with padding right where the header pins — a strip of page ' \
            'background between it and the toolbar'

    def test_only_the_header_against_the_toolbar_has_a_square_top(self):
        """A search puts several sections on screen. The first is continuous with the bar above
        it, so it keeps a square top and a rounded bottom — the same thing `.ss-bleed-top` says
        about the toolbar: this is the line the scrolling body disappears under, and rounding it
        is what says so. The rest float in the middle of the sheet, and one square edge on a
        block that touches nothing looks attached to something that is not there.

        Marked by the pass, not by `:first-child`: hidden sections stay in the DOM, so the first
        CHILD and the first one VISIBLE are rarely the same element."""
        css = _read(CSS)
        i = css.index('.cfg-sheet .cfg-sheet-head {')
        assert 'border-radius: .375rem' in css[i:css.index('}', i)], 'the floating ones stay square'
        assert '.cfg-sheet .cfg-card-first .cfg-sheet-head {' in css
        rail = _fn(_read(VIEWS), '_cfgViewRail')
        assert "classList.add('cfg-card-first')" in rail
        assert "classList.remove('cfg-card-first')" in rail, 'the mark is never cleared'

    def test_the_bar_still_says_it_is_on_top(self):
        """Taking the mask off cost a second thing it was doing. Softening the header was the
        bug; the depth cue between the toolbar and what scrolls under it was worth keeping, and
        without it the two read as halves of one flat block.

        It comes back as a shadow cast BY the bar — the thing that is actually above — rather
        than as a fade applied to whatever happens to be beneath it, and above the header in
        the stack so it lands on the header instead of behind it."""
        css = _read(CSS)
        i = css.index('.cfg-main > .ss-bleed-top { position: relative;')
        block = css[i:css.index('}', i)]
        assert 'box-shadow' in block and 'z-index: 11' in block

    def test_the_list_breathes_at_its_ends_and_nowhere_else(self):
        """The first option pressed against the header read as part of it, and the last against
        the edge of the pane read as cut off. Between rows the hairline IS the separation —
        spacing them too would make four options look like four groups of one."""
        css = _read(CSS)
        i = css.index('.cfg-sheet .cfg-card .cfg-fields {')
        assert 'padding: .55rem 0 .75rem' in css[i:css.index('}', i)]


class TestAnOptionThatDoesNotApplyIsNotCounted:
    """Reported from Database: on SQLite the section offers two options and the index said six.

    The four missing ones were the host / port / user / password of a MySQL deployment — still
    in the config, no longer applying to anything, and still being counted. The number then
    sent the reader hunting for four settings that are not on the screen and would do nothing
    if they were, which is the opposite of what "6 modified" is for.

    Conditional options declare themselves with `.sw-field[data-sw-when]`, so the answer was
    already in the DOM; nothing was asking it.
    """

    FIELD_RENDER = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                'core', '_field_render.html')

    def test_the_one_definition_asks_whether_it_applies(self):
        """Into `_cfgFieldIsChanged` rather than into the counter: it is the single definition
        the count, the filter and the index all read, and putting it anywhere else would fix
        the number while leaving the list it counts unchanged."""
        body = _fn(_read(VIEWS), '_cfgFieldIsChanged')
        assert '_cfgFieldApplies' in body, \
            'the count is back to including options the current engine rules out'
        assert body.index('_cfgFieldApplies') < body.index('data-cfg-changed'), \
            'applicability is decided after the answer has already been given'

    def test_it_reads_the_marker_and_never_computed_visibility(self):
        """`offsetParent`/`getComputedStyle` would be the obvious way and would be catastrophic
        here: every card but the section on screen is hidden at any moment, so it would zero
        the count of every OTHER section — the whole index."""
        body = _fn(_read(VIEWS), '_cfgFieldApplies')
        assert 'sw-field' in body and 'display' in body
        for wrong in ('offsetParent', 'getComputedStyle', 'checkVisibility'):
            assert wrong not in body, \
                f'{wrong} confuses "not applicable" with "not the section on screen"'

    def test_it_walks_every_wrapper_not_just_the_nearest(self):
        """Conditional wrappers nest — an option can be inside a group that is itself
        conditional — and stopping at the first one would count a row inside a hidden group."""
        body = _fn(_read(VIEWS), '_cfgFieldApplies')
        assert 'for (' in body or 'while' in body, 'it stopped climbing past the first wrapper'

    def test_changing_the_engine_recounts(self):
        """The select fires `updateField(...);_refreshConditionalFields(...)` in that order, so
        the refresh updateField triggers runs against the OLD visibility. Whatever depends on
        which options apply has to be recomputed by the thing that changes them."""
        body = _fn(_read(self.FIELD_RENDER), '_refreshConditionalFields')
        assert '_cfgRefreshMarks' in body, \
            'switching the database engine leaves the count one change behind'
        assert 'config-container' in body, \
            'it fires for module items too, whose panel has no index to keep in step'
