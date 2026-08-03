#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the event-rules manager: CRUD API + matching/dispatch."""

from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

_DISP = 'lib.core.notify.notification_dispatcher.dispatch'
















class TestEventDetailStr:
    """The audit detail rendered into a notification body must be empty when there is
    no detail — an empty dict must NOT render as a literal "{}" (e.g. syslog_started
    audits with {})."""

    @pytest.mark.parametrize('detail,expected', [
        (None, ''),
        ('', ''),
        ({}, ''),
        ([], ''),
        ('boom', 'boom'),
        ({'deleted': 3}, '{"deleted": 3}'),
    ])
    def test_detail_str(self, detail, expected):
        from lib.services.events.manager import _EventsMixin
        assert _EventsMixin._event_detail_str(detail) == expected




