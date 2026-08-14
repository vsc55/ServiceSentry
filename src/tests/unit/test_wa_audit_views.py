#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The audit log can be read four ways, and two of them are not lists.

A table reads the log one line at a time, which is right for "what happened at 14:32" and
wrong for every question about the log as a whole. Two of those are worth a view each:

* WHO has been active. The table shows every line by every actor and never a per-actor total,
  so "an account nobody uses did forty things last night" is invisible unless you already
  suspected it and filtered by that user — you have to know the answer to ask the question.
* WHEN it happened. A 03:00 login and an 11:00 login read identically in a list sorted by
  time; on a day × hour grid they are in different places, and off-hours activity becomes a
  shape rather than a query you have to think of.

Those two are SUMMARIES, and the guards below are mostly about what that word costs. A
summary describes a set: it is computed over everything the filters left standing rather than
over the page, it is not paginated (page 2 of a heat map is not a thing), and it picks its own
axis — which is why the Sort and Group-by controls are hidden while one is on screen instead
of being left there to do nothing.

What must not differ between views is what an ENTRY is, and the part of that which is not
cosmetic is the delete button: `audit_delete` becomes a control in exactly one place.
"""

import os
import re
from tests.helpers import _fn, _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
AUD = os.path.join(TPL, 'partials', 'audit')
VIEWS = os.path.join(AUD, '_views.html')
RENDER = os.path.join(AUD, '_render.html')
FILTERS = os.path.join(AUD, '_filters.html')
VIEW_FILES = {
    'timeline': os.path.join(AUD, '_view_timeline.html'),
    'actors': os.path.join(AUD, '_view_actors.html'),
    'activity': os.path.join(AUD, '_view_activity.html'),
}


def _strip_comments(js: str) -> str:
    """Code only. A guard that reads the prose trips over the comment explaining the rule it
    is checking, and every file here carries one."""
    js = re.sub(r'\{#.*?#\}', '', js, flags=re.S)
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


class TestTheScanItself:
    """If these fail the guard is broken, not the layout."""

    def test_every_file_is_found(self):
        for p in (VIEWS, RENDER, FILTERS, *VIEW_FILES.values()):
            assert os.path.isfile(p), p

    def test_the_registry_lists_every_view(self):
        src = _strip_comments(_read(VIEWS))
        reg = src[src.index('const AUDIT_VIEWS'):]
        reg = reg[:reg.index('];')]
        for vid in ('table', 'timeline', 'actors', 'activity'):
            assert f"id: '{vid}'" in reg, f'{vid} is not in the registry'

    def test_the_bundle_includes_them_after_the_registry(self):
        """The registry names render functions as STRINGS because the view files are
        concatenated after it. A file that is never included makes its view fall back to an
        empty body without saying so."""
        js = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        i_views = js.index('audit/_views.html')
        for f in ('audit/_view_timeline.html', 'audit/_view_actors.html',
                  'audit/_view_activity.html'):
            assert f in js, f'{f} is never included'
            assert js.index(f) > i_views, f'{f} is included before the registry it registers in'


class TestOnePlaceDecidesWhoMayDelete:

    def test_the_permission_becomes_a_button_once(self):
        """The one that is not cosmetic. Two places asking "may this user delete" is one place
        that can answer it differently."""
        views = _strip_comments(_read(VIEWS))
        assert views.count('function _auditDeleteBtn') == 1
        body = _fn(views, '_auditDeleteBtn')
        assert 'ctx.canDelete' in body and 'deleteAuditEntry(' in body

    def test_no_view_builds_its_own_delete_button(self):
        for name, path in (*VIEW_FILES.items(), ('table', RENDER)):
            body = _strip_comments(_read(path))
            assert 'onclick="deleteAuditEntry' not in body, (
                f'{name} wires the delete itself instead of composing _auditDeleteBtn')

    def test_no_view_reads_the_permission_set(self):
        """It is resolved once per render into a ctx every view is handed."""
        for name, path in VIEW_FILES.items():
            assert 'currentUser.permissions' not in _strip_comments(_read(path)), name
        assert '_auditCtx()' in _strip_comments(_read(RENDER))

    def test_a_summary_row_offers_no_delete(self):
        """There is no single entry behind a count, so there is nothing for the button to
        act on — and a delete aimed at "42 entries by this user" is not the same feature."""
        for name in ('actors', 'activity'):
            assert '_auditDeleteBtn' not in _strip_comments(_read(VIEW_FILES[name])), name


class TestASummaryIsNotAPage:

    def test_summaries_are_handed_the_whole_filtered_set(self):
        """Over the page they would describe "the first 25 entries", which is a statement
        about the pagination and not about the log."""
        body = _fn(_strip_comments(_read(RENDER)), 'renderAuditTable')
        assert '_auditViewBody(pageEntries, filtered, ctx)' in body
        disp = _fn(_strip_comments(_read(VIEWS)), '_auditViewBody')
        assert 'v.lists ? pageEntries : filtered' in disp

    def test_only_the_list_views_are_paginated(self):
        body = _fn(_strip_comments(_read(RENDER)), 'renderAuditTable')
        assert re.search(r'const pageEntries = lists\s*\n?\s*\?', body), \
            'the page slice no longer depends on the view family'
        assert body.count('${lists ?') >= 2, 'the pagination bands are drawn for a summary'

    def test_the_summary_header_states_the_whole_set(self):
        """A view that shows twelve rows must never suggest the log holds twelve entries —
        the same rule the Status and Services headers follow."""
        body = _fn(_strip_comments(_read(VIEWS)), '_auditSummaryHeader')
        assert 'entries.length' in body
        for name in ('actors', 'activity'):
            assert '_auditSummaryHeader(' in _strip_comments(_read(VIEW_FILES[name])), name

    def test_the_list_only_controls_are_hidden_for_a_summary(self):
        """Sort and Group by decide the order of a LIST. A summary picks its own axis, so
        leaving them on screen would offer a control that does nothing when used."""
        src = _strip_comments(_read(VIEWS))
        body = _fn(src, '_auditSyncListControls')
        assert 'ss-audit-listctl' in body
        assert '_auditViewLists()' in body
        filters = _strip_comments(_read(FILTERS))
        assert filters.count('ss-audit-listctl') == 2, \
            'the Sort and Group-by blocks are no longer both marked'
        assert '_auditSyncListControls()' in filters, 'the first paint never syncs them'

    def test_the_column_chooser_belongs_to_the_table(self):
        body = _fn(_strip_comments(_read(RENDER)), 'renderAuditTable')
        assert "view.id === 'table'" in body


class TestSwitchingViewIsPresentationOnly:

    def test_it_redraws_instead_of_refetching(self):
        """Every view reads the same `_auditEntries`, and this section's fetch returns the
        WHOLE log — re-asking for it to answer a question about presentation is the most
        expensive possible way to change a layout."""
        body = _fn(_strip_comments(_read(VIEWS)), 'setAuditView')
        assert 'renderAuditTable()' in body
        assert 'apiGet' not in body and 'renderAudit()' not in body

    def test_it_returns_to_the_first_page(self):
        """Page 3 of the table is not page 3 of anything else, and a summary has no pages at
        all — keeping the number would land the next list view on an empty slice."""
        body = _fn(_strip_comments(_read(VIEWS)), 'setAuditView')
        assert '_auditPage = 1' in body

    def test_the_choice_is_remembered_with_the_rest_of_the_ui_state(self):
        """Sort, group, filters and now the view travel in one key rather than each growing a
        localStorage entry of its own."""
        filters = _strip_comments(_read(FILTERS))
        assert 'view: _auditViewId()' in _fn(filters, '_saveAuditUiState')
        assert '_auditApplyView(saved?.view)' in _fn(filters, 'initAuditControls')


class TestTheTimelineIsTheSameRowsInTheSameOrder:

    def test_it_does_not_re_sort(self):
        """Grouping by day and sorting the days would quietly override the direction the sort
        control decides, and the page would stop matching the pagination band above it."""
        body = _strip_comments(_read(VIEW_FILES['timeline']))
        assert '.sort(' not in body, 'the timeline re-orders the page under the user'

    def test_the_day_header_follows_the_entries(self):
        body = _fn(_strip_comments(_read(VIEW_FILES['timeline'])), '_auditViewTimeline')
        assert '_auditDayKey(e.ts)' in body and 'day = k' in body

    def test_a_day_is_the_readers_day(self):
        """From toISOString() the key would be the UTC day, so an entry either side of local
        midnight would sit under a heading with a different date than its own timestamp —
        in the timeline AND in the activity grid, which counts hours locally.

        The computation lives in the shared `_dayKeyLocal` because Events groups by day too,
        and where midnight falls is not something two sections may answer differently.
        """
        assert '_dayKeyLocal(ts)' in _fn(_strip_comments(_read(VIEWS)), '_auditDayKey')
        shared = _fn(_strip_comments(_read(os.path.join(TPL, 'partials', 'core', '_utils.html'))),
                     '_dayKeyLocal')
        assert 'toISOString' not in shared
        assert 'getFullYear()' in shared and 'getDate()' in shared


class TestActorsCountsWhatMatters:

    def test_failed_logins_are_counted_apart(self):
        """A hundred entries from an admin who was working is not news; six failed logins from
        an account that did nothing else is, and averaged into one total they look alike."""
        body = _strip_comments(_read(VIEW_FILES['actors']))
        assert '_auditIsFailedLogin(' in body
        assert 'audit_col_failed' in body

    def test_the_failure_definition_is_narrow_and_shared(self):
        """Folding "everything that is not a success" into it would make the number mean
        nothing, and each view inventing its own definition would make it mean two things."""
        body = _fn(_strip_comments(_read(VIEWS)), '_auditIsFailedLogin')
        assert "e.event === 'login_failed'" in body

    def test_it_lists_the_addresses_rather_than_only_counting_them(self):
        """"3 IPs" is a number; WHICH three is the fact you act on."""
        body = _strip_comments(_read(VIEW_FILES['actors']))
        # The cut itself is the shared `_chipList` (core/_utils.html) — nine views had written
        # the same slice/join/+n by hand.
        assert 'a.ips' in body and '_chipList(' in body

    def test_an_entry_with_no_user_is_not_called_unknown(self):
        """The daemon writes entries with no session behind them. Calling that "unknown"
        would suggest something is missing when nothing is."""
        body = _fn(_strip_comments(_read(VIEWS)), '_auditActor')
        assert "t('audit_actor_system')" in body


class TestActivityIsACountNotAVerdict:

    def test_the_ramp_is_one_hue(self):
        """The colour carries a count and nothing else: this view has no opinion about whether
        activity is good, so a red-to-green ramp would be inventing one."""
        body = _fn(_strip_comments(_read(VIEW_FILES['activity'])), '_auditHeatColor')
        assert body.count('--bs-primary') == 1
        for state in ('--bs-danger', '--bs-success', '--bs-warning'):
            assert state not in body, f'the heat ramp reaches for {state}'

    def test_it_is_theme_aware(self):
        """Both ends of the ramp are theme variables: a scale tuned against one background is
        wrong on the other, and there is no version of it that is right on both."""
        body = _fn(_strip_comments(_read(VIEW_FILES['activity'])), '_auditHeatColor')
        assert 'var(--bs-tertiary-bg)' in body

    def test_every_cell_states_its_number(self):
        """A shade is a comparison, not a value — without the exact count the grid can only be
        read relative to itself."""
        body = _fn(_strip_comments(_read(VIEW_FILES['activity'])), '_auditActivityRow')
        assert 'title="${escAttr(title)}"' in body

    def test_the_cap_is_never_silent(self):
        """Dropping the older days without saying so reads as "this is all there is", which is
        the one thing an audit view must not imply."""
        body = _strip_comments(_read(VIEW_FILES['activity']))
        assert '_AUD_ACT_MAX_DAYS' in body
        assert 'audit_activity_capped' in body
        assert 'dropped ?' in body, 'the notice is not tied to the cap actually biting'


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for vid in ('table', 'timeline', 'actors', 'activity'):
                assert f"'audit_view_{vid}':" in src, f'{lang} does not name the {vid} view'

    def test_the_summary_vocabulary_exists_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('audit_actor_system', 'audit_count_entries', 'audit_count_actors',
                        'audit_count_days', 'audit_actors_failing', 'audit_col_entries',
                        'audit_col_failed', 'audit_col_kinds', 'audit_col_first',
                        'audit_col_last', 'audit_peak', 'audit_legend_less',
                        'audit_legend_more', 'audit_activity_capped'):
                assert f"'{key}':" in src, f'{lang} is missing {key}'

    def test_the_cap_notice_names_both_numbers(self):
        """"Showing 62 days" alone hides how much was left out."""
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            m = re.search(r"'audit_activity_capped':\s*'([^']*)'", src)
            assert m, lang
            assert m.group(1).count('{}') == 2, f'{lang}: audit_activity_capped lost a number'


class TestAnEntryIsAlwaysReachable:
    """The log exists to be read. An entry the reader cannot open is a record nobody has.

    Reported from a MIB import: the row printed its whole summary as prose — six lines of
    file names and TLS errors in a table cell — and was not clickable, while the two lists
    that answered "which ones, and why" sat unread inside the entry.
    """

    DETAIL = os.path.join(AUD, '_detail.html')

    def test_a_detail_with_more_than_the_row_shows_is_clickable(self):
        """The old rule was "clickable if it has `changes` or a before/after snapshot", which
        is the vocabulary of the core's own events. A module's audit hook records whatever it
        likes, and under that rule everything it recorded was unreachable."""
        body = _fn(_strip_comments(_read(self.DETAIL)), 'auditSummaryHtml')
        assert '_auditHasMore(detail)' in body, 'only core-shaped details can be opened'
        more = _fn(_strip_comments(_read(self.DETAIL)), '_auditHasMore')
        assert '_AUDIT_ROW_KEYS' in more

    def test_the_row_label_is_clipped(self):
        """A cell is an index, not the record. Twelve failures with a TLS timeout each turned
        one row into six lines."""
        body = _fn(_strip_comments(_read(self.DETAIL)), 'auditSummaryHtml')
        assert body.count('_auditClip(detail.name)') == 2, \
            'one of the two label branches prints the name unclipped'

    def test_the_modal_shows_the_keys_it_does_not_know(self):
        """It used to fall back to the generic renderer only when it had recognised NOTHING
        (`html || renderReadable(detail)`), so an entry with one known key and ten unknown
        ones showed the one and dropped the ten."""
        body = _fn(_strip_comments(_read(self.DETAIL)), 'formatAuditDetailFull')
        assert '_AUDIT_KNOWN_KEYS' in body and 'renderReadable(_rest)' in body

    def test_the_two_key_sets_stay_in_step(self):
        """The row set is the modal's plus the keys the row itself states. Written out twice
        they would drift, and the drift shows up as an entry that is clickable and opens on
        nothing, or one that holds something and cannot be opened."""
        src = _strip_comments(_read(self.DETAIL))
        assert '..._AUDIT_KNOWN_KEYS' in src, 'the row set is a second hand-written list'
