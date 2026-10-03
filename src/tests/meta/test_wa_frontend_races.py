#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Late answers, and links into Configuration that point at what no longer exists.

Two families of front-end bug that no Python test sees and the screen only shows sometimes:

* An async load that paints whatever it gets back, without asking whether the thing it was
  asked for is still the thing on screen. Open device A, then B before A answers, and A paints
  over B; pick history series B while A is in flight and A's points sit under B's title; a
  live syslog poll lands after the filtered request and the rows stop matching the chips.
  Each loader below captures what it asked for (or a sequence ticket) BEFORE the await and
  drops the answer when it has been superseded.

* Links into Configuration that drove its old sub-tabs (`_activeCfgTab`, a `cfg_active_tab`
  key, `#cfg-tab-…-btn` buttons). Configuration is a rail of sections now; those links opened
  whichever section was open last, and scrolled to a field inside a hidden card. They go
  through `openConfigField`, which picks the section that holds the option first.

Plus two bugs in the cluster Logs tab: a trailing comment that swallowed two keys of its state
object, and "All" rows sent as `limit=0`, which the API reads as its own default of 200.
"""

import os
import re

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
PARTIALS = os.path.join(TPL, 'partials')


def _p(*parts):
    return _read(os.path.join(PARTIALS, *parts))


def _code(src):
    """Only code, trailing `//` comments included — `_strip_comments` keeps those, and one of
    them is precisely what hid two keys of an object literal."""
    src = _strip_comments(src)
    return re.sub(r'(?<![:\'"`\\])//[^\n]*', '', src)


def _all_partials():
    for root, _dirs, files in os.walk(PARTIALS):
        for f in files:
            if f.endswith('.html'):
                yield os.path.join(root, f)


class TestInfraDeviceIgnoresALateAnswer:
    """`_infraOpenView` / `_infraReload` must not paint a device that is no longer open."""

    def _src(self):
        return _p('infra', '_render.html')

    def test_open_view_captures_the_uid_before_the_await(self):
        body = _code(_fn(self._src(), '_infraOpenView'))
        assert 'const uid = _infraDevice;' in body
        assert body.index('const uid = _infraDevice;') < body.index('await apiGet')
        assert 'encodeURIComponent(uid)' in body

    def test_open_view_drops_the_answer_when_another_device_opened(self):
        body = _code(_fn(self._src(), '_infraOpenView'))
        guard = body.index('if (_infraDevice !== uid) return;')
        assert body.index('await apiGet') < guard < body.index('_infraDetail = data;'), (
            'the payload is stored before checking the device is still the one open')

    def test_reload_drops_the_answer_when_another_device_opened(self):
        body = _code(_fn(self._src(), '_infraReload'))
        assert body.index('const uid = _infraDevice;') < body.index('await apiGet')
        guard = body.index('if (_infraDevice !== uid) return;')
        assert body.index('await apiGet') < guard < body.index('_infraDetail = data;')


class TestHistoryIgnoresASupersededLoad:
    """Single chart and compare overlay share one sequence: only the newest load paints."""

    def test_the_chart_takes_a_ticket_and_checks_it_after_the_await(self):
        src = _p('history', '_render.html')
        assert re.search(r'^let _historyLoadSeq = 0;', src, re.M)
        body = _code(_fn(src, '_historyLoadChart'))
        assert body.index('const seq = ++_historyLoadSeq;') < body.index('await apiGet')
        guard = body.index('if (seq !== _historyLoadSeq) return;')
        assert body.index('await apiGet') < guard < body.index('_historyPoints     =')

    def test_compare_uses_the_same_sequence(self):
        body = _code(_fn(_p('history', '_compare.html'), '_historyLoadCompare'))
        assert body.index('const seq = ++_historyLoadSeq;') < body.index('await Promise.all')
        guard = body.index('if (seq !== _historyLoadSeq) return;')
        assert body.index('await Promise.all') < guard < body.index('_historyCompareData = results')

    def test_the_placeholder_cancels_a_load_in_flight(self):
        body = _code(_fn(_p('history', '_series.html'), '_historyShowPlaceholder'))
        assert '_historyLoadSeq++' in body


class TestSyslogIgnoresASupersededLoad:

    def test_load_syslog_takes_a_ticket_and_checks_it_before_painting(self):
        src = _p('syslog', '_poll.html')
        assert re.search(r'^let _syslogLoadSeq = 0;', src, re.M)
        body = _code(_fn(src, '_loadSyslog'))
        assert body.index('const seq = ++_syslogLoadSeq;') < body.index('await Promise.all')
        guard = body.index('if (seq !== _syslogLoadSeq) return;')
        assert body.index('await Promise.all') < guard < body.index('_slRowsData = msgs;')


class TestLinksIntoConfigurationUseTheRail:

    def test_no_partial_drives_the_old_config_sub_tabs(self):
        dead = re.compile(r'_activeCfgTab|cfg_active_tab|cfg-tab-[\w-]*-btn')
        hits = [os.path.relpath(p, PARTIALS) for p in _all_partials()
                if dead.search(_strip_comments(_read(p)))]
        assert not hits, f'the old config sub-tab mechanism is still used in: {hits}'

    def test_open_config_field_picks_the_card_then_reveals(self):
        body = _code(_fn(_p('cfg', '_views.html'), 'openConfigField'))
        assert body.index('_cfgCardOfPath(') < body.index('setConfigRailCard(')
        assert '_cfgRevealField(path)' in body
        # The tab's own handler redraws on arrival; the reveal must survive that redraw.
        assert "'shown.bs.tab'" in body and 'MutationObserver' in body

    def test_the_card_comes_from_the_layout_first(self):
        body = _code(_fn(_p('cfg', '_views.html'), '_cfgCardOfPath'))
        assert '(cd.fields || []).includes(path)' in body

    def test_the_syslog_link_goes_to_allowed_sources(self):
        body = _code(_fn(_p('syslog', '_drops.html'), '_gotoSyslogConfig'))
        assert "openConfigField('syslog|allowed_sources')" in body

    def test_the_update_detail_link_goes_through_the_rail(self):
        src = _p('core', '_polling.html')
        body = _code(_fn(src, '_goCfgField'))
        assert 'openConfigField(pathStr, sec)' in body
        assert 'jsStr(item.sec)' in src, 'a list row has no path: its section must travel too'


class TestClusterLogsTab:

    def test_the_state_declares_severity_max_and_q(self):
        body = _code(_fn(_p('clusters', '_modal.html'), '_clRenderLogs'))
        state = body[body.index('_clLogsState = {'):]
        state = state[:state.index('};')]
        assert re.search(r"\bseverity_max:\s*''", state), 'severity_max is not in the state'
        assert re.search(r"\bq:\s*''", state), 'q is not in the state'

    def test_all_rows_is_not_sent_as_limit_zero(self):
        body = _code(_fn(_p('clusters', '_modal.html'), '_clLogsFetch'))
        assert 'const all = !st.pageSize;' in body
        assert 'limit: String(limit)' in body and 'limit: String(st.pageSize)' not in body
        assert 'all ? 0 : st.pageSize' in body, 'the pager is told the real page size for "All"'
