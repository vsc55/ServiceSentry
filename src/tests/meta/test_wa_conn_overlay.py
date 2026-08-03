#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""""Connection lost" must mean the connection is lost.

The overlay covers the whole panel, so a false one is not a cosmetic slip: it interrupts
whatever the user was doing to tell them something untrue, and it stays until the next probe
happens to succeed. It was firing on a single failure.

The mechanism read as if it were careful — "debounced (~1.2 s of continuous failure) so a
single blip doesn't flash it" — but nothing re-checked during that wait. One slow answer was
enough: a request that overran the 4 s heartbeat timeout because a worker was busy, a blip
while a laptop changes network. The timer only delayed the announcement; it never questioned
it.

Two changes, and the first is the one that matters:

* **a first failure asks again instead of announcing.** It triggers an immediate re-probe,
  and only a second consecutive failure raises the overlay. A real outage is barely slower to
  show, because the confirmation does not wait for the next heartbeat;
* **the confirmation waits longer.** The first probe's short timeout is tuned to notice a
  hanging backend; a merely busy one overruns it too, and "slow once" is not "gone".

Static guards over the polling partial, in the same spirit as the rest of the panel's UI
tests: what is pinned is that a single failure cannot paint the overlay, and that any success
clears the state completely.
"""

import io
import os
import re
from tests.helpers import _fn

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
POLL = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_polling.html')
API = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_api.html')


def _poll() -> str:
    return io.open(POLL, encoding='utf-8-sig').read()


class TestTheScanItself:

    def test_the_pieces_are_found(self):
        src = _poll()
        assert _fn(src, '_setConnLost') and _fn(src, '_connPing') and _fn(src, '_applyConnLost')


class TestOneFailureIsNotAnAnswer:

    def test_a_failure_is_counted_not_announced(self):
        """**The regression.** Without a counter, the first failure arms the overlay and the
        only thing standing between a blip and a full-screen "connection lost" is a timer
        that re-checks nothing."""
        body = _fn(_poll(), '_setConnLost')
        assert '_connFails++' in body, 'failures are no longer counted'
        assert re.search(r'_connFails\s*<\s*2', body), \
            'a single failure can paint the overlay again'

    def test_the_first_failure_triggers_a_re_probe(self):
        """Asking again is what makes the second failure mean something. Waiting for the next
        heartbeat instead would make a real outage several seconds slower to show."""
        body = _fn(_poll(), '_setConnLost')
        assert '_connPing(true)' in body

    def test_the_probe_is_reachable_from_there(self):
        """It used to be a const inside the init closure, so nothing outside could re-run it —
        which is why the confirmation had to be invented as a bare timer in the first place."""
        src = _poll()
        assert re.search(r'^async function _connPing\(', src, re.M), \
            '_connPing is scoped to the initialiser again'

    def test_the_confirmation_is_given_more_time(self):
        """A busy server overruns the first probe's budget too, and "slow once" is not
        "gone"."""
        body = _fn(_poll(), '_connPing')
        m = re.search(r'confirming \? (\d+) : (\d+)', body)
        assert m, 'the confirmation uses the same timeout as the first probe'
        assert int(m.group(1)) > int(m.group(2))


class TestSuccessClearsEverything:

    def test_a_success_resets_the_counter(self):
        """Otherwise two unrelated failures minutes apart would add up to an outage."""
        body = _fn(_poll(), '_setConnLost')
        head = body.split('_connFails++')[0]
        assert '_connFails = 0' in head

    def test_it_cancels_both_pending_timers(self):
        """A confirmation or a paint still queued from an earlier failure would fire after the
        server had already answered."""
        head = _fn(_poll(), '_setConnLost').split('_connFails++')[0]
        assert 'clearTimeout(_connConfirmTimer)' in head
        assert 'clearTimeout(_connShowTimer)' in head

    def test_hiding_is_immediate(self):
        """Only showing is guarded. A panel that is working must never look broken."""
        head = _fn(_poll(), '_setConnLost').split('_connFails++')[0]
        assert '_applyConnLost(false)' in head


class TestTheAuthoritativeSignalsStillBypassIt:

    def test_the_browser_going_offline_shows_it_at_once(self):
        """The browser knows there is no link; there is nothing to confirm."""
        assert "'offline', () => _applyConnLost(true)" in _poll()

    def test_a_gateway_error_still_counts_as_unreachable(self):
        """A proxy that is up while the backend is down answers 502/503/504 — a resolved
        response, not a rejection."""
        api = io.open(API, encoding='utf-8-sig').read()
        assert '_setConnLost(_connGatewayDown(r.status))' in api

    def test_an_abort_is_still_not_a_network_error(self):
        """A request cancelled by navigation is not the server going away."""
        api = io.open(API, encoding='utf-8-sig').read()
        assert "e.name !== 'AbortError'" in api
