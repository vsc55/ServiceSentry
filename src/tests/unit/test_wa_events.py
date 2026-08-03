#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the event-rules manager: CRUD API + matching/dispatch.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_events.py`` lives in ``tests/integration/test_wa_events.py``."""


import pytest


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


