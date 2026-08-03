#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recipient token resolution (email | user:<uid> | group:<uid>) + suggest endpoint.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_notify_recipients.py`` lives in
``tests/integration/test_notify_recipients.py``."""



class TestDispatchNoFallback:
    def test_empty_explicit_list_does_not_fall_back_to_raw_tokens(self):
        """A resolved empty list must NOT fall back to the raw config (which could mail a
        literal `group:`/`user:` token)."""
        from lib.core.notify.email import notify as email_notify
        cfg = {'enabled': True, 'provider': 'smtp', 'recipients': 'group:zzz'}
        ok, msg = email_notify._dispatch(cfg, subject='s', body_html='<b>x</b>', recipients=[])
        assert ok is False and 'recipient' in msg.lower()
