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

    def test_a_rate_climbs_in_thousands(self):
        """A gigabit is 10^9 bits per second by definition — it is what is printed on the
        port, on the cable and on the invoice — so scaling it in 1024s would answer 0.93 to a
        question everybody already knows the answer to. Bytes go the other way because an
        agent reporting memory and disk means 1024, and the two rules differ for that reason
        and not by oversight. Matched on the SHAPE of the unit, so a profile that starts
        reporting frames per second reads properly without this function learning the word."""
        body = _fn(_js(), '_fmtMeasure')
        assert "unit.slice(-2) === '/s'" in body, 'a rate is printed at its base magnitude'
        assert "'k', 'M', 'G'" in body and '1000' in body

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
        assert 'm.states[m.state_key || String(m.value)]' in body, (
            'the badge reads the raw value again — a reading whose own value is not the '
            'whole answer (a port down because somebody switched it off) is drawn as '
            'whatever it would have been without the rule that excused it')

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

    def test_it_is_drawn_HERE_and_not_in_the_host_dialog_too(self):
        """The dialog is where a device is CONFIGURED; this is where it is looked at, and a
        machine misbehaving is looked at here. Two copies of one syslog table, with two filter
        bars and two pagers, is two places for them to stop agreeing — and the second is
        always the one nobody updates."""
        modal = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'servers', '_modal.html')))
        for gone in ('hmTabLogs', 'hmLogsBody', '_loadHostLogs'):
            assert gone not in modal, f'the dialog draws the logs again ({gone})'

    def test_the_refresh_tick_belongs_to_the_table(self):
        """It looked up the dialog's own tab pane and stopped when it was missing. The day
        the dialog stopped carrying logs, the first tick on the section that DOES carry them
        would have found no such pane and switched the auto-refresh off — with nothing to say
        so, because the only symptom is that rows stop being new."""
        js = _strip_comments(_read(self.MONITORING))
        tick = _fn(js, '_hostLogsApplyTimer')
        assert 'hmTabLogs' not in tick, 'the tick still looks for the dialog'
        assert "getElementById('hml-rows')" in tick, 'it is not keyed on the table'
        assert 'offsetParent' in tick, (
            'it polls for rows on a hidden tab, whichever screen they are on')

    def test_nothing_is_bound_to_a_dialog_it_cannot_be_inside(self):
        js = _strip_comments(_read(self.MONITORING))
        body = _fn(js, '_loadHostLogs')
        assert 'hostModal' not in body, 'it still unbinds from a dialog that never holds it'
        assert "containerId ? document.getElementById(containerId)" in body, (
            'it falls back to an element the dialog used to have')

    def test_its_columns_sort_and_resize_like_every_other_table(self):
        """Both asked for from the screen, and both already existed: `_thSortInner` for the
        header and `_attachColFeatures` for resize / auto-fit / reorder. The logs table was
        the one that did not use them."""
        js = _strip_comments(_read(self.MONITORING))
        draw = _fn(js, '_hostLogsDrawTable')
        assert '_thSortInner(' in draw and '_hostLogsSort' in draw
        assert 'ss-th-resizable' in draw and 'draggable="true"' in draw
        assert '_attachColFeatures(' in draw, 'a second resize implementation'

    def test_the_sort_is_the_servers_and_not_the_pages(self):
        """This table is paged server-side. Sorting the page in the browser would sort the
        fifty rows somebody happens to be looking at and call it the order of forty
        thousand."""
        js = _strip_comments(_read(self.MONITORING))
        assert 'sort: st.sort' in js and 'order: st.order' in js, (
            'the sort never reaches the request')
        fn = _fn(js, '_hostLogsSort')
        assert '_hostLogsFetch()' in fn and 'st.page = 1' in fn, (
            'sorting leaves the reader on page nine of a different order')

    def test_the_header_and_the_rows_read_one_list(self):
        """A header and a body that each decide their own column order is a table that puts
        one column's data under another's name the first time somebody drags one."""
        js = _strip_comments(_read(self.MONITORING))
        draw = _fn(js, '_hostLogsDrawTable')
        assert draw.count('_hmlOrderedCols()') == 1, 'two orders in one table'
        assert 'hml-head' in draw and 'hml-rows' in draw, (
            'the header and the rows are not drawn together')

    def test_a_stored_column_order_cannot_hide_a_column(self):
        """A preference saved by an older version names the columns of that version. Taking
        it as the whole list is how a column added since disappears for whoever had one."""
        js = _strip_comments(_read(self.MONITORING))
        fn = _fn(js, '_hmlColOrder')
        assert 'concat(' in fn and 'includes(id)' in fn

    def test_the_tab_carries_a_count_like_the_others(self):
        """Reported from the screen: every other tab says how many, and this one did not.

        It could not: the others count what is already in the device's payload and logs are
        not in it — they are rows of the syslog table. So the badge is asked for AFTER the
        section paints (~60 ms with the index behind it, on 60.000 rows) and patched in place
        when the answer lands. Re-rendering the device instead would throw away whatever tab
        somebody had just opened."""
        js = _js()
        assert 'counts.logs = _infraLogCount(' in js, 'the logs tab has no count'
        fn = _fn(js, '_infraLogCount')
        assert 'apiGet(' in fn and 'limit=1' in fn, (
            'the count is fetched with a page of rows behind it')
        assert '.then(' in fn, (
            'it is awaited, so the section waits on syslog before drawing anything')
        assert 'getElementById(' in fn and 'classList.remove' in fn, (
            'the badge is not patched in place — a re-render loses the open tab')

    def test_a_count_nobody_knows_yet_is_not_a_zero(self):
        """The trap the Jobs history badge fell into from the other side: a badge that reads
        the number it has instead of admitting it has none says "0 logs" about a machine with
        forty thousand, for as long as the request takes."""
        js = _js()
        fn = _fn(js, '_infraLogCount')
        assert 'return undefined' in fn, 'an unknown count is reported as a number'
        assert "'d-none'" in js, 'nothing hides the badge while the count is unknown'

    def test_it_is_asked_once_per_machine(self):
        """A tab switch re-renders the tabs. Asking there is a query per click for a figure
        that changed by three."""
        js = _js()
        fn = _fn(js, '_infraLogCount')
        assert 'hasOwnProperty.call(_INFRA_LOG_COUNTS' in fn, (
            'the count is re-fetched on every render')
        assert '_INFRA_LOG_COUNTS[addr] = undefined' in fn, (
            'two renders before the first answer send two requests')

    def test_a_machine_with_no_address_asks_nothing(self):
        js = _js()
        assert 'if (_addr) counts.logs' in js, (
            'a device with no address still queries syslog for it')

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

    def test_no_heading_in_that_column_is_a_tooltip(self):
        """The registry block was titled with the gear button's tooltip — "Open in the
        registry" over a list of facts, which reads as an instruction and is not one. That
        block has since gone (it repeated the header above it), and the rule it was written
        for applies to whatever heads a card there now."""
        body = _fn(_js(), '_infraIdentityHtml')
        assert "t('infra_registry')" not in body, 'a heading is a tooltip again'
        assert 'head(g)' in body, 'the cards are no longer headed by their source'


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

    def test_a_property_of_the_box_sits_beside_what_the_box_IS(self):
        """"Is there an update" is not a measurement anybody charts — it is a property of the
        machine, and it belongs next to the DSM version it is about rather than among the
        temperatures on the summary. Which values those are is the profile's word, so the panel
        never learns what an update is."""
        body = self._fn()
        assert 'm.identity && !m.row' in body
        assert '_infraValueHtml(m)' in body, (
            'the badge is drawn a second way, so a warning level could be amber in one place '
            'and not the other')
        # …and beside the FACT it is about, not as a second entry: "Actualización disponible:
        # Disponible" is the same word twice and pushes the version a line away from the thing
        # that qualifies it.
        assert 'm.identity === a.key' in body
        assert 'const loose' in body, (
            'a state whose fact the device did not answer would vanish — a value nobody shows '
            'is a value that might as well not be sampled')
        import json                                            # noqa: PLC0415
        prof = json.loads(_read(os.path.join(
            SRC, 'lib', 'core', 'snmp', 'profiles', 'sources', 'synology_system.json')))
        up = [m for m in prof['metrics'] if m['key'] == 'syno_upgrade'][0]
        assert up.get('identity') == 'firmware', 'it no longer says which fact it is about'
        assert not up.get('headline'), 'it is on the summary as well as beside the firmware'

    def test_it_is_the_profile_that_says_so_and_not_the_panel(self):
        """A core that put "update available" beside the model by name would be a core that
        knows what DSM is, and would have nothing to say about the next kind of device."""
        # The code, not the prose: the comment says "update" because that is the example the
        # screen showed. What must not exist is a field name being tested for.
        body = _strip_comments(self._fn())
        assert 'syno_' not in body, 'the identity card names a module field'
        for tell in ('m.field ===', 'm.field ==', 'm.label ===', ".includes('"):
            assert tell not in body, f'the card picks its values by name ({tell})'

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

    def test_and_how_hot_they_are(self):
        """`diskHealthStatus` says "Normal" until the day it does not. Heat is the half of a
        drive's condition that moves, and the summary card is where somebody looks weeks before
        there is anything to look for."""
        import json                                            # noqa: PLC0415
        prof = json.loads(_read(os.path.join(
            SRC, 'lib', 'core', 'snmp', 'profiles', 'sources', 'synology_disks.json')))
        temp = [m for m in prof['metrics'] if m['key'] == 'syno_disk_temp'][0]
        assert temp.get('headline'), 'a disk says how it is and not how hot it is'
        assert temp.get('unit') == '°C', 'degrees, not a bare number'

    def test_a_card_grows_sideways(self):
        """Reported from the screen: a disk with two readings stacked them, so a shelf of eight
        came out as eight tall boxes each with an empty right half. The card was pinned at a
        14rem basis, which is a width chosen before anyone knew what was going in it — so the
        CONTENT wrapped instead. Sized by what it holds, and the whole card wraps when the pane
        runs out of room, which is the thing that should wrap."""
        body = _fn(_read(DETAILS), '_infraDetailRow')
        assert 'flex:0 1 auto' in body, 'the card does not follow its content'
        assert 'flex:1 1 14rem' not in body, 'the card is still pinned at a fixed basis'
        assert 'min-width:7rem' not in body, 'a reading still claims a column of its own'

    def test_a_condition_on_a_card_is_a_mark(self):
        """The word is the widest thing in the box and the one that changes with the language:
        eight disks came out as eight cards sized by the length of "Normal" in Spanish. A tick,
        a triangle or an octagon says the same thing in every language and in no room at all —
        with the word itself on the hover and in the row's own dialog, since "Initialized" and
        "Not initialized" are two pieces of news that no symbol separates."""
        body = _fn(_read(DETAILS), '_infraCardValueHtml')
        assert 'm.states' in body and '_INFRA_LEVEL_MARKS' in body
        assert 'title=' in body and 'aria-label=' in body, (
            'the word is gone rather than moved — unreachable by hover or by screen reader')
        assert '_infraValueHtml(m)' in body, 'a reading that is not a state must be untouched'

    def test_the_mark_is_picked_by_the_level_the_profile_declared(self):
        """The same value the badge is coloured by, so a symbol and a colour cannot disagree.
        Reading the WORD would be the panel deciding that "Degraded" is bad and "Repairing" is
        not — which is true, and is not something the text can tell you."""
        body = _fn(_read(DETAILS), '_infraCardValueHtml')
        assert 'st.level' in body
        assert 'st.label.' not in body and 'toLowerCase' not in body

    def test_every_level_has_a_shape_of_its_own(self):
        """The silent one. A level added to the palette without a mark falls back to the info
        `i`, so the worst news on the device draws as the mildest — no error anywhere, and the
        card looks exactly as it should. Shape AND colour, because colour alone is not a
        distinction for everybody."""
        marks = _read(DETAILS).split('_INFRA_LEVEL_MARKS = {')[1].split(NL + '};')[0]
        levels = _read(METRICS).split('_INFRA_LEVELS = {')[1].split('};')[0]
        have = set(re.findall(r'(\w+):\s*\{', marks))
        want = set(re.findall(r'(\w+):\s*[\'"]', levels))
        assert want and have == want, f'levels {sorted(want)} but marks {sorted(have)}'
        icons = re.findall(r"icon: '([^']+)'", marks)
        assert len(set(icons)) == len(icons), f'two levels share a shape: {icons}'
        assert all(i.startswith('bi-') for i in icons), icons

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

    def test_the_facts_are_a_grid_and_not_a_ragged_row(self):
        """Reported from the screen. With a flex row each pair takes the width of its own
        text, so "Tipo SATA" sits inches from "Modelo ST14000NM000J-2TX103" and there is no
        column for the eye to run down. Columns of a minimum width line up and wrap whole."""
        body = _fn(self._src(), '_infraRowFactsHtml')
        assert 'ss-factgrid' in body
        assert 'd-flex flex-wrap gap-3' not in body, 'the bare flex with no gap of its own'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        base = css.split('.ss-factgrid {')[1].split('}')[0]
        # Columns of EQUAL width was the version after that, and it wrapped for a reason that
        # has nothing to do with the content: four tracks of 13rem need 56rem and the dialog
        # offers 46, so the fourth fact dropped to a line of its own while three quarters of
        # the row sat empty. A fact is as wide as the fact.
        assert 'grid-template-columns' not in base
        assert 'display: flex' in base and 'gap:' in base
        item = css.split('.ss-factgrid > div {')[1].split('}')[0]
        assert 'min-width' in item and 'max-width' in item, (
            'a fact is unbounded — one long value pushes the rest off the row')

    def test_the_two_shapes_each_declare_their_own(self):
        """The facts are a flex row and the readings are a grid. A modifier that only changed
        `grid-template-columns` while the base said `display: flex` would be a layout that
        depends on which rule loaded last."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert 'display: grid' in css.split('.ss-factgrid-lg {')[1].split('}')[0]
        assert css.index('.ss-factgrid-lg {') > css.index('.ss-factgrid {')

    def test_the_dialog_grows_to_what_it_needs(self):
        """Already true and worth pinning: a dialog of this size is `fit-content` capped at
        the work area, so widening it is a matter of the content asking for the room."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.modal-lg, .modal-xl { max-width: 96vw; width: fit-content; }' in css

    def test_the_facts_read_in_an_order_somebody_chose(self):
        """Alphabetical by KEY is what it was, which put "Bahía" first and "Modelo" third for
        no reason a reader could see. The keys are internal and their alphabet is not a fact
        about equipment."""
        src = self._src()
        assert '_INFRA_FACT_ORDER' in src
        order = src.split('_INFRA_FACT_ORDER = [')[1].split('];')[0]
        assert order.index("'model'") < order.index("'bay'"), 'what it is, before where it sits'
        assert order.index("'serial'") < order.index("'role'")
        body = _fn(src, '_infraRowFactsHtml')
        assert '_infraFactRank' in body, 'the order is declared and not applied'

    def test_a_role_the_core_does_not_name_still_appears(self):
        """Last, and not dropped: a module can record an attribute the core has no word for,
        and a fact nobody shows is a fact somebody reads off the machine with a torch."""
        body = _fn(self._src(), '_infraFactRank')
        assert '_INFRA_FACT_ORDER.length' in body

    def test_a_part_number_is_not_broken_in_half(self):
        """Reported from the screen: "ST12000NM000J-2TY103" came out as "…-2TY10" and "3" on
        the next line, which reads as two things. Truncated with the whole of it on the hover,
        which is what the rest of the panel does with a value that will not fit."""
        body = _fn(self._src(), '_infraRowFactsHtml')
        assert 'text-truncate' in body and 'title="${escAttr(text)}"' in body
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        grid = css.split('.ss-factgrid {')[1].split('}')[0]
        assert 'word-break' not in grid, 'the browser is still told to split a part number'

    def test_an_icon_is_the_profiles_word(self):
        """A number has no picture. Only whatever produced it knows that this one is a
        temperature and that one a count of bad sectors, so the profile says — and a metric
        that says nothing gets none rather than a placeholder."""
        body = _fn(self._src(), '_infraRowList')
        assert 'm.icon ?' in body, 'every reading gets an icon whether it has one or not'
        assert 'escAttr(m.icon)' in body, 'the icon reaches a class attribute unescaped'
        prof = _read(os.path.join(SRC, 'lib', 'core', 'snmp', 'profiles', '__init__.py'))
        assert "_ICON_RE = re.compile(r'^bi-[a-z0-9-]{1,40}$')" in prof, (
            'a profile is data an administrator writes, and this one ends up in a class')

    def test_the_dialog_does_not_offer_to_be_resized(self):
        """A resize handle and a maximise button on a box that is already exactly as tall as
        its six lines is offering to make the empty part bigger. Both halves — the CSS and the
        header controls — read one function, so they cannot disagree about which dialogs are
        resizable."""
        beh = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'init',
                                 '_behaviors.html'))
        assert 'function _modalResizable' in beh
        assert beh.count('_modalResizable(dlg)') == 3, 'a caller still decides for itself'
        assert "contains('ss-modal-fit')" in beh
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        content = css.split('.ss-modal-fit > .modal-content {')[1].split('}')[0]
        assert 'resize: none' in content

    def test_the_dialog_is_only_as_tall_as_it_needs(self):
        """`.modal-dialog-scrollable` sets a full height unconditionally — which is what makes
        a long body scroll inside instead of pushing the page, and also what left six readings
        sitting in four hundred pixels of empty box."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-modal-fit.modal-dialog-scrollable' in css
        # split on the RULE and not the name: the comment above it says the name too
        rule = css.split('.ss-modal-fit.modal-dialog-scrollable,')[1].split('}')[0]
        assert 'height: auto' in rule
        assert '.ss-modal-fit.modal-dialog-centered.modal-dialog-scrollable' in rule
        # It still SPANS, and that span is what centring measures against — taking it away
        # (the second attempt) gave a compact box glued to the top of the screen.
        assert 'min-height: calc' in rule and 'justify-content: center' in rule
        content = css.split('.ss-modal-fit > .modal-content {')[1].split('}')[0]
        # …and the content is the half that must not stretch into that span. This is the line
        # that empties the four hundred pixels.
        assert 'flex: 0 1 auto' in content
        assert 'max-height' in content, (
            'a long body would now push the page instead of scrolling inside')
        dialogs = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                     'modals', '_dialogs.html'))
        info = dialogs.split('id="infoModal"')[1].split('</div>')[0]
        assert 'ss-modal-fit' in info

    def test_the_readings_do_not_span_the_whole_dialog(self):
        """A full-width row made the eye travel the entire modal to join "Temperatura" to
        "40 °C", with nothing in between."""
        body = _fn(self._src(), '_infraRowList')
        assert 'ss-factgrid-lg' in body
        assert '<table' not in body, 'one column across the whole width again'

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


class TestTwoColumnsThatAreOnePicture:
    """Traffic in and traffic out are one question. Two charts side by side, on two y-scales
    fitted separately, is that comparison made impossible — and two cards showing the two
    numbers is the same comparison left to the reader as arithmetic."""

    def _js(self):
        return _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra',
                                  '_details.html'))

    def test_the_pair_is_one_card(self):
        det = self._js()
        pane = _fn(det, '_infraDetailsPane')
        assert 'mated' in pane and 'chart_with' in pane, (
            'a figure named by another as its companion still gets a card of its own')
        tile = _fn(det, '_infraDetailTile')
        assert '_infraChartMates(m)' in tile and '[m, ...mates]' in tile, (
            'the card shows one of the two numbers it is about')
        assert 'm.chart_label' in tile, (
            'the combined card is headed with the name of one half of it')

    def test_the_companion_comes_from_the_payload_and_not_from_a_second_call(self):
        """They are columns of ONE result, so every point of the series already carries both
        numbers — the pairing costs no extra request, and a second one would be two windows of
        the same picture free to disagree."""
        metrics = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra',
                                     '_metrics.html'))
        mates = _fn(metrics, '_infraChartMates')
        assert 'x.module === m.module' in mates and 'x.key === m.key' in mates
        assert 'apiGet' not in mates and 'await' not in mates
        chart = _fn(metrics, '_infraChart')
        assert chart.count('apiGet') == 1, 'a paired chart asks twice'

    def test_a_companion_the_device_never_answered_is_not_drawn(self):
        """A profile can declare a pair whose second half this box does not serve. An empty
        line with a name on the legend is a chart claiming a series that is not there."""
        chart = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'history',
                                   '_chart.html'))
        draw = _fn(chart, '_historyDraw')
        assert 'const mates = (extra || []).filter' in draw
        assert "typeof (p.data || {})[x.field] === 'number'" in draw, (
            'a declared companion is drawn whether or not the payload carries it')

    def test_the_axis_holds_every_series_on_it(self):
        """Fitted to the first series alone, the second is drawn off the top of the box — which
        is the same lie as two charts on two scales, with less warning."""
        chart = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'history',
                                   '_chart.html'))
        draw = _fn(chart, '_historyDraw')
        assert 'vals.concat(...mateVals)' in draw, 'the y-range is fitted to one of them'

    def test_with_two_lines_the_colour_names_them(self):
        """One series is coloured by whether the device was up, one segment at a time. With two
        on the axis the eye has to tell the lines apart first, and the strip under the chart
        already answers the other question for every series at once."""
        chart = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'history',
                                   '_chart.html'))
        draw = _fn(chart, '_historyDraw')
        assert 'MATE_COLOURS' in draw and "'#0d6efd'" in draw
        assert 'mates.length ? MATE_COLOURS[0]' in draw, 'status colouring survives the pair'
        assert 'ctx.fillRect(lx' in draw, 'two lines and nothing saying which is which'


class TestAShapeGetsALineOfItsOwn:
    """Reported from the screen: four cards across left the traffic chart about 380 px wide,
    with a week of two series in it and a y-axis whose labels ran into the axis title. A number
    is a card; a shape is a figure, and a figure sharing a row with three numbers is one nobody
    reads."""

    def _det(self):
        return _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra',
                                  '_details.html'))

    def test_a_card_that_draws_takes_the_line_it_is_on(self):
        tile = _fn(self._det(), '_infraDetailTile')
        assert "auto ? '100%' : '11rem'" in tile, 'a chart shares its row again'

    def test_the_plain_figures_come_first(self):
        """A full-width card in the middle of the run leaves the cards before it stranded on a
        line of their own, with the rest of that line empty."""
        pane = _fn(self._det(), '_infraDetailsPane')
        assert '_infraWantsChart(a)' in pane, 'the order no longer knows which cards draw'

    def test_one_answer_to_whether_a_figure_draws(self):
        """The tile and the order it is drawn in have to agree, or the sort puts a card at the
        end that then renders narrow — or worse, leaves a full-width one in the middle."""
        det = self._det()
        assert 'function _infraWantsChart(' in det
        tile = _fn(det, '_infraDetailTile')
        assert '_infraWantsChart(m, shape)' in tile
        assert "m.chart === 'area'" not in tile, 'the tile decides again, on its own'


class TestAnAxisIsReadOrItIsDecoration:

    def _chart(self):
        return _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'history',
                                  '_chart.html'))

    def test_the_labels_are_scaled(self):
        """"13420000B/s" is a number nobody reads, and on a narrow chart it ran into the axis
        title. Through the same scaler as every other value on the screen."""
        draw = _fn(self._chart(), '_historyDraw')
        assert '_fmtMeasure' in draw and 'axisDiv' in draw
        assert '_hFmtNum(v / axisDiv) + axisUnit' in draw, 'the axis prints its base unit again'

    def test_the_gutter_is_measured_and_not_guessed(self):
        """58 px was enough for "8.50W" and not for "13.39MB/s", which ran straight into the
        rotated axis title beside it — two pieces of text on top of each other. The labels are
        composed BEFORE the padding that has to hold them, and the padding is their width."""
        draw = _fn(self._chart(), '_historyDraw')
        assert 'yLabels.map(l => ctx.measureText(l).width)' in draw, (
            'the left gutter is a number somebody typed again')
        assert 'l: 58' not in draw and "b: 38, l: 58" not in draw
        assert draw.index('const yLabels') < draw.index('const PAD'), (
            'the padding is decided before the labels it has to hold')
        assert "(metricLabel ? 24 : 10)" in draw, (
            'no room kept for the rotated title, which is drawn inside that gutter')

    def test_one_unit_for_the_whole_axis(self):
        """Scaling each label on its own gives "13.4 MB/s" above "980 kB/s" — an axis that
        changes unit halfway up and cannot be read at a glance. The top decides for all."""
        draw = _fn(self._chart(), '_historyDraw')
        assert 'Math.max(Math.abs(ymin), Math.abs(ymax))' in draw

    def test_the_scaler_is_asked_for_and_not_assumed(self):
        """History is a section of its own and must still draw when the infrastructure bundle
        is not on the page — `_fmtMeasure` lives over there."""
        draw = _fn(self._chart(), '_historyDraw')
        assert "typeof _fmtMeasure === 'function'" in draw
        assert 'axis ? axis.unit : unit' in draw, 'no fallback to the unit it was given'


class TestAChartCanHaveTheWholePage:
    """A week of two series in a 380 px card is a shape you can see and not one you can read.

    This was the browser's own full screen, which answers that by taking the panel away with
    the picture: no sidebar, no breadcrumb, nothing around the chart, and a way out that is a
    browser gesture rather than something on the page — and it can be refused outright by a
    policy or an iframe. The card grows over the page instead, to 90 % of it, on a veil that
    darkens and blurs what is behind. The margin left around it is what says the panel is
    still there underneath rather than gone, and it is where somebody clicks to get out of
    something they did not mean to open."""

    def _js(self):
        return _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra',
                                  '_metrics.html'))

    def test_the_control_sits_with_the_one_that_draws_the_chart(self):
        """It was floating in the corner of the picture, where the one thing it covered was
        the picture — the corner a legend and the newest point share. And only where the
        controls are already a group of icons: the measurements table is one row per reading,
        and a second button on every one of six hundred is texture and not a control."""
        js = self._js()
        link = _fn(js, '_infraChartLink')
        assert '_infraChartZoom(' in link and 'infra_chart_zoom' in link
        assert 'btn-group' in link, 'two loose buttons where the card had one'
        assert link.index('_infraChartZoom(') < link.index('btn-link'), (
            'the expand button reached the table of six hundred readings')
        chart = _fn(js, '_infraChart')
        assert 'ss-chartfull' not in chart, 'the button is back on top of the picture'

    def test_the_control_is_there_only_while_a_chart_is(self):
        """Reported from the screen: a card showing one number — a processor temperature —
        carried an expand button beside the one that draws the chart. Expanding a picture that
        is not there is not an offer; it is a second icon on every card that has a series,
        which is how a pair of controls stops reading as controls and starts reading as
        texture."""
        js = self._js()
        link = _fn(js, '_infraChartLink')
        expand = link.split('_infraChartZoom(')[0]
        assert 'd-none' in link.split('_infraChartZoom(')[1].split('</button>')[0] \
            or 'd-none' in expand.rsplit('<button', 1)[-1], 'it does not start hidden'
        assert 'bi-graph-up' not in link.split('d-none')[0].rsplit('<button', 1)[-1], (
            'the button that OPENS the chart was hidden too — then nothing can open one')
        chart = _fn(js, '_infraChart')
        assert chart.count('_infraZoomShown(') == 3, (
            'the three ways a chart ends do not all agree about the button: closed, '
            'drawn, and a series with no history to draw')

    def test_it_draws_the_chart_it_was_asked_to_enlarge(self):
        """Kept although the button is only on screen while a chart is: it is what makes this
        safe to call from anywhere, and an expanded empty box is what it avoids."""
        zoom = _fn(self._js(), '_infraChartZoom')
        assert "box.dataset.open !== '1'" in zoom and 'await _infraChart(i)' in zoom

    def test_a_series_with_no_history_is_not_a_picture(self):
        """`dataset.open` does not answer whether there is one: a device with nothing recorded
        yet leaves the box open with a line of text in it, and the work area filled with "no
        data yet" is not what the button offered. `ss-chartbox` is put there by the drawing
        and by nothing else."""
        zoom = _fn(self._js(), '_infraChartZoom')
        assert "classList.contains('ss-chartbox')" in zoom

    def test_it_takes_the_page_and_not_the_column_beside_the_sidebar(self):
        """A chart is worth every pixel there is, and the sidebar is the one part of the panel
        nobody is reading while they look at a week of traffic."""
        js = self._js()
        area = _fn(js, '_infraZoomArea')
        assert 'window.innerWidth' in area and 'window.innerHeight' in area
        assert 'ss-main' not in js, 'it is back to the column beside the sidebar'

    def test_it_stops_short_of_the_edges(self):
        """All of it would be a full screen with extra steps: the margin is what keeps the
        panel visible underneath, and what somebody clicks to get out."""
        js = self._js()
        fill = float(js.split('_INFRA_ZOOM_FILL = ')[1].split(';')[0])
        assert 0.5 < fill < 1, f'{fill} is not a margin'
        area = _fn(js, '_infraZoomArea')
        assert '_INFRA_ZOOM_FILL' in area
        assert area.count('/ 2)') == 2, 'it is not centred — the margin is all on one side'

    def test_there_is_a_veil_between_the_card_and_the_page(self):
        """It does two jobs and they are the same job: it darkens and blurs what is behind so
        the chart is what the eye lands on, and it catches the click outside — the gesture
        anybody tries before they look for a button."""
        js = self._js()
        back = _fn(js, '_infraZoomBack')
        assert "addEventListener('click'" in back and '_infraZoomOut()' in back
        assert 'ss-zoom-back' in back
        out = _fn(js, '_infraZoomOut')
        assert 'z.back.parentNode.removeChild' in out, (
            'a transparent sheet over the whole page still swallows every click on it, and '
            'the section would look alive and answer nothing')
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        veil = css.split('.ss-zoom-back {')[1].split('}')[0]
        assert 'backdrop-filter: blur(' in veil and 'rgba(0, 0, 0' in veil, (
            'the veil neither darkens nor blurs')
        assert '-webkit-backdrop-filter' in veil, 'no blur on a WebKit browser'
        assert 'opacity: 0' in veil and '.ss-zoom-back.show { opacity: 1; }' in css, (
            'it appears at once, which is a flash of black rather than a fade')
        z_back = int(veil.split('z-index:')[1].split(';')[0].strip())
        z_card = int(css.split('.ss-zoom {')[1].split('}')[0]
                     .split('z-index:')[1].split(';')[0].strip())
        assert z_back < z_card, 'the veil is over the card it is supposed to be under'

    def test_the_card_looks_lifted_and_not_pasted_on(self):
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        block = css.split('.ss-zoom {')[1].split('}')[0]
        assert block.count('rgba(0, 0, 0') >= 2, (
            'one flat shadow reads as a grey border rather than as height')
        assert 'border-radius' in block, 'square corners on something floating over the page' 

    def test_the_card_leaves_a_gap_the_size_of_itself(self):
        """Without it the cards beside it close over the hole the moment one is expanded, and
        giving it back drops it into a family that has rearranged itself."""
        zoom = _fn(self._js(), '_infraChartZoom')
        assert 'ss-zoom-hold' in zoom and 'insertBefore' in zoom
        assert 'from.width' in zoom and 'from.height' in zoom
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-zoom-hold { visibility: hidden; }' in css, (
            'the gap is removed rather than hidden, which is the reflow it exists to stop')

    def test_there_are_two_frames_before_it_moves(self):
        """In one, the browser coalesces the start and the end into the end state: the card
        appears at full size with no movement to see, which is the animation not happening."""
        zoom = _fn(self._js(), '_infraChartZoom')
        assert zoom.count('requestAnimationFrame') == 2

    def test_the_way_back_is_the_button_and_the_key(self):
        js = self._js()
        assert '_infraZoomOut()' in _fn(js, '_infraChartZoom'), 'the same button both ways'
        assert "e.key !== 'Escape'" in js, 'Escape does not give the card back'
        assert "querySelector('.modal.show')" in js, (
            "Escape is taken from a dialog that is open, closing the card underneath instead "
            "of the thing somebody is looking at")

    def test_what_is_expanded_is_put_back_before_the_markup_is_rewritten(self):
        """A card given back after the pane is redrawn is given back to a parent that is no
        longer there. Both of the two places that rewrite it — the section, and the open
        device, which refreshes in place."""
        render = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra',
                                    '_render.html'))
        assert '_infraZoomOut(true)' in _fn(render, 'renderInfra')
        assert '_infraZoomOut(true)' in _fn(render, '_infraReload')
        out = _fn(self._js(), '_infraZoomOut')
        assert 'document.body.contains' in out, 'it puts back a card that is already gone'

    def test_the_auto_refresh_does_not_take_the_picture_away(self):
        """This is the screen somebody leaves open on a wall, on a poll. A redraw underneath
        an expanded chart closes it, so a thirty-second interval would take it back from
        whoever expanded it, every thirty seconds — the same reason the tick already stands
        aside for a running collection."""
        render = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra',
                                    '_render.html'))
        tick = _fn(render, '_infraAutoTick')
        assert '_infraZoom' in tick and 'return' in tick

    def test_closing_the_chart_cannot_leave_a_card_the_size_of_the_screen(self):
        """…with nothing in it, and a way back that is no longer on screen."""
        chart = _fn(self._js(), '_infraChart')
        assert '_infraZoomOut(true)' in chart

    def test_nothing_is_left_pinned_where_it_was_dropped(self):
        """The four properties are set inline to animate them, so they have to be taken off
        again or the card keeps the size of the work area once it is back in the flow."""
        out = _fn(self._js(), '_infraZoomOut')
        assert "style.top = z.card.style.left = ''" in out
        assert "style.width = z.card.style.height = ''" in out
        assert "classList.remove('ss-zoom')" in out

    def test_the_canvas_is_redrawn_at_its_new_size(self):
        """A canvas is drawn at a pixel size and does not reflow: the box gets three times
        wider and the picture stays where it was, stretched. After the card has finished
        growing, not during, when its size is still changing."""
        js = self._js()
        assert '_INFRA_ZOOM_MS' in _fn(js, '_infraChartZoom')
        assert '_infraChartRedraw' in _fn(js, '_infraChartZoom')
        assert '_infraChartRedraw' in _fn(js, '_infraZoomOut')
        assert "addEventListener('resize'" in js, 'a window resized leaves it the wrong size'
        redraw = _fn(js, '_infraChartRedraw')
        assert '_historyDraw(' in redraw and 'canvas._histMeta' in redraw
        assert 'apiGet' not in redraw, 'resizing a chart re-fetches its series'

    def test_the_expanded_card_sits_over_the_panel_and_under_a_dialog(self):
        """Reported from the screen: the sidebar sat on top of the veil, undimmed, with an
        open submenu over the chart. The panel puts more on screen than the sticky header,
        and a number chosen to clear that one clears none of the others — so they are read
        off the style sheet rather than written down here, and a sidebar raised tomorrow
        fails this instead of covering the chart again."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        block = css.split('.ss-zoom {')[1].split('}')[0]
        assert 'position: fixed' in block
        z = int(block.split('z-index:')[1].split(';')[0].strip())

        def _z(sel):
            """The HIGHEST one declared for that selector, not the first block that carries
            it: a selector is written more than once — a theme override, a media query — and
            the veil has to clear whichever of them wins."""
            found = [int(b.split('z-index:')[1].split(';')[0].strip())
                     for b in css.split(sel + ' {')[1:]
                     if 'z-index:' in b.split('}')[0]
                     for b in [b.split('}')[0]]]
            assert found, sel + ' declares no z-index any more'
            return max(found)

        for sel in ('.ss-sidebar', '.ss-sb-flyout', '.dropdown-menu'):
            assert z > _z(sel), f'{sel} ({_z(sel)}) stays over the expanded card ({z})'
        assert z < 1055, f'z-index {z} is over a dialog'

    def test_the_browsers_own_full_screen_is_gone(self):
        """Both halves of it: the call that asked for it and the rules that styled it. A
        `:fullscreen` block nothing can enter is a rule that will be read as live."""
        js = self._js()
        for word in ('requestFullscreen', 'exitFullscreen', 'fullscreenchange',
                     'fullscreenElement'):
            assert word not in js, f'{word} outlived the mechanism it belonged to'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert ':fullscreen' not in css

    def test_the_height_is_a_class_and_not_a_style_attribute(self):
        """…or the expanded rule would have to fight an inline style with `!important`."""
        chart = _fn(self._js(), '_infraChart')
        assert 'ss-charth' in chart and 'height:170px' not in chart
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-zoom .ss-charth' in css, 'the chart does not grow with the card'
        assert '.ss-zoom > .ss-chartbox' in css, (
            'the chart is not what takes the room the card gained — it keeps its 170 px and '
            'the rest of the work area is empty')
        block = css.split('.ss-zoom {')[1].split('}')[0]
        assert 'background:' in block, (
            'a transparent card over whatever it covers is a chart drawn on top of the page')
