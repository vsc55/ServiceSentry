#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The order of the request lifecycle is load-bearing, so it is declared and checked.

Flask runs ``before_request`` handlers in REGISTRATION order. That order used to be the order
of five decorators down the middle of ``_create_app`` — true, security-critical, and written
down nowhere. Moving a block while tidying the file would have changed who guards what, and
nothing would have said so: every test still passes when the fail2ban gate runs third.

These guards make the order a thing you have to mean to change.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_request_hooks.py`` lives in ``tests/meta/test_wa_request_hooks.py``."""

import os
import sys

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# Los 5 tests leen `WebAdmin._BEFORE_REQUEST`, así que necesitan la clase — y eso arrastra
# Flask. Sin guarda, una instalación sin panel web se caía al colectar en vez de saltarlos.
try:
    from lib.web_admin.app import WebAdmin  # noqa: E402
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

import pytest  # noqa: E402

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


EXPECTED = (
    '_hook_ipban_gate',
    '_hook_trace_start',
    '_hook_refresh_caches',
    # Before CSRF, and that is the design rather than a detail: judging a request for CSRF
    # means knowing HOW it authenticated. A bearer call is not a browser being tricked into
    # posting — no cross-site page can attach an Authorization header — so the CSRF hook
    # returns early for one, and it can only do that if this one has already run.
    '_hook_api_token',
    '_hook_csrf_protect',
    '_hook_enforce_fqdn',
)


class TestTheOrderIsDeclared:

    def test_it_is_exactly_this(self):
        """Change the tuple deliberately and this line with it; do not let a refactor move a
        handler and discover the new order in production."""
        assert WebAdmin._BEFORE_REQUEST == EXPECTED

    def test_the_ban_gate_runs_first(self):
        """A banned address must reach nothing — not a cache refresh, not a redirect, not a
        login form. Anything registered before it is work done on behalf of someone who was
        supposed to be turned away at the door."""
        assert WebAdmin._BEFORE_REQUEST[0] == '_hook_ipban_gate'

    def test_csrf_is_judged_before_the_fqdn_redirect(self):
        """Both can end the request. If the redirect went first, a state-changing request that
        arrived on the wrong hostname would be bounced to a URL that drops its body — and the
        token it did carry would never be looked at."""
        order = WebAdmin._BEFORE_REQUEST
        assert order.index('_hook_csrf_protect') < order.index('_hook_enforce_fqdn')

    def test_the_caches_are_fresh_before_anything_authorises(self):
        """A CSRF rejection is audited against the user store, and every handler after these
        hooks authorises against roles and groups. Refreshing them afterwards would authorise
        against the previous process's idea of who exists."""
        order = WebAdmin._BEFORE_REQUEST
        assert order.index('_hook_refresh_caches') < order.index('_hook_csrf_protect')

    @pytest.mark.parametrize('name', EXPECTED)
    def test_every_declared_handler_exists(self, name):
        """A typo in the tuple would register nothing at all: `getattr` would raise at boot —
        loudly, which is right — but only for the handler that was misspelled."""
        assert callable(getattr(WebAdmin, name, None))


