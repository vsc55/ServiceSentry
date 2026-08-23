#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A device's measurements, when there are a thousand of them.

The strip of cards was written for a machine watched by the ordinary probes: about a dozen
values, each a different KIND of thing — CPU, latency, RAM, days to expiry — where a card each
reads at a glance. Reported from the screen once SNMP was switched on: a NAS with a full
device profile files 1014 measurements, and they are not a thousand kinds. They are sixty-four
kinds measured across many rows, four SMART attributes across 176 of them being 704 cards that
all say nearly the same thing. The page became a wall you scroll past to reach the table under
it, which is itself 295 rows.

Both halves fail the same way and neither raises: everything renders, nothing is missing, and
the page is unusable. So what is guarded here is the SHAPE — that a handful of rows still
reads as cards (the machine that worked keeps working), that a large field collapses, and that
the answer to "what did this do over time" is drawn in place instead of navigating away.
"""

import os
import re

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_INFRA = (SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra')
RENDER = os.path.join(*_INFRA, '_render.html')
METRICS = os.path.join(*_INFRA, '_metrics.html')
TABS = os.path.join(*_INFRA, '_tabs.html')
LIST = os.path.join(*_INFRA, '_list.html')


def _js():
    """The device page's script, whichever partial each half lives in — the shell stays a
    shell (`test_render_shells_stay_thin`), so what this file is about is spread over three
    files and asking about one of them would be asking about where the code sits."""
    return _strip_comments(NL.join(_read(p) for p in (RENDER, TABS, METRICS)))


NL = chr(10)


class TestAThousandMeasurementsAreNotAThousandCards:

    def test_they_are_grouped_by_field_and_not_by_label(self):
        """Two modules may name a value the same thing; merging on the label would put two
        different measurements under one heading and chart one of them for both."""
        body = _fn(_js(), '_infraMetricGroups')
        assert '${m.module}|${m.field}' in body, 'grouped by something that can collide'

    def test_a_handful_of_rows_still_reads_as_cards(self):
        """NS1 resolves three DNS records and shows three cards, which is exactly right —
        collapsing them behind a heading would hide what already fitted. The threshold is a
        judgement about the PAGE and is stated once, with its reason, rather than spread
        through the conditions."""
        js = _js()
        assert 'const _INFRA_CARD_ROWS' in js, 'the judgement has no home'
        body = _fn(js, '_infraMetricsHtml')
        assert 'g.rows.length <= _INFRA_CARD_ROWS' in body
        assert 'g.rows.length > _INFRA_CARD_ROWS' in body

    def test_the_big_ones_collapse_instead_of_flooding(self):
        body = _fn(_js(), '_infraMetricsHtml')
        assert '<details' in body, 'a field of 176 rows still draws 176 of something'
        assert 'g.rows.length}</span>' in body, 'a collapsed group does not say how many'

    def test_the_biggest_blocks_come_last(self):
        """A 176-row block sitting between two things somebody wanted to read is the wall
        again, one level down."""
        body = _fn(_js(), '_infraMetricGroups')
        assert 'a.rows.length - b.rows.length' in body, 'the order is no longer by size'


class TestTheChartIsDrawnWhereTheNumberIs:
    """It used to be a link into History. That answered the question by leaving the page: you
    lost the device you were looking at to see one of its numbers over time, and came back by
    pressing Back."""

    def test_no_metric_navigates_to_the_history_section(self):
        js = _js()
        # Asked of what draws a measurement, not of the file: the gear in the header IS a
        # link out (to the registry) and is meant to be. `'/history?` with the quote is the
        # section; `/api/v1/history?` is the API that draws the series in place.
        for fn in ('_infraMetricCard', '_infraMetricRow', '_infraChartLink'):
            body = _fn(js, fn)
            assert "'/history?" not in body, f'{fn} still sends you somewhere else'
            assert 'data-nav-section' not in body, f'{fn} navigates out of the device'

    def test_it_asks_the_history_api_and_draws_in_place(self):
        body = _fn(_js(), '_infraChart')
        assert '/api/v1/history?' in body, 'it draws nothing — where would the series be?'
        assert '_historyDraw(' in body, 'a second chart renderer appeared'
        assert "getElementById('infra-chart-' + i)" in body, 'it has nowhere to draw'

    def test_a_series_that_does_not_exist_yet_says_so(self):
        """A module can be recording live values and have no history at all — that is what a
        newly added device looks like, and what a module whose rows never reached the store
        looks like. A blank box would read as a chart that failed."""
        assert 'infra_chart_empty' in _fn(_js(), '_infraChart')

    def test_closing_it_mid_load_does_not_repaint_it(self):
        """The fetch is a round trip; a click that closes the box before it lands would
        otherwise be answered by the box opening itself again."""
        body = _fn(_js(), '_infraChart')
        assert "box.dataset.open !== '1'" in body

    def test_one_range_for_the_page_and_not_one_per_chart(self):
        """Two numbers of the same device drawn over different windows is the comparison this
        would invite and could not support."""
        js = _js()
        assert 'function _infraRangePicker' in js
        assert js.count('let _infraChartHours') == 1


class TestTheResultsTableIsNotEndless:

    def test_it_is_capped_and_says_what_it_is_hiding(self):
        js = _js()
        assert 'const _INFRA_RESULTS_CAP' in js
        body = _fn(js, '_infraResultsTable')
        assert 'infra_results_more' in body, 'the rest of the rows vanish without a word'

    def test_the_worst_rows_lead_so_the_cap_hides_the_quiet_tail(self):
        """A cap over an arbitrary order hides news. Sorted worst-first it hides only the
        part somebody was never going to read."""
        body = _fn(_js(), '_infraResultsTable')
        assert 'error: 0' in body and 'warning: 1' in body


class TestTheRowOpensTheDevice:

    def test_clicking_the_line_does_what_the_button_does(self):
        js = _strip_comments(_read(LIST))
        assert 'rowAttrs:' in js and 'infraOpen(' in js
        assert 'cursor:pointer' in js

    def test_the_actions_column_still_means_the_control_you_pressed(self):
        """Without the guard the row handler fires under every button in it, so "open" would
        also happen when somebody pressed something else."""
        js = _strip_comments(_read(LIST))
        assert "event.target.closest('button,a,input,select,label')" in js


class TestWhatEachMeasurementIsCalled:
    """Reported from the screen: every card said "erebor" — on erebor's own page.

    It is the ITEM's label, and one SNMP item files a result per disk, per volume, per share,
    so the device's own name was printed a thousand times in the one place it cannot tell you
    anything. What identifies a measurement here is the row it came from.
    """

    def test_the_row_is_what_the_card_shows(self):
        js = _js()
        assert 'function _infraWhich' in js, 'nothing decides what to call a measurement'
        body = _fn(js, '_infraWhich')
        assert 'm.row' in body
        assert 'm.item' not in body, 'back to printing the device name on the device page'

    def test_a_device_wide_measurement_says_nothing_rather_than_the_module(self):
        """Putting the module there instead would be the same repetition wearing a different
        word — thirty-seven cards reading "snmp". The label under the number already says
        what the measurement is."""
        body = _fn(_js(), '_infraWhich')
        assert 'm.module' not in body

    def test_the_full_name_is_still_on_the_hover(self):
        js = _js()
        for fn in ('_infraMetricCard', '_infraMetricRow'):
            # The hover moved into `_infraWhichHtml`, which both of them draw the name
            # through — one place, so a card and a row cannot disagree about whether a disk
            # is clickable. What the guard is about is unchanged: the name is still there.
            assert '_infraWhichHtml(m)' in _fn(js, fn), f'{fn} lost the name entirely'

    def test_the_backend_works_the_row_out_and_does_not_guess(self):
        """Two sources and both are the module's own: the name it recorded (`_row`), and the
        `<item>/<detail>` key the rest of the product already speaks. Nothing here parses a
        message or infers from a field name."""
        from lib.core.hosts.service import _row_of          # noqa: PLC0415
        assert _row_of('abc/Drive_1', {'_row': 'Drive 1 (DX517-1)'}) == 'Drive 1 (DX517-1)'
        assert _row_of('abc/Drive_1', {}) == 'Drive_1'
        # `metrics` is the sampler's word for "the item itself", so it names no row.
        assert _row_of('abc/metrics', {}) == ''
        assert _row_of('abc', {}) == ''


class TestAValueIsShownAtTheSizeItIs:
    """The module records in its base unit, which is the only sane thing for a store: a value
    that changed units with its magnitude could not be charted or compared. The screen is not
    the store — "34528771842048 B" is a number nobody reads, and printing it beside
    "40289542017024 B" invites exactly the arithmetic somebody will get wrong."""

    def test_bytes_climb_in_binary_steps(self):
        body = _fn(_js(), '_fmtMeasure')
        assert '1024' in body, 'bytes scaled in thousands — not what an agent means by B'
        assert 'KiB' in body and 'TiB' in body

    def test_seconds_become_the_unit_worth_reading(self):
        body = _fn(_js(), '_fmtMeasure')
        assert "86400, 'd'" in body and "3600, 'h'" in body

    def test_only_the_display_is_scaled(self):
        """What goes to the chart has to stay in the base unit, or the axis and the number
        above it would disagree — and the series would change shape at the point a value
        crossed a power of 1024."""
        body = _fn(_js(), '_infraChart')
        assert '_fmtMeasure' not in body, 'the chart is being handed a scaled value'


class TestWhichPartOfTheDeviceAMeasurementIsOf:
    """Sixty-four kinds of measurement is not a list somebody reads; it is a list somebody
    gives up on. They are not sixty-four unrelated things either — the module already groups
    them, because a device carries PROFILES: the system, the disks, the RAID, the shares, the
    UPS plugged into it. That grouping existed at the only point it could be known, and the
    union that flattens every profile's fields into one map threw it away."""

    def test_the_profile_keeps_its_fields(self):
        from lib.core.snmp.profiles import history_fields          # noqa: PLC0415
        prof = {'id': 'synology_disks', 'label': {'es_ES': 'Discos', 'en_EN': 'Disks'},
                'metrics': [{'key': 'syno_disk_temp', 'kind': 'gauge', 'unit': 'C',
                             'chart': 'line', 'label': {'en_EN': 'Temperature'}},
                            {'key': 'syno_disk_model', 'kind': 'text'}]}
        got = history_fields(prof, 'en_EN')
        assert got['syno_disk_temp']['source'] == 'synology_disks'
        assert got['syno_disk_temp']['source_label'] == 'Disks'
        assert got['syno_disk_temp']['chart'] == 'line', 'a line and a state look the same now'
        assert 'syno_disk_model' not in got, 'a text metric is what the machine IS'

    def test_the_union_does_not_drop_it(self):
        """The projection in ``module_history_fields`` is a whitelist, which is the right
        shape — a module cannot put arbitrary keys into a core structure — but a whitelist
        that never grew is how the answer was lost at the last step."""
        from lib.modules.history_fields import _OPTIONAL_META      # noqa: PLC0415
        assert {'source', 'source_label', 'chart'} <= set(_OPTIONAL_META)

    def test_it_reaches_a_measurement(self):
        from lib.core.infra.service import metrics                 # noqa: PLC0415
        rows = [{'module': 'snmp', 'key': 'k', 'name': 'erebor', 'row': 'Drive 1',
                 'data': {'syno_disk_temp': 39}}]
        fields = {'snmp': {'syno_disk_temp': {'label': 'Temperatura', 'unit': 'C',
                                              'source': 'synology_disks',
                                              'source_label': 'Discos', 'chart': 'line'}}}
        [m] = metrics(rows, fields)
        assert m['source'] == 'synology_disks' and m['source_label'] == 'Discos'
        assert m['chart'] == 'line'

    def test_the_rail_is_alphabetical_and_not_by_size(self):
        """A rail is an index, and an index you can find things in is one whose order does
        not change as a device grows a disk. Size is what the groups INSIDE a family are
        sorted by, and that reason stops applying here: a 704-measurement family is one
        button, so its size floods nothing."""
        body = _fn(_js(), '_infraFamilies')
        assert 'localeCompare' in body
        assert 'rows.length -' not in body, 'the rail reorders itself as the device changes'

    def test_it_does_not_open_on_the_noisiest_family(self):
        body = _fn(_js(), '_infraMetricsPane')
        assert 'fams[0]' in body
        assert 'fams.length - 1' not in body, (
            'it greets somebody with the 704-attribute SMART block — the one family they '
            'were least likely to have come for')

    def test_one_family_draws_no_rail_at_all(self):
        """Everything watched by the ordinary probes has exactly one, and then the rail is a
        column of a single button beside the thing it selects."""
        body = _fn(_js(), '_infraMetricsPane')
        assert 'fams.length <= 1' in body


class TestAStateIsAWordAndNotAnInteger:
    """Reported from the screen, and confirmed by comparing against a mature panel: a device
    page read "System status 1 · Power supply status 1 · Update available 2".

    The agent answers 1 and only the MIB it came from says that 1 is Normal. The panel cannot
    know, so it printed the integer — on the screen whose whole job is to say whether the
    machine is all right.
    """

    def test_a_declared_state_is_drawn_as_a_badge(self):
        js = _js()
        assert 'function _infraState' in js, 'nothing turns a state into a word'
        body = _fn(js, '_infraState')
        assert 'm.states[String(m.value)]' in body

    def test_a_value_the_map_does_not_cover_keeps_its_number(self):
        """The profiles are filled in one MIB at a time, and not knowing is a fine thing to
        say. Inventing a word for an unmapped value would be worse than the integer."""
        body = _fn(_js(), '_infraState')
        assert 'if (!st) return null' in body

    def test_the_colour_comes_from_the_declared_level(self):
        js = _js()
        assert 'const _INFRA_LEVELS' in js
        for level in ('ok', 'warn', 'bad', 'info'):
            assert f'{level}:' in js.split('const _INFRA_LEVELS')[1][:400], level

    def test_a_state_replaces_the_number_rather_than_sitting_beside_it(self):
        """"Normal 1" is the worst of both: it looks like the badge is a label for the
        integer, which is exactly the thing that meant nothing.

        Asked of the one function that decides — the renderers stopped branching when the
        choice moved there (see TestHowAValueIsDrawnIsOneDecision)."""
        body = _fn(_js(), '_infraValueHtml')
        assert '_infraState(m) ||' in body, 'a state no longer wins over the number'

    def test_the_profiles_that_declare_states_actually_have_them(self):
        """A mechanism nothing uses is a mechanism nobody notices breaking. These are the
        MIBs whose enumerations are not in doubt; the rest keep their numbers on purpose."""
        from lib.core.snmp import profiles as P                    # noqa: PLC0415
        cat = P.catalog()
        for pid, field in (('if_generic', 'if_oper'),
                           ('synology_system', 'syno_status'),
                           ('synology_disks', 'syno_disk_health'),
                           ('synology_raid', 'syno_raid_status')):
            fields = P.history_fields(cat[pid], 'es_ES')
            assert fields[field].get('states'), f'{pid}.{field} lost its enumeration'


class TestWhatTheMachineHasBeenSaying:
    """The logs were only reachable from the modal where a device is CONFIGURED.

    That is the wrong place for them: this page is where somebody looks when a machine is
    misbehaving, and the other one is where somebody changes its community string. What a
    machine has been saying is the other half of what it has been doing.
    """

    MONITORING = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers',
                              '_monitoring.html')

    def test_it_is_a_tab_here(self):
        js = _js()
        assert "id: 'logs'" in js, 'the section still has no logs'
        assert "_loadHostLogs('infraLogsBody'" in js, 'the tab draws nothing'

    def test_it_is_the_same_panel_the_modal_draws(self):
        """Two syslog tables with two filter bars and two pagers is two places for them to
        stop agreeing — and the second one is always the one nobody updates."""
        js = _strip_comments(_read(self.MONITORING))
        assert js.count('async function _loadHostLogs') == 1, 'a second logs panel appeared'
        body = _fn(js, '_loadHostLogs')
        assert 'containerId' in body, 'it still knows which box it lives in'
        assert 'address != null' in body, 'it still reads the modal draft'

    def test_a_caller_who_may_not_read_syslog_is_not_offered_it(self):
        """A tab whose data the caller cannot fetch is a tab that opens on an error."""
        js = _js()
        assert "perm: 'syslog_view'" in js
        body = _fn(js, '_infraTabsFor')
        assert 'currentUser.permissions' in body and 'x.perm' in body

    def test_choosing_a_tab_respects_the_same_list(self):
        """Otherwise the saved choice from a wider account survives a login as a narrower one
        and the page opens on a tab that is not in its own nav."""
        body = _fn(_js(), 'setInfraTab')
        assert '_infraTabsFor()' in body, 'the setter and the nav disagree about what exists'

    def test_a_tab_with_nothing_to_count_shows_no_count(self):
        """The other three carry a number; logs are fetched a page at a time and a zero there
        would say the machine has said nothing, which is not what it means."""
        body = _fn(_js(), '_infraTabsHtml')
        assert 'counts[x.id] === undefined' in body


class TestHowAValueIsDrawnIsOneDecision:
    """A percentage, a state and a byte count are not the same kind of answer, and drawing
    all three as "a number with a word after it" is what made a device page read as a wall.

    The order is by how much is KNOWN about the value: an enumeration the profile explained,
    then a percentage — whose scale needs no explaining — then a number with whatever unit it
    came with.
    """

    def test_the_choice_lives_in_one_place(self):
        """It was three conditions across two renderers, which is how a card and a row of the
        same value start looking like different things."""
        js = _js()
        assert 'function _infraValueHtml' in js
        for fn in ('_infraMetricCard', '_infraMetricRow'):
            body = _fn(js, fn)
            assert '_infraValueHtml(m)' in body, f'{fn} decides for itself again'
            assert '_infraState(' not in body, f'{fn} still branches on its own'

    def test_a_percentage_is_drawn_as_a_length(self):
        """It is the one measurement whose scale is known without asking — 0 to 100 — so 13
        and 97 can be drawn as what they are instead of read as two numbers of similar
        length. Nothing else here has that property: 39 °C means something only against what
        the disk is rated for, and the profile does not say."""
        body = _fn(_js(), '_infraBar')
        assert "m.unit !== '%'" in body, 'it draws bars for things that are not percentages'
        assert 'progress-bar' in body

    def test_the_bar_asserts_nothing_about_being_full(self):
        """Half of these are "CPU idle" and "battery capacity", where full is the good news.
        What a number MEANS is a threshold, and a threshold is a check's job — this is a
        reading."""
        body = _fn(_js(), '_infraBar')
        for danger in ('text-bg-danger', 'bg-danger', 'bg-warning'):
            assert danger not in body, 'the bar is judging the value'

    def test_a_value_outside_the_range_does_not_escape_its_box(self):
        body = _fn(_js(), '_infraBar')
        assert 'Math.max(0, Math.min(100' in body

    def test_the_sparkline_is_absent_on_purpose_and_says_why(self):
        """Not a rendering problem: drawing eighty of them means eighty requests, because the
        history API answers one series per call. A batched endpoint has to come first, and
        inventing one under a card renderer is how a screen ends up hammering a database."""
        src = _read(METRICS)
        assert 'batched endpoint' in src, (
            'the reason the small graphs are missing is no longer written down, so the next '
            'person adds them one fetch at a time')


class TestIdentityIsContextAndNotASection:
    """It was a tab, and a tab is read once and then unreachable — which is the opposite of
    what a serial number and a firmware version are for. They are the context of everything
    else on the page: you read them WHILE looking at the measurements, to answer "is this the
    box with the problem".

    Compared against a mature panel (Observium) that keeps them in a column down the side, and
    it is right about this one.
    """

    CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')

    def test_it_is_no_longer_a_tab(self):
        js = _js()
        assert "id: 'info'" not in js, 'the identity is a tab again'
        assert 'ss-sticky-aside' in js, 'and it is not a column either — it is nowhere'

    def test_the_column_stays_put_while_the_rest_scrolls(self):
        css = _read(self.CSS)
        rule = css.split('.ss-sticky-aside {')[1].split('}')[0]
        assert 'position: sticky' in rule
        assert 'align-self: flex-start' in rule, 'a sticky child stretched to full height'

    def test_it_is_not_a_second_scroll_region(self):
        """A scrollbar inside a page that already scrolls is how a column ends up with its
        head off the screen. This one is short by construction."""
        css = _read(self.CSS)
        rule = css.split('.ss-sticky-aside {')[1].split('}')[0]
        assert 'overflow' not in rule

    def test_it_stops_sticking_on_a_narrow_screen(self):
        """A sticky column 17rem wide on a phone is the page."""
        css = _read(self.CSS)
        assert '.ss-sticky-aside { flex: 0 0 auto' in css.replace('\n', ' ').replace('    ', ' ')

    def test_it_is_a_reusable_class_and_not_a_rule_about_this_page(self):
        """The convention: layout behaviour is a generic class, so the next panel that wants a
        column of context is markup and no new rule. A `#infra…` selector carrying the width
        and the stickiness would be one page's private layout with nothing to reuse.

        Asked of the stylesheet's RULES and not its prose — a comment naming an id is a
        comment explaining one, and `#infraSubTabs` (which hides a nav the sidebar drives) is
        neither this layout nor new."""
        rules = re.sub(r'/\*.*?\*/', '', _read(self.CSS), flags=re.S)
        for sel in re.findall(r'([^{}]+)\{[^}]*(?:sticky|flex: 0 0 17rem)[^}]*\}', rules):
            assert '#' not in sel or 'ss-sticky-aside' not in sel, (
                f'the aside is styled through an id: {sel.strip()[:60]}')
        # Two: the rule and its override below the breakpoint. Anything more is a third
        # opinion about the same column.
        assert rules.count('.ss-sticky-aside {') == 2, 'defined more than twice, or not at all'

    def test_the_tabs_left_are_the_ones_about_what_it_DOES(self):
        js = _js()
        block = js.split('const _INFRA_TABS')[1].split('];')[0]
        for tid in ('metrics', 'results', 'logs'):
            assert f"id: '{tid}'" in block, tid


class TestTheIdentityColumnIsAnIdentityAndNotAnInventory:
    """Reported from the screen: the column ran for pages.

    One SNMP item files a result per disk, per volume, per share, and every one of them
    carries a model, a serial and a bay. Two hundred blocks is not an identity — it is an
    inventory, and it belongs beside the rows it describes rather than in the column that
    answers "what is this box".
    """

    def test_only_the_devices_own_facts_are_in_it(self):
        body = _fn(_js(), '_infraIdentityHtml')
        assert 'attrs.filter(a => !a.row)' in body, 'every row is back in the column'

    def test_they_are_still_grouped_by_what_answered_them(self):
        """"The UPS says its model is X" is a different statement from "the NAS says its
        model is X", and merged they read as one machine contradicting itself."""
        body = _fn(_js(), '_infraIdentityHtml')
        assert 'a.source' in body and 'groups' in body


class TestTheFamilyRailDoesNotFightThePage:
    """Reported from the screen: opening some families sent the tab strip to the bottom of
    the document.

    `.ss-railbox` is a rail with its own scroll, and the stylesheet turns the body around one
    into a flex column with `overflow: hidden`. That is right when the rail IS the page and
    wrong once the device page scrolls behind a sticky identity column: the page stopped
    being able to scroll and its content went looking for somewhere to go.
    """

    def test_the_family_rail_is_a_sticky_column_and_not_a_railbox(self):
        body = _fn(_js(), '_infraMetricsPane')
        assert 'ss-railbox' not in body, 'it is fighting the page scroll again'
        assert 'ss-sticky-aside' in body, 'the same column the identity uses'

    def test_the_button_drops_the_mib_and_the_hover_keeps_it(self):
        """A profile is titled "Synology — disks (SYNOLOGY-DISK-MIB)" and that parenthesis is
        the right half of the title where you CHOOSE a profile. In a 17rem column it is two
        thirds of the width spent on the half nobody is choosing by."""
        js = _js()
        assert 'function _infraShortLabel' in js
        body = _fn(js, '_infraMetricsPane')
        assert '_infraShortLabel(f.label)' in body
        assert 'title="${escAttr(f.label)}"' in body, 'the full title is gone, not moved'


class TestAPanelThatNeedsRoomAsksForIt:
    """Reported from the screen: the log table showed its column titles and nothing else.

    `.ss-vfill` is the right mechanism when there IS a height to hand down. A tab inside a
    scrolling document has none, so a panel that asked to fill drew at the height of its own
    header.
    """

    CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')

    def test_the_logs_panel_carries_the_class(self):
        assert 'ss-pane-tall' in _fn(_js(), '_infraTabsHtml')

    def test_it_is_a_floor_and_not_a_cap(self):
        """A cap would trade one broken shape for another: a device with four hundred lines
        of syslog would scroll inside a box inside a page that also scrolls."""
        css = _read(self.CSS)
        rule = css.split('.ss-pane-tall {')[1].split('}')[0]
        assert 'min-height' in rule and 'max-height' not in rule


class TestTheOpenDeviceSurvivesAReload:
    """Reported from the screen: F5 inside a device answered by going back to the list of
    forty.

    A section that answers "which machine is in trouble" is one somebody keeps open, refreshes
    and sends to a colleague, and the device it was showing lived only in a variable. Same
    shape the History section already uses for a series (`/history?module=&key=`).
    """

    def test_the_open_device_is_in_the_url(self):
        js = _js()
        assert 'function _infraSyncUrl' in js
        body = _fn(js, 'infraOpen')
        assert '_infraSyncUrl()' in body, 'opening a device leaves the URL behind'

    def test_going_back_to_the_fleet_takes_it_out(self):
        body = _fn(_js(), '_infraSyncUrl')
        assert 'searchParams.delete' in body, 'a link to the fleet reopens the last device'

    def test_it_replaces_rather_than_stacks(self):
        """An entry per device would make Back walk the machines you looked at instead of
        leaving the section — and Back would then have to re-render the page it restored,
        which is a second navigation mechanism beside the sidebar's."""
        body = _fn(_js(), '_infraSyncUrl')
        assert 'replaceState' in body and 'pushState' not in body

    def test_the_url_is_read_once_and_not_on_every_render(self):
        """Re-reading it would reopen a device somebody had just closed: the auto-refresh
        re-renders this section on a timer."""
        js = _js()
        assert 'let _infraUrlRead' in js
        body = _fn(js, 'renderInfra')
        assert '!_infraUrlRead' in body

    def test_a_link_to_a_device_that_no_longer_exists_falls_back_to_the_fleet(self):
        """A uid can be deleted between one person sending the link and another opening it.
        Checked against the fleet that was just fetched, rather than asked for and answered
        with a spinner that never resolves."""
        body = _fn(_js(), 'renderInfra')
        assert '_infraHosts.some(h => h.uid === want)' in body


class TestRowsThatBelongToDifferentPartsAreSeparated:
    """Eight disks in two enclosures sort into each other and read as one shelf of eight: the
    device names them "Drive 1" and "Drive 1 (DX517-1)", so alphabetically they interleave.

    Which part a row belongs to is worked out SERVER-side from a pattern the profile declares
    — once per measurement instead of on every repaint, and what reaches the screen is data
    rather than a rule.
    """

    def test_the_rows_of_a_group_are_split_by_the_part_they_belong_to(self):
        js = _js()
        assert 'function _infraGroupRows' in js
        body = _fn(js, '_infraMetricsHtml')
        assert '_infraGroupRows(g.rows, idx)' in body, 'a group draws its rows flat again'

    def test_nothing_splits_means_no_headings_at_all(self):
        """Which is every table that names its rows plainly. A heading over the only group
        there is says nothing and costs a line."""
        body = _fn(_js(), '_infraGroupRows')
        assert 'by.size <= 1' in body

    def test_the_unqualified_rows_come_first(self):
        """A disk in the box itself is "Drive 1"; the enclosures hang off it rather than the
        other way round."""
        body = _fn(_js(), '_infraGroupRows')
        assert "a[0] === ''" in body

    def test_the_screen_does_not_parse_the_name_itself(self):
        """The pattern is a statement about how one vendor names things and belongs in that
        vendor's profile. A regex here would be the core assuming something about brackets —
        and running it on every repaint."""
        js = _js()
        assert 'row_group' in js
        for fn in ('_infraGroupRows', '_infraWhich'):
            body = _fn(js, fn)
            assert '(?P<' not in body and 'match(' not in body, f'{fn} parses the row name'


class TestNothingIsPushedOutOfItsColumn:
    """Three misalignments reported from one screenshot, and all three are the same flexbox
    rule: **a flex child's automatic minimum size is its CONTENT**, so anything whose content
    is wider than the space it was given pushes instead of shrinking.

    A row of measurement cards did it to the family rail (the cards wrapped onto the line
    below instead of sitting beside it); a long profile name did it to the rail itself (one
    item stuck out past its neighbours, and the selected one then drew to a different edge).
    """

    CSS = os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css')

    def test_the_body_beside_a_column_can_shrink(self):
        for fn, src in (('_infraMetricsPane', _js()), ('_infraHostHtml', _js())):
            body = _fn(src, fn)
            assert 'min-width:0' in body, (
                f'{fn} gives its main column a floor of its own content, so a wide row of '
                f'cards wraps the whole thing onto the next line')

    def test_a_rail_item_can_shrink_and_its_label_can_truncate(self):
        """`.text-truncate` is overflow+ellipsis and nothing else: without being allowed to
        shrink, the label never reaches the width where it would ellipsise."""
        css = _read(self.CSS)
        item = css.split('.ss-rail-item {')[1].split('}')[0]
        assert 'min-width: 0' in item
        assert '.ss-rail-item > .text-truncate { min-width: 0; }' in css

    def test_the_record_block_has_a_heading_of_its_own(self):
        """It was titled with the gear button's tooltip — "Open in the registry" over a list
        of facts, which reads as an instruction and is not one."""
        body = _fn(_js(), '_infraIdentityHtml')
        assert "t('infra_record')" in body
        assert "t('infra_registry')" not in body, 'the heading is a tooltip again'


class TestAPanelFillsWhatIsActuallyLeft:
    """Reported twice from the screen: first the log table drew at the height of its own
    header, then — with a `min-height` in the stylesheet — it stopped short of the bottom.

    Both are the same thing seen from two sides. The fill chain (`.ss-vfill`) is the mechanism
    when there IS a height to hand down, and a tab inside a scrolling document has none. A
    fixed viewport fraction is the other half: 60vh is right for one screen and a hole in the
    next, because the stylesheet cannot know where on the page the panel starts.
    """

    UTILS = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core',
                         '_utils.html')

    def test_the_height_is_measured_and_not_assumed(self):
        js = _strip_comments(_read(self.UTILS))
        assert 'function fitToViewportBottom' in js
        body = _fn(js, 'fitToViewportBottom')
        assert 'getBoundingClientRect().top' in body and 'window.innerHeight' in body

    def test_it_is_a_floor_and_never_a_cap(self):
        """Content past it grows the page, which is what a page that scrolls is for."""
        body = _fn(_strip_comments(_read(self.UTILS)), 'fitToViewportBottom')
        assert 'minHeight' in body and 'maxHeight' not in body

    def test_a_short_window_does_not_get_a_two_row_panel(self):
        body = _fn(_strip_comments(_read(self.UTILS)), 'fitToViewportBottom')
        assert 'Math.max(240' in body

    def test_it_re_measures_on_resize_and_lets_go(self):
        """A section is re-rendered on a timer, and a listener per render is a page that gets
        slower the longer somebody leaves it open."""
        body = _fn(_strip_comments(_read(self.UTILS)), 'fitToViewportBottom')
        assert "addEventListener('resize'" in body
        assert "removeEventListener('resize'" in body
        assert 'el.isConnected' in body, 'nothing ever tells the listener the panel is gone'

    def test_the_logs_pane_uses_it(self):
        body = _fn(_js(), '_infraTabsHtml')
        assert 'fitToViewportBottom(' in body
        assert 'ss-pane-tall' in body, (
            'the stylesheet floor is what it draws at until the measurement runs; without it '
            'the panel flashes at the height of its own header on every open')


class TestARowsOwnFacts:
    """A disk's model and serial, a SMART attribute's status.

    They were being recorded and shown nowhere. The identity column draws the DEVICE's facts
    — it has to, or one registry entry fronting a NAS and the UPS plugged into it reads as one
    machine with contradictory serials — and when it stopped drawing row-level ones, the
    disks' serials went with them. A serial nobody can read from the panel is a serial
    somebody reads off the machine with a torch.
    """

    def _src(self) -> str:
        return _read(METRICS)

    def test_they_are_matched_on_the_unsplit_name(self):
        """The attributes were recorded against the name the DEVICE composed ("Drive 1 /
        Raw Read Error Rate"); the split into row and group is the screen's doing. Matching on
        the split half finds nothing, silently — every row would simply show no facts."""
        body = self._src().split('function _infraFactsOf')[1].split(chr(10) + '}')[0]
        assert 'm.row_key' in body
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        assert "'row_key':" in svc, 'the unsplit name never leaves the server'

    def test_the_device_s_own_facts_are_not_repeated_on_every_row(self):
        """176 SMART rows each captioned "model: DS916+" is not information, it is wallpaper —
        and it is the identity column's job, one screen element away."""
        body = self._src().split('function _infraIndexRowFacts')[1].split(chr(10) + '}')[0]
        assert 'if (!a.row) continue;' in body

    def test_they_are_indexed_once_and_not_searched_per_row(self):
        """A Synology answers 176 SMART rows. A linear scan of the attribute list for each of
        them is the repaint nobody can explain afterwards."""
        src = self._src()
        assert 'new Map()' in src.split('function _infraIndexRowFacts')[1].split(chr(10) + '}')[0]
        tabs = _read(TABS)
        assert '_infraIndexRowFacts(attrs);' in tabs, 'the index is never built'

    def test_a_row_with_no_facts_draws_nothing(self):
        body = self._src().split('function _infraFactsHtml')[1].split(chr(10) + '}')[0]
        assert "if (!facts.length) return '';" in body

    def test_the_smart_table_says_which_half_of_a_row_name_is_the_disk(self):
        """`index_label` names two columns and the sampler joins them with " / ", so every
        SMART row is "<disk> / <attribute>". Without the split they sort by attribute name
        across every bay — eighty rows in which one disk's story is never together."""
        import json
        path = os.path.join(SRC, 'lib', 'core', 'snmp', 'profiles', 'sources',
                            'synology_smart.json')
        prof = json.loads(_read(path))
        pattern = prof.get('row_split') or ''
        assert pattern, 'the SMART table does not say how its row names are composed'
        m = re.match(pattern, 'Drive 1 / Raw Read Error Rate')
        assert m and m.group('group') == 'Drive 1'
        assert m.group('row') == 'Raw Read Error Rate'


class TestAPileIsNotAnIdentity:
    """The heading over facts whose source was not recorded.

    A sample written before the source was kept holds a NAS's facts and those of the UPS
    plugged into it in one dict, with no way left to tell which said what — that is exactly
    how a UPS's model came to be read as the NAS's. The nested shape fixed the recording;
    what it cannot fix is a sample already on disk. Presenting that pile under "Identity" is
    the panel asserting the one thing it demonstrably does not know.
    """

    def _fn(self) -> str:
        src = _read(TABS)
        return src[src.index('function _infraIdentityHtml'):]

    def test_the_unsourced_pile_is_not_called_the_identity(self):
        body = self._fn()
        assert "t('infra_identity_unsourced')" in body
        assert "|| t('infra_identity')" not in body, (
            'unattributed facts are still presented as this machine`s identity')

    def test_a_source_that_is_known_is_still_the_heading(self):
        """"The UPS says its model is X" is a different statement from "the NAS says its
        model is X", and the heading is what keeps them different."""
        body = self._fn()
        assert 'g.short ||' in body, (
            'the card ignores the name the profile gives the thing it describes')
        assert '_infraShortLabel(g.label || g.source)' in body, (
            'a profile that names nothing has no heading at all')

    def test_the_heading_is_the_name_and_not_the_id(self):
        """The ids were printed raw ("synology_ups") beside values that were translated —
        the panel showing its own filing system to somebody who asked what the machine is."""
        body = self._fn()
        assert 'g.label || g.source' in body, 'the heading is still the raw source id'
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        assert "'source_label':" in svc, 'the name never leaves the server'

    def test_the_browser_does_not_re_sort_them(self):
        """The server ordered them (standards before a vendor's own MIB) with the profile's
        own claim to go on. A second sort here would be an opinion with less behind it."""
        body = self._fn()
        assert '.sort(' not in body.split('const groups')[1].split('return `')[0]

    def test_it_is_dropped_when_anything_is_sourced(self):
        """Reported from the screen: the pile sat above the three correct cards, and every
        fact in it was already in one of them, attributed. A device that has answered once
        with sources has answered with all of them — so beside them the pile is not a
        fallback, it is a stale duplicate that contradicts them ("Modelo: Linux erebor…"
        over "Modelo: DS916+"). Obsolete and wrong, which is the worst pair."""
        assert "if (groups.size > 1) groups.delete('');" in self._fn()

    def test_it_survives_when_it_is_all_there_is(self):
        """A module that records attributes without naming what answered is not stale — it is
        a module with one answerer. Dropping it there would hide the only facts it has."""
        body = self._fn()
        assert 'groups.size > 1' in body, (
            'the pile is dropped unconditionally, taking a single-source module`s facts with it')

    def test_the_device_s_own_facts_are_the_only_ones_here(self):
        """One SNMP item files a result per disk, per volume, per share, each carrying a model
        and a serial. Two hundred blocks is not an identity, it is an inventory — and the rows`
        facts belong beside their rows (see TestARowsOwnFacts)."""
        assert 'attrs.filter(a => !a.row)' in self._fn()


DETAILS = os.path.join(*_INFRA, '_details.html')


class TestHowIsThisMachine:
    """The question a device page is opened with, and the Measures tab is the wrong screen
    for it: a device with a full set of profiles answers around a thousand values, and "is
    this box all right" is four or five of them.

    Which four or five is NOT decided in the panel. A NAS answers with its system status and
    its temperature; a switch's headline is throughput; a UPS's is its battery. A core that
    picked them by field name would be a core that knows what a NAS is, and would have nothing
    to say about the next kind of device somebody plugs in.
    """

    def _src(self) -> str:
        return _read(DETAILS)

    def test_the_tab_exists_and_leads(self):
        tabs = _read(TABS)
        assert "{id: 'details'" in tabs
        assert tabs.index("{id: 'details'") < tabs.index("{id: 'metrics'"), (
            'the summary is behind the thousand values it summarises')

    def test_it_is_where_a_device_opens(self):
        """Remembered per user like the others, but the DEFAULT is this one: somebody who has
        never chosen wants the answer, not the archive."""
        tabs = _read(TABS)
        assert tabs.count("'metrics';") == 0, 'metrics is still the fallback tab'
        assert "? _infraTab : 'details'" in tabs

    def test_the_profile_decides_what_is_shown(self):
        body = self._src()
        assert 'm.headline' in body, 'the pane picks its own values'
        for word in ('cpu', 'mem_', 'syno_', 'fs_used'):
            assert word not in body, (
                f'the panel names a module`s field ({word}) — it would know what a NAS is and '
                'nothing about the next kind of device')

    def test_a_device_that_flags_nothing_is_told_so(self):
        """An empty box reads as a broken screen. A sentence reads as an answer."""
        assert "t('infra_no_headline')" in self._src()

    def test_a_value_is_drawn_by_the_one_renderer(self):
        """A state is a badge with the word the MIB gives it, a byte count is scaled, a
        percentage gets its bar. Two renderers for one value is two answers to "what does 2
        mean", and the one on the summary screen would be the one that stayed wrong.

        The ring composes its two figures itself ("8 GiB / 10 GiB" is one sentence, not two
        values) — but from the SHARED formatter. What must not appear is a second answer to
        how big a gibibyte is.
        """
        body = self._src()
        assert '_infraValueHtml(m)' in body, 'a value on its own is formatted here'
        for word in ('1024', "'GiB'", "'MB'", 'toFixed(1)', 'Math.log'):
            assert word not in body, f'the summary re-derives units ({word})'

    def test_a_store_is_drawn_as_a_proportion(self):
        """HOST-RESOURCES-MIB reports every store the same way — physical memory, cached,
        swap, and every mounted volume — as a size and an amount used. Two byte counts side by
        side is arithmetic left to the reader when the answer they want is "83 %"."""
        body = self._src()
        assert "m.headline === 'used'" in body and "m.headline === 'total'" in body
        assert '_infraDonut(' in body

    def test_which_half_is_which_is_the_profiles_word(self):
        """A label saying "Usado" in one profile and "In use" in the next is not something to
        pattern-match on, and getting it backwards draws a full disk as an empty one."""
        prof = _read(os.path.join(SRC, 'lib', 'core', 'snmp', 'profiles', '__init__.py'))
        assert "HEADLINE_ROLES = ('used', 'total', 'free')" in prof
        body = self._src()
        for word in ('used', 'usado', 'size', 'capacidad'):
            assert f"label.toLowerCase().includes('{word}')" not in body.lower()

    def test_a_table_says_which_of_its_rows_the_summary_is_about(self):
        """Reported from the screen, and it is the difference between a summary and a dump.
        HOST-RESOURCES-MIB reports every store a host has: on a NAS running containers that is
        physical memory, swap and the buffers, then forty bind mounts of the same volume — so
        Details came out as five useful rings followed by thirty-nine that all said 67 % of the
        same 31 TiB."""
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        assert 'headline_rows' in svc and 'def _headline_of' in svc

    def test_the_rule_matches_what_the_device_said_and_not_a_path(self):
        """A volume is `/volume1` on one machine and `C:` on the next. A panel matching on
        paths is a panel that knows what Linux is."""
        import json                                            # noqa: PLC0415
        prof = json.loads(_read(os.path.join(
            SRC, 'lib', 'core', 'snmp', 'profiles', 'sources', 'hr_storage.json')))
        rule = prof.get('headline_rows') or {}
        assert rule.get('role') == 'kind', 'the rule does not read hrStorageType'
        assert all(v.startswith('1.3.6.1.2.1.25.2.1.') for v in rule.get('any') or ()), rule
        assert '1.3.6.1.2.1.25.2.1.4' not in (rule.get('any') or ()), (
            'hrStorageFixedDisk is back on the summary — every bind mount with it')

    def test_the_real_volumes_come_from_the_profile_that_knows_them(self):
        """HOST-RESOURCES cannot tell a volume from a bind mount of it; SYNOLOGY-RAID-MIB
        lists the volumes and nothing else, with the space free and the space total."""
        import json                                            # noqa: PLC0415
        prof = json.loads(_read(os.path.join(
            SRC, 'lib', 'core', 'snmp', 'profiles', 'sources', 'synology_raid.json')))
        flagged = {m['key']: m['headline'] for m in prof['metrics'] if m.get('headline')}
        assert flagged == {'syno_raid_free': 'free', 'syno_raid_total': 'total'}, flagged

    def test_a_table_that_reports_free_is_still_a_proportion(self):
        """One table gives the amount USED and the other the space FREE. Both answer "how full
        is it", and neither is worth a second renderer."""
        body = _fn(self._src(), '_infraDonut')
        assert "headline: 'used'" in body and 'cap - fr' in body

    def test_the_translator_is_not_shadowed(self):
        """`t` is the panel's translator. A local `t` inside a function that also needs a word
        is a TypeError on the one branch that has a word in it — which is the branch that only
        runs for a device reporting free space."""
        body = _fn(self._src(), '_infraDonut')
        assert 'const t =' not in body and 't = Number(' not in body

    def test_no_capacity_is_not_zero_per_cent(self):
        """An unmounted store and a full one are different things, and dividing by zero says
        the second."""
        body = _fn(self._src(), '_infraDonut')
        assert 'cap <= 0' in body

    def test_nothing_is_coloured_by_a_threshold_nobody_gave(self):
        """What counts as "too full" is a decision about the installation, and the panel has
        not been given one — the same reason the percentage bar beside it is grey. Turning a
        ring amber at 80 % would be the screen deciding that on its own authority."""
        body = _fn(self._src(), '_infraDonut')
        for word in ('danger', 'warning', 'text-bg-', '> 80', '>= 90'):
            assert word not in body, f'the ring invents a threshold ({word})'

    def test_memory_and_volumes_are_not_one_list(self):
        """Reported from the screen: the stores came out as one run of cards with nothing
        between them, and "31 TiB" beside "8 GiB" reads as one list of the same kind of thing.
        The heading is the SOURCE's own name, so a device that adds a fourth kind of store
        gets a fourth section without the panel learning about it."""
        body = _fn(self._src(), '_infraDetailsPane')
        assert 'sections' in body and 'source_short' in body
        assert 'source_rank' in body, 'the sections are not in the reading order'

    def test_a_table_may_name_its_rows_by_pattern(self):
        """SYNOLOGY-RAID-MIB lists a storage pool and the volumes carved out of it in one
        table and answers nothing that tells them apart — "Storage Pool 1" and "volume1"
        differ by name and by nothing else. The pattern is the vendor profile's, next to the
        OIDs it is about; the core applies it and knows nothing about pools."""
        import json                                            # noqa: PLC0415
        prof = json.loads(_read(os.path.join(
            SRC, 'lib', 'core', 'snmp', 'profiles', 'sources', 'synology_raid.json')))
        pat = (prof.get('headline_rows') or {}).get('row_matches') or ''
        assert pat, 'the volume table does not say which of its rows are volumes'
        assert re.search(pat, 'volume1') and not re.search(pat, 'Storage Pool 1')

    def test_the_disks_report_their_health(self):
        import json                                            # noqa: PLC0415
        prof = json.loads(_read(os.path.join(
            SRC, 'lib', 'core', 'snmp', 'profiles', 'sources', 'synology_disks.json')))
        assert any(m.get('headline') for m in prof['metrics'] if m['key'] == 'syno_disk_health')

class TestOneRowsWholeStory:
    """Clicking a disk shows its SMART.

    A row is a name the equipment chose, and several profiles can be about the same one: a
    disk is a row of SYNOLOGY-DISK-MIB — its model, its temperature, its health — AND the group
    that eighty rows of SYNOLOGY-SMART-MIB belong to. No summary can hold eighty attributes per
    disk, and "click the disk" is where a person looks for them.
    """

    def _src(self) -> str:
        return _read(DETAILS)

    def test_a_row_gathers_what_every_profile_said_about_it(self):
        body = _fn(self._src(), '_infraRowDetail')
        assert 'm.row_key === name' in body and 'm.row_group === name' in body, (
            'a disk finds only half its story — the SMART rows group under it, they are not it')

    def test_a_row_is_identified_by_the_name_the_device_composed(self):
        """Reported from the screen: a disk's dialog showed every reading twice, at two
        different temperatures. A Synology with an expansion unit has a "Drive 3" in the box
        and a "Drive 3 (DX517-1)" in the shelf, and the profile's split exists precisely so
        those are not one row — so looking them up by the SPLIT name puts them back together,
        which is the bug the split was written to fix."""
        body = _fn(self._src(), '_infraRowDetail')
        assert 'm.row === name' not in body, 'rows are matched by their split half again'
        facts = _fn(self._src(), '_infraRowFactsHtml')
        assert 'a.row === key' in facts, '"Drive 3" would match "Drive 30" again'

    def test_a_row_with_nothing_more_does_not_pretend_to_open(self):
        """A chevron on a row that opens onto the two numbers already in front of you is a
        promise the dialog does not keep."""
        assert '_infraRowDetailCount' in self._src()
        body = _fn(self._src(), '_infraRowDetailCount')
        assert '!m.headline' in body

    def test_the_dialog_does_not_repeat_the_row_in_every_line(self):
        """It is titled with the disk. Repeating it ninety times is the one word on the screen
        that carries no information."""
        body = _fn(self._src(), '_infraRowWhich')
        assert 'm.row_key !== key' in body

    def test_two_tables_of_one_device_may_name_it_differently(self):
        """Reported from the screen: clicking a disk showed its six readings and none of its
        eighty SMART attributes. SYNOLOGY-DISK-MIB names a disk by `diskName` ("Drive 1") and
        files its `diskID` ("Disk 1") beside it; SYNOLOGY-SMART-MIB names its rows by a column
        of its own — and nothing says the two agree."""
        body = self._src()
        assert '_infraIndexRowAliases' in body
        assert '_infraRowAlias.get(m.row_group)' in _fn(body, '_infraRowDetail')

    def test_an_alias_is_what_the_device_said_and_not_a_rule_about_names(self):
        """Stripping a prefix or lowercasing would be the panel inventing a naming convention
        for equipment it has never seen. The aliases are the identity facts the device
        reported, and only the ones that NAME a row — a model or a kind is shared by every
        disk in the box."""
        body = _fn(self._src(), '_infraIndexRowAliases')
        assert '_INFRA_ID_ROLES' in body
        for word in ('toLowerCase', 'replace(', 'startsWith', 'slice('):
            assert word not in body, f'the aliases are guessed rather than read ({word})'
        roles = self._src().split('_INFRA_ID_ROLES = new Set(')[1].split(')')[0]
        for shared in ("'model'", "'kind'", "'vendor'", "'role'"):
            assert shared not in roles, f'{shared} is shared by every row — it names nothing'

    def test_the_join_is_the_devices_own_number_and_not_a_convention(self):
        """The two tables name a disk differently — "Drive 1" and "sda" — and the letters look
        like a rule: sda is the first disk, sdb the second. They are not a rule, they are
        DISCOVERY ORDER, so an empty bay shifts every letter after it and the panel would show
        the wrong disk's SMART on exactly the day somebody is reading SMART.

        SYNOLOGY-SMART-MIB reports the serial of the disk each of its rows belongs to
        (`diskSMARTSerialNumber`), and so does the disk table. Same physical object, same
        number, nothing assumed.
        """
        import json                                            # noqa: PLC0415
        prof = json.loads(_read(os.path.join(
            SRC, 'lib', 'core', 'snmp', 'profiles', 'sources', 'synology_smart.json')))
        serial = [m for m in prof['metrics'] if m.get('role') == 'serial']
        assert serial, 'the SMART table no longer carries the disk it belongs to'
        assert serial[0]['walk'] == '1.3.6.1.4.1.6574.5.1.1.11'
        body = _fn(self._src(), '_infraIndexRowAliases')
        assert 'nestedOf' in body and 'owners.size === 1' in body
        # The code, not the prose: the comments name "sda" because that is what the screen
        # showed. What must not exist is letter arithmetic.
        for word in ('charCodeAt', 'fromCharCode', "'sd'", '.charAt('):
            assert word not in body, f'a device-letter convention crept in ({word})'

    def test_an_ambiguous_alias_is_not_used(self):
        """With an expansion unit the shelf disk's split name is "Drive 3", which is the
        internal disk's WHOLE name: one claimant, and completely the wrong disk. A name that
        already belongs to a row is never a nickname for another."""
        body = _fn(self._src(), '_infraIndexRowAliases')
        assert 'keys.size === 1' in body and '!rowKeys.has(alias)' in body

    def test_a_smart_table_is_read_across_and_not_down(self):
        """An attribute is a name and four numbers — current, worst, threshold, raw — and "is
        the current value near the threshold" is the whole question. It cannot be asked of four
        separate lines saying "Reallocated Sector Count — Valor actual"."""
        body = _fn(self._src(), '_infraNestedTable')
        assert 'cols.map' in body and '<th' in body
        assert 'x.field === c.field' in body, 'the columns are not the fields'

    def test_the_columns_are_whatever_came_back(self):
        """A table with three readings per row and one with six work the same. A fixed list of
        SMART column names here would be the panel knowing what SMART is."""
        body = _fn(self._src(), '_infraNestedTable')
        for word in ('current', 'worst', 'threshold', 'syno_smart'):
            assert word not in body, f'the dialog names a SMART field ({word})'

    def test_the_two_panes_are_the_row_and_what_hangs_off_it(self):
        body = _fn(self._src(), '_infraOpenRow')
        assert 'm.row_key === key' in body and 'm.row_key !== key' in body
        assert 'data-bs-toggle="tab"' in body, 'one list of ninety rows again'

    def test_a_row_with_nothing_nested_gets_no_tabs(self):
        """A tab strip over a single pane is furniture."""
        body = _fn(self._src(), '_infraOpenRow')
        assert 'nested.length' in body and ': facts + _infraRowList' in body

    def test_it_leads_with_what_the_row_IS(self):
        """A disk's model and serial before its numbers — that is the half of the dialog
        somebody opened it for when the question is "which disk do I take out"."""
        assert '_infraRowFactsHtml' in self._src()


class TestEverythingTheDeviceAnswered:
    """The tab with no opinion.

    Every other tab is one: Details picks the handful that answer "is this box all right",
    Measures groups by profile and hides the quiet tail behind a button, the row dialog gathers
    one disk's story. Opinions are what make a screen readable — and they are also what makes
    "is the panel even receiving that OID" unanswerable, because each of them can drop a value
    for a reason that looked sensible when it was written.
    """

    def _src(self) -> str:
        return _read(os.path.join(*_INFRA, '_raw.html'))

    def test_the_tab_is_last_and_is_never_the_default(self):
        """A thousand undifferentiated lines is the right answer to a question nobody has
        asked yet."""
        tabs = _read(TABS)
        assert "{id: 'raw'" in tabs
        assert tabs.index("{id: 'raw'") > tabs.index("{id: 'logs'")
        assert "? _infraTab : 'details'" in tabs

    def test_it_shows_the_number_and_not_the_rendering(self):
        """Everywhere else a state is the word the MIB gives it and a byte count is scaled —
        which is right, and is exactly what you cannot check against the device with."""
        body = self._src()
        assert '_fmtNum(m.value)' in body
        for word in ('_infraValueHtml', '_infraState', '_fmtMeasure'):
            assert word not in body, f'the raw tab renders instead of reporting ({word})'

    def test_it_names_the_coordinates_of_every_reading(self):
        """Which profile, which row, which field, which check. Without those, a wrong number
        is just a wrong number and there is nothing to go and look at."""
        body = self._src()
        for word in ('m.source', 'm.field', 'm.module', 'm.row'):
            assert word in body, f'a reading arrives with no {word}'

    def test_the_row_is_the_one_the_device_composed(self):
        """Split into row and group everywhere else. Here they go back together, because two
        disks called "Drive 3" are two rows and this is the tab that has to show that."""
        assert 'm.row_group ?' in self._src()

    def test_filtering_does_not_repaint_the_table(self):
        """A repaint per keystroke on a thousand-row table is the panel freezing while
        somebody types."""
        body = _fn(self._src(), '_infraRawFilter')
        assert 'classList.toggle' in body
        assert 'innerHTML' not in body


class TestHowIsThisMachineStill:

    def _src(self) -> str:
        return _read(DETAILS)

    def test_the_rows_do_not_reshuffle(self):
        """The device's own index is gone by the time this is drawn — the payload is sorted by
        module and label — and a list that reorders between refreshes is one nobody can read
        twice."""
        assert '.sort(' in _fn(self._src(), '_infraDetailsPane')

    def test_a_rows_figures_stay_with_their_row(self):
        """"Used 412 GiB" is about ONE filesystem and there are usually several. Loose tiles
        would be twelve numbers with no way to tell which volume each belongs to."""
        body = self._src()
        assert 'flagged.filter(m => m.row)' in body
        assert 'm.row_group' in body, 'two disks called "Drive 1" would merge'
