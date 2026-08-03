#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the /status public status page and language priority logic.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_status.py`` lives in ``tests/integration/test_wa_status.py``."""

import os

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False



pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask not available")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_PASS = "secret"

# Absolute path to the watchfuls directory (used for pretty-name tests)
_WATCHFULS_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'watchfuls'
)


# ---------------------------------------------------------------------------
# TestPublicStatusPage — core status page behaviour
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TestStatusPageLanguage — 3-level language priority
#
# Priority order (highest → lowest):
#   1. User session lang  (set via /lang/<code> after login)
#   2. wa._STATUS_LANG    (status_lang constructor param / config UI)
#   3. wa._DEFAULT_LANG   (default_lang constructor param)
# ---------------------------------------------------------------------------



class TestStatusConnectivity:
    """A downed backend must be reported fast and must not corrupt the countdown.

    The refresh used to reset its countdown only once the request SETTLED and to flag the
    connection lost only from the catch. Behind a reverse proxy a downed backend leaves the
    request hanging until the browser's own (very long) timeout, so the 1 s ticker kept
    subtracting — the page showed "refreshing in -30s" — and the overlay took just as long.
    These pin the guards in the served page (the behaviour itself is browser-side)."""

    def _page(self, config_dir, var_dir):
        wa = WebAdmin(config_dir, "admin", "secret", var_dir, public_status=True,
                      pw_require_upper=False, pw_require_digit=False)
        wa.app.config["TESTING"] = True
        return wa.app.test_client().get("/status").data.decode()

    def test_refresh_is_time_capped(self, config_dir, var_dir):
        html = self._page(config_dir, var_dir)
        assert "AbortController" in html and "REFRESH_TIMEOUT_MS" in html, \
            'the body refresh can hang until the browser timeout'

    def test_countdown_holds_until_the_data_arrives(self, config_dir, var_dir):
        """The countdown measures time to the next refresh, so it may not restart the moment
        one is FIRED — only when that refresh has actually delivered data. It holds at zero
        meanwhile (and is clamped, so a stray tick can never render a negative)."""
        html = self._page(config_dir, var_dir)
        assert "Math.max(0, remaining)" in html, 'the countdown can render negative seconds'
        assert "if (_stBusy) return;" in html, 'the countdown keeps running during a refresh'
        # The only reset lives in the success path, after the body has been replaced.
        body = html.split("async function _stRefresh()")[1].split("setInterval")[0]
        assert body.count("remaining = REFRESH_SECS") == 1
        assert body.index("remaining = REFRESH_SECS") > body.index("status-body")

    def test_it_says_it_is_refreshing_while_it_runs(self, config_dir, var_dir):
        """Holding at "Refreshing in 0s" for the length of the request reads as a stuck page,
        so the phrase becomes "Refreshing…" until the data lands."""
        html = self._page(config_dir, var_dir)
        assert 'id="refresh-label"' in html, 'the countdown phrase cannot be swapped'
        assert "_stShowRefreshing()" in html

    def test_countdown_freezes_while_disconnected(self, config_dir, var_dir):
        """"Refreshing in Ns" is a promise the page cannot keep with the server gone, so the
        countdown stops and only restarts once a refresh actually brings data back. Something
        must still retry, or the page would never notice the server returning."""
        html = self._page(config_dir, var_dir)
        assert "if (_stLost) {" in html, 'the ticker keeps counting down while disconnected'
        assert "RETRY_SECS" in html, 'nothing retries while disconnected → never recovers'

    def test_no_extra_polling_beyond_the_refresh(self, config_dir, var_dir):
        """Deliberate: the page checks connectivity only when the countdown reaches zero.
        It is a public page, so the refresh it already makes is the only request it needs —
        the cost is that detection takes up to one status_refresh_secs."""
        html = self._page(config_dir, var_dir)
        assert "/api/v1/health" not in html, 'the status page added a separate heartbeat'
        assert html.count("setInterval") == 1, 'only the 1 s countdown ticker should be running'
