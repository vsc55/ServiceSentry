#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Access › Sessions › Activity — the view, and the four things that make a view exist.

A view in this panel is a line in its section's registry, a render function, an include in the
bundle, and — when it has data of its own — something that fetches it. Miss the include and the
switcher offers a view whose renderer is not defined; miss the fetch and it opens empty and
stays empty until somebody presses Refresh. Neither fails in a way a Python test would
otherwise notice.

The other half of this file is about the SHARED cells. There are four access-log tables now —
a token's history, the feed of every token's calls, and the same pair for sessions — and the
colour of a status is not decoration: a 401/403 among the 200s is the row an access review
exists to find. Four copies of that rule would drift, and the copy that stopped separating
"refused" from "broken" would look perfectly fine on its own.
"""

import os

from tests.helpers import _fn, _read, _strip_comments

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
SES = os.path.join(TPL, 'partials', 'sessions')
VIEWS = os.path.join(SES, '_views.html')
ACTIVITY = os.path.join(SES, '_view_activity.html')
LIST = os.path.join(SES, '_list.html')
BUNDLE = os.path.join(TPL, 'partials', '_js_sections.html')
ACCESS_LOG = os.path.join(TPL, 'partials', 'core', '_access_log.html')


class TestTheViewIsWired:

    def test_it_is_in_the_registry_as_a_summary(self):
        """`summary` and not `cards`: it is handed every session the filter strip left
        standing rather than the page on screen, so filtering to one account shows that
        account's traffic instead of the traffic of whoever landed on page 1."""
        src = _read(VIEWS)
        assert "id: 'activity'" in src, 'the view is not offered at all'
        assert "render: '_sesViewActivity'" in src
        assert "mode: 'summary'" in src

    def test_its_javascript_is_included(self):
        """A registry entry naming a function nobody defined is a switcher that throws."""
        assert 'partials/sessions/_view_activity.html' in _read(BUNDLE)

    def test_the_feed_is_fetched_only_by_the_view_that_needs_it(self):
        """It is the biggest thing this section fetches and three of the four views never
        look at it."""
        assert "_sesView.is('activity')" in _fn(_read(ACTIVITY), '_sesActivityLoad')

    def test_switching_to_it_loads_it(self):
        assert '_sesActivityLoad()' in _read(VIEWS), 'the view opens empty and stays empty'

    def test_the_poll_keeps_it_current(self):
        """The Refresh button and the 30 s poll of the Access tab both go through
        `refreshAccessData`, so the feed ages like everything else on the tab."""
        wiring = _read(os.path.join(TPL, 'partials', 'init', '_wiring.html'))
        assert '_sesActivityLoad();' in _fn(wiring, 'refreshAccessData')

    def test_it_says_what_it_does_not_record(self):
        """The rule is not everything, so a reader who is not told it would take an empty
        feed as "nothing happened" instead of "nothing recordable happened"."""
        src = _read(ACTIVITY)
        assert src.count('ses_access_rule') >= 3, (
            'the "acts and refusals only" note is missing from the feed, the empty state '
            'or the per-session dialog')


class TestTheRowActions:

    def test_the_history_button_is_one_function(self):
        """Drawn by the table and by the card grid. Two copies is one view free to offer an
        action the other does not, which is how a button ends up existing in a layout nobody
        uses."""
        src = _read(LIST)
        assert 'function _sesHistoryBtn(' in _read(ACTIVITY)
        assert src.count('_sesHistoryBtn(') == 2, 'the two bodies do not share the button'

    def test_reading_is_offered_to_whoever_may_see_the_list(self):
        """Reading what a session did is the `sessions_view` question; cutting it off is the
        `sessions_revoke` one. Gating the history behind revoke would hide the evidence from
        exactly the account that is allowed to look and not to act."""
        actions = _read(LIST)
        i = actions.index('actions: sid =>')
        line = actions[i:actions.index('\n', i)]
        assert '_sesHistoryBtn(sid)' in line
        assert line.index('_sesHistoryBtn') < line.index('_canRevokeSessions')


class TestTheStatusColoursAreDefinedOnce:

    def test_the_shared_cells_exist(self):
        src = _read(ACCESS_LOG)
        assert 'function _accessStatusBadge(' in src
        assert 'function _accessCallCell(' in src

    def test_it_is_included_before_anything_draws_a_table(self):
        assert 'partials/core/_access_log.html' in _read(BUNDLE)

    def test_no_table_paints_a_status_by_hand(self):
        """The regression this guard exists for: the first copy to stop telling 401/403 apart
        from a 500 would look right on its own and be wrong only beside the other three."""
        offenders = []
        for rel in ('sessions/_view_activity.html', 'apitokens/_views.html',
                    'account/_tokens.html'):
            src = _strip_comments(_read(os.path.join(TPL, 'partials', *rel.split('/'))))
            if 'r.status >= 500' in src or "r.status === 403" in src:
                offenders.append(rel)
        assert not offenders, f'a status band written by hand again in: {offenders}'

    def test_all_four_tables_use_them(self):
        """A shared helper nobody calls is not shared, it is dead."""
        callers = 0
        for rel in ('sessions/_view_activity.html', 'apitokens/_views.html',
                    'account/_tokens.html'):
            callers += _read(os.path.join(TPL, 'partials', *rel.split('/'))).count(
                '_accessStatusBadge(')
        assert callers >= 4, f'only {callers} of the four access-log tables use the shared cell'
