#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the Flask-independent SCIM provider helpers
(lib.providers.scim.service). The end-to-end HTTP behaviour is covered by
test_wa_scim.py; this exercises the pure functions directly."""

from lib.providers.scim import bearer_token_ok, parse_filter_eq
from lib.providers.scim.service import scim_user_fields


class TestBearerTokenOk:
    def test_valid(self):
        assert bearer_token_ok('Bearer secrettoken_0123456789', 'secrettoken_0123456789', 16)

    def test_wrong_token(self):
        assert not bearer_token_ok('Bearer nope0123456789abc', 'secrettoken_0123456789', 16)

    def test_missing_prefix(self):
        assert not bearer_token_ok('secrettoken_0123456789', 'secrettoken_0123456789', 16)

    def test_token_below_min_len_denied(self):
        # A too-short configured token is rejected even if it matches (weak-token floor).
        assert not bearer_token_ok('Bearer short', 'short', 16)

    def test_empty(self):
        assert not bearer_token_ok('', '', 16)


class TestParseFilterEq:
    def test_quoted(self):
        assert parse_filter_eq('userName eq "bob"', 'userName') == 'bob'

    def test_single_quoted(self):
        assert parse_filter_eq("userName eq 'bob'", 'userName') == 'bob'

    def test_case_insensitive_attr(self):
        assert parse_filter_eq('USERNAME eq "x"', 'userName') == 'x'

    def test_no_match(self):
        assert parse_filter_eq('displayName eq "x"', 'userName') is None
        assert parse_filter_eq('', 'userName') is None
        assert parse_filter_eq(None, 'userName') is None


class TestScimUserFields:
    def test_primary_email_and_name(self):
        email, name, active = scim_user_fields({
            'displayName': 'Jane',
            'emails': [{'value': 'a@x.com'}, {'value': 'p@x.com', 'primary': True}],
            'active': True})
        assert email == 'p@x.com' and name == 'Jane' and active is True

    def test_name_formatted_fallback_and_inactive(self):
        email, name, active = scim_user_fields({'name': {'formatted': 'N'}, 'active': False})
        assert email == '' and name == 'N' and active is False

    def test_active_defaults_true(self):
        _e, _n, active = scim_user_fields({'userName': 'x'})
        assert active is True
