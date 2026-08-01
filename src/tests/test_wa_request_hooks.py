#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The order of the request lifecycle is load-bearing, so it is declared and checked.

Flask runs ``before_request`` handlers in REGISTRATION order. That order used to be the order
of five decorators down the middle of ``_create_app`` — true, security-critical, and written
down nowhere. Moving a block while tidying the file would have changed who guards what, and
nothing would have said so: every test still passes when the fail2ban gate runs third.

These guards make the order a thing you have to mean to change.
"""

import os
import sys

import pytest

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lib.web_admin.app import WebAdmin  # noqa: E402


EXPECTED = (
    '_hook_ipban_gate',
    '_hook_trace_start',
    '_hook_refresh_caches',
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


class TestTheyAreActuallyRegistered:
    """Declaring the order is worth nothing if the registration stops reading the tuple."""

    def test_registration_walks_the_declared_order(self):
        import inspect
        src = inspect.getsource(WebAdmin._register_request_hooks)
        assert 'self._BEFORE_REQUEST' in src, \
            'the tuple is documentation only — the real order is somewhere else again'
        assert 'app.after_request(self._hook_trace_end)' in src
        assert 'app.teardown_request(self._hook_close_thread_db)' in src

    def test_the_app_registers_them_through_that_one_call(self):
        import inspect
        src = inspect.getsource(WebAdmin._create_app)
        assert 'self._register_request_hooks(app)' in src
        for gone in ('@app.before_request', '@app.after_request', '@app.teardown_request'):
            assert gone not in src, f'a hook is registered outside the declared order ({gone})'
