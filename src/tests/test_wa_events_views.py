#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Events section holds two different things, and each can be read four ways.

RULES are configuration — "when this happens, tell these people". The table answers "what is
configured" and leaves two questions it cannot:

* which rules reach a given CHANNEL. If Telegram breaks, what stops arriving? The channel
  column is icons per row, so the answer is a scan. Grouped by channel it is a count — and it
  is where a rule with NO channel finally shows up: one that can match perfectly and notify
  nobody, which nothing else on the page makes obvious.
* whether a rule ever actually fires. `last_fired` is a column you can sort by; what you want
  is the triage — failing now, never fired, delivering. "Never fired" is the interesting one
  and it is not an error, so a two-state view would have to call it a success.

The LOG is history — one line per notification sent. Beyond reading it as a log, the questions
are per rule ("which one is noisy, which one is failing") and per channel ("has email been
failing since 10:00"). Both are facts the flat list contains and never states.

The summaries describe everything the filters left standing and draw no pagination, the same
rule the Audit views follow. And what must not differ between views is what a rule IS: the
channel vocabulary, the delivery verdict, and the action buttons — `events_*` becomes a
control in exactly one place.
"""

import io
import os
import re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
EV = os.path.join(TPL, 'partials', 'events')
VIEWS = os.path.join(EV, '_views.html')
RENDER = os.path.join(EV, '_render.html')
MODAL = os.path.join(EV, '_modal.html')
V_RULES = os.path.join(EV, '_views_rules.html')
V_LOG = os.path.join(EV, '_views_log.html')
UTILS = os.path.join(TPL, 'partials', 'core', '_utils.html')


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


def _registry(src: str, name: str) -> str:
    reg = src[src.index('const ' + name):]
    return reg[:reg.index('];')]


class TestTheScanItself:

    def test_every_file_is_found(self):
        for p in (VIEWS, RENDER, MODAL, V_RULES, V_LOG):
            assert os.path.isfile(p), p

    def test_both_registries_list_their_views(self):
        src = _strip_comments(_read(VIEWS))
        for name, ids in (('EVENT_RULE_VIEWS', ('table', 'cards', 'channels', 'delivery')),
                          ('EVENT_LOG_VIEWS', ('table', 'timeline', 'rules', 'channels'))):
            reg = _registry(src, name)
            for vid in ids:
                assert f"id: '{vid}'" in reg, f'{vid} is not in {name}'

    def test_the_bundle_includes_them_after_the_registries(self):
        """The registries name their renderers as STRINGS because the view files are
        concatenated after them; a file that is never included makes its view fall back to an
        empty body without saying so."""
        js = _read(os.path.join(TPL, 'partials', '_js_sections.html'))
        i_views = js.index('events/_views.html')
        for f in ('events/_views_rules.html', 'events/_views_log.html'):
            assert f in js, f'{f} is never included'
            assert js.index(f) > i_views, f'{f} is included before the registry it registers in'


class TestOnePlaceDecidesWhatAUserMayDo:

    def test_the_permissions_become_buttons_once(self):
        views = _strip_comments(_read(VIEWS))
        assert views.count('function _evRuleActions') == 1
        body = _fn(views, '_evRuleActions')
        for flag in ('ctx.canEdit', 'ctx.canClone', 'ctx.canDelete'):
            assert flag in body, f'{flag} is no longer decided here'

    def test_no_view_wires_a_rule_action_itself(self):
        """Four views draw the same buttons; four places asking "may this user delete" is
        three places that can answer it differently."""
        bodies = {
            'rules': _strip_comments(_read(V_RULES)),
            'log': _strip_comments(_read(V_LOG)),
            # The table body only — the section header's "New rule" button opens the same
            # modal with no rule behind it, which is a different thing from a row's Edit.
            'table': _fn(_strip_comments(_read(RENDER)), '_eventRulesBody'),
        }
        for name, body in bodies.items():
            for wired in ('_eventDeleteRule(', 'openEventRuleModal(', '_eventTestRule('):
                assert wired not in body, f'{name} wires {wired} instead of composing _evRuleActions'

    def test_no_view_asks_the_permission_set(self):
        for name, path in (('rules', V_RULES), ('log', V_LOG)):
            body = _strip_comments(_read(path))
            assert '_evCan(' not in body, f'{name} checks a permission itself'
            assert 'currentUser.permissions' not in body, name

    def test_the_log_views_offer_no_actions_at_all(self):
        """A log line is history: there is nothing to edit and nothing to delete, and a row
        that offered the rule's buttons would invite acting on the rule from a record of what
        it once did."""
        assert '_evRuleActions' not in _strip_comments(_read(V_LOG))


class TestASummaryIsNotAPage:

    def test_summaries_get_the_whole_filtered_set(self):
        disp = _strip_comments(_read(VIEWS))
        assert 'v.lists ? pageRows : rows' in _fn(disp, '_evrViewBody')
        assert 'v.lists ? pageRows : rows' in _fn(disp, '_evlViewBody')

    def test_neither_body_paginates_a_summary(self):
        for name, path, fname in (('rules', RENDER, '_eventRulesBody'),
                                  ('log', MODAL, '_renderEventLog')):
            body = _fn(_strip_comments(_read(path)), fname)
            assert 'lists ? rows.slice(' in body, f'{name} slices a summary into pages'
            assert "el.style.display = lists ? '' : 'none'" in body, \
                f'{name} still draws pagination bands for a summary'

    def test_every_summary_states_the_set_it_describes(self):
        """A view showing four rows must never suggest the log holds four lines."""
        for path in (V_RULES, V_LOG):
            assert '_evSummaryHeader(' in _strip_comments(_read(path)), path

    def test_the_column_chooser_belongs_to_the_table(self):
        body = _fn(_strip_comments(_read(RENDER)), '_eventsRender')
        assert "_evrViewId() === 'table'" in body
        assert "_evlViewId() === 'table'" in body


class TestSwitchingViewIsPresentationOnly:

    def test_neither_switch_refetches(self):
        """Both sub-sections are fetched together when the section opens, so a refetch to
        change a layout would also reload the one the user is not looking at."""
        src = _strip_comments(_read(VIEWS))
        for fname in ('setEventRulesView', 'setEventLogView'):
            body = _fn(src, fname)
            assert 'renderEvents()' not in body, f'{fname} re-fetches both sub-sections'
            assert '_eventsRender()' in body

    def test_each_switch_returns_to_the_first_page(self):
        src = _strip_comments(_read(VIEWS))
        assert '_evrPage = 1' in _fn(src, 'setEventRulesView')
        assert '_evlPage = 1' in _fn(src, 'setEventLogView')

    def test_each_choice_is_remembered_apart(self):
        """They are two independent sub-sections: choosing cards for the rules must not
        decide how the log is drawn."""
        src = _strip_comments(_read(VIEWS))
        assert '_EVR_VIEW_KEY' in src and '_EVL_VIEW_KEY' in src
        assert src.count('localStorage.setItem(_EVR_VIEW_KEY') == 1
        assert src.count('localStorage.setItem(_EVL_VIEW_KEY') == 1


class TestOneChannelVocabulary:

    def test_the_icon_map_exists_once(self):
        """It used to be two literals — the rules table and the modal — and the copy in the
        table had already lost `msteams`, so a Teams rule drew the generic bell."""
        assert _strip_comments(_read(VIEWS)).count('_EV_CH_ICON = {') == 1
        for name, path in (('render', RENDER), ('modal', MODAL),
                           ('rule views', V_RULES), ('log views', V_LOG)):
            body = _strip_comments(_read(path))
            assert "'bi-telegram'" not in body, f'{name} declares its own channel icons again'

    def test_every_declared_channel_has_an_icon(self):
        src = _strip_comments(_read(VIEWS))
        m = re.search(r'_EV_CH_ICON = \{(.*?)\}', src, re.S)
        assert m
        for ch in ('telegram', 'email', 'msteams', 'webhook'):
            assert ch in m.group(1), f'{ch} has no icon'

    def test_the_log_splits_the_channel_string_in_one_place(self):
        """The backend stores them as one string; a view doing its own split is a view that
        can disagree about what counts as a channel."""
        assert 'function _evLogChannels' in _strip_comments(_read(VIEWS))
        body = _strip_comments(_read(V_LOG))
        assert '.split(' not in body, 'a log view splits the channel string itself'


class TestDeliveryHasThreeStates:

    def test_never_fired_is_not_folded_into_ok(self):
        """A rule that has never fired is not a success: it is either a gap in the alerting or
        dead configuration, and a boolean would have to call it fine."""
        body = _fn(_strip_comments(_read(VIEWS)), '_evRuleDelivery')
        assert "'never'" in body and "'failed'" in body and "'ok'" in body
        assert 'r.last_fired' in body and 'r.last_ok' in body

    def test_the_buckets_are_ordered_worst_first(self):
        """…and "never" above "ok": an unanswered question buried under the working rules is
        an unanswered question nobody reads."""
        body = _strip_comments(_read(V_RULES))
        assert "['failed', 'never', 'ok']" in body

    def test_a_rule_with_no_channel_is_called_out(self):
        """It matches, it fires, and it reaches nobody. Left as an empty cell it reads like
        any other row."""
        body = _strip_comments(_read(V_RULES))
        assert 'evr_no_channel' in body
        assert 'none.length' in body, 'the no-channel group is no longer built'

    def test_the_channel_groups_are_not_claimed_to_partition(self):
        """A rule with two channels appears under both — the view answers "what does THIS
        channel carry". The header states the rule count so the difference cannot read as a
        miscount."""
        body = _fn(_strip_comments(_read(V_RULES)), '_evrViewChannels')
        assert "_evChip('bi-bell', t('evr_count_rules'), rows.length)" in body


class TestTheLogSummariesCountTheSameThing:

    def test_both_share_the_cells(self):
        """"Failures" must mean the same thing per rule and per channel."""
        body = _strip_comments(_read(V_LOG))
        assert body.count('function _evlSummaryCells') == 1
        assert body.count('_evlSummaryCells(') == 3     # the definition + both callers

    def test_the_last_send_carries_its_own_outcome(self):
        """12 failures out of 300 ending green is a transport that recovered; the same numbers
        ending red is one that is down right now."""
        body = _fn(_strip_comments(_read(V_LOG)), '_evlSummaryCells')
        assert '_evStatusBadge(a.lastOk)' in body

    def test_the_shell_is_told_which_columns_to_draw(self):
        """Deciding a column by comparing translated header text would drop it in whichever
        language happened to translate two headers alike."""
        body = _fn(_strip_comments(_read(V_LOG)), '_evlSummaryTable')
        assert 'hideChannels ?' in body
        assert "=== t(" not in body

    def test_the_timeline_does_not_re_sort(self):
        body = _strip_comments(_read(V_LOG))
        assert '.sort(' not in _fn(body, '_evlViewTimeline')

    def test_the_timestamps_are_seconds_and_converted_in_one_place(self):
        """`ts` and `last_fired` are unix SECONDS. A view that forgot to multiply would draw
        January 1970 and look like a data problem."""
        src = _strip_comments(_read(VIEWS))
        assert 'function _evMs' in src
        assert '_dayKeyLocal(_evMs(ts))' in _fn(src, '_evDayKey')
        assert 'new Date(' not in _strip_comments(_read(V_LOG)), \
            'a log view builds its own Date instead of using the shared helpers'


class TestTheSwitcherItselfIsShared:
    """Six sections draw this button group. It was six copies of the same markup, which is
    six places for the same control to end up a different size."""

    def test_the_helper_exists_and_is_registry_driven(self):
        body = _fn(_strip_comments(_read(UTILS)), '_viewSwitcher')
        assert 'views.map(' in body
        assert 'aria-pressed' in body

    def test_every_section_composes_it(self):
        for rel, reg in (('status/_views.html', 'STATUS_VIEWS'),
                         ('modules/_views.html', 'MOD_VIEWS'),
                         ('services/_views.html', 'SERVICE_VIEWS'),
                         ('credentials/_views.html', 'CREDENTIAL_VIEWS'),
                         ('audit/_views.html', 'AUDIT_VIEWS'),
                         ('core/_module_page_views.html', 'MP_VIEWS'),
                         ('events/_views.html', 'EVENT_RULE_VIEWS'),
                         ('events/_views.html', 'EVENT_LOG_VIEWS')):
            src = _strip_comments(_read(os.path.join(TPL, 'partials', *rel.split('/'))))
            assert f'_viewSwitcher({reg}' in src, f'{rel} draws its own switcher again'


class TestTheLabelsExist:

    def test_every_view_is_named_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('evr_view_table', 'evr_view_cards', 'evr_view_channels',
                        'evr_view_delivery', 'evl_view_table', 'evl_view_timeline',
                        'evl_view_rules', 'evl_view_channels'):
                assert f"'{key}':" in src, f'{lang} does not name {key}'

    def test_the_vocabulary_exists_in_both_languages(self):
        for lang in ('en_EN', 'es_ES'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', f'{lang}.py'))
            for key in ('evr_no_channel', 'evr_count_rules', 'evr_count_channels',
                        'evr_delivery_failed', 'evr_delivery_never', 'evr_delivery_ok',
                        'evr_delivery_failed_hint', 'evr_delivery_never_hint',
                        'evr_delivery_ok_hint', 'evl_count_sends', 'evl_count_rules',
                        'evl_count_failing', 'evl_col_sends', 'evl_col_failures',
                        'evl_col_last'):
                assert f"'{key}':" in src, f'{lang} is missing {key}'
