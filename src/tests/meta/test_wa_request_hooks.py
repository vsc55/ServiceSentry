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

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
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
