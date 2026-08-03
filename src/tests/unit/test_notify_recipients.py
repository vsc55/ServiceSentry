#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recipient token resolution (email | user:<uid> | group:<uid>) + suggest endpoint."""

from tests.conftest import _login


def _mk_group(client, name):
    return (client.post('/api/v1/groups', json={'name': name}).get_json() or {}).get('uid', '')


def _mk_user(admin, username, email, group_uids, enabled=True):
    # uid defaults to the username in the store, so tokens are `user:<username>` here.
    admin._users_store.upsert(username, {
        'email': email, 'enabled': enabled, 'role': 'viewer', 'groups': list(group_uids),
    })






class TestDispatchNoFallback:
    def test_empty_explicit_list_does_not_fall_back_to_raw_tokens(self):
        """A resolved empty list must NOT fall back to the raw config (which could mail a
        literal `group:`/`user:` token)."""
        from lib.core.notify.email import notify as email_notify
        cfg = {'enabled': True, 'provider': 'smtp', 'recipients': 'group:zzz'}
        ok, msg = email_notify._dispatch(cfg, subject='s', body_html='<b>x</b>', recipients=[])
        assert ok is False and 'recipient' in msg.lower()
