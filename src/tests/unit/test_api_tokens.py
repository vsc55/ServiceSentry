#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The token primitives, on their own: shape, hashing, expiry, and the intersection.

`lib.core.apitokens.service` imports no Flask on purpose, so the two properties the whole
feature rests on can be checked without an app in the way:

* a token is **intersected** with its owner's current permissions on every request, so it can
  never outgrow the account and demoting the account demotes the token at the same instant;
* `'*'` means "whatever the owner has", not "everything" — the same statement written so that
  it stays true after a role changes.
"""

import pytest

from lib.core.apitokens import service as S


class TestTheShape:

    def test_a_minted_token_parses_back(self):
        raw, token_id, token_hash = S.mint()
        assert raw.startswith(S.PREFIX)
        assert S.parse(raw) == (token_id, raw.split('_', 2)[2])
        assert S.matches(raw.split('_', 2)[2], token_hash)

    def test_two_tokens_are_not_the_same_token(self):
        assert len({S.mint()[0] for _ in range(50)}) == 50

    def test_the_marker_is_there_so_a_leaked_token_is_recognisable(self):
        """The reason GitHub and Stripe prefix theirs: a secret-scanning rule can be written
        for a token found in a log, a shell history or a commit."""
        assert S.mint()[0].startswith('sst_')

    @pytest.mark.parametrize('raw', [
        '', None, 'hunter2', 'Bearer sst_abc_def', 'sst_', 'sst_abc', 'sst__x',
        'sst_' + 'a' * 11 + '_' + 'b' * 48,      # id one char short
        'sst_' + 'a' * 12 + '_' + 'b' * 47,      # secret one char short
    ])
    def test_what_is_not_a_token_costs_one_string_check(self, raw):
        """Shape is judged before the database is touched: a value that is not one of ours
        should not become a query, let alone a row."""
        assert S.parse(raw) == ('', '')

    def test_the_hash_is_not_the_secret(self):
        raw, _tid, token_hash = S.mint()
        secret = raw.split('_', 2)[2]
        assert token_hash != secret and len(token_hash) == 64

    def test_a_wrong_secret_does_not_match(self):
        _raw, _tid, token_hash = S.mint()
        assert not S.matches('0' * 48, token_hash)
        assert not S.matches('', token_hash)


class TestExpiry:

    @staticmethod
    def _at(minutes):
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    def test_no_expiry_is_not_an_expired_one(self):
        assert S.is_expired('') is False

    def test_future_and_past(self):
        assert S.is_expired(self._at(10)) is False
        assert S.is_expired(self._at(-10)) is True

    def test_an_unreadable_date_counts_as_expired(self):
        """Failing closed is the only safe direction: the other way, a token whose expiry was
        written wrong lives forever."""
        assert S.is_expired('whenever') is True

    def test_a_naive_timestamp_does_not_raise(self):
        """Comparing naive to aware raises, and this runs on every API request."""
        from datetime import datetime, timedelta
        assert S.is_expired((datetime.utcnow() + timedelta(minutes=10)).isoformat()) is False


class TestThePermissionIntersection:

    OWNER = frozenset({'users_view', 'config_view', 'checks_run'})

    def test_a_token_is_capped_by_its_owner(self):
        """The whole security model in one assertion: what the token asked for AND what the
        account can still do."""
        stored = S.encode_permissions(['users_view', 'config_edit'])
        assert S.effective(stored, self.OWNER) == frozenset({'users_view'})

    def test_demoting_the_owner_narrows_the_token_at_once(self):
        stored = S.encode_permissions(['users_view', 'checks_run'])
        assert S.effective(stored, frozenset({'users_view'})) == frozenset({'users_view'})

    def test_star_means_whatever_the_owner_has_not_everything(self):
        assert S.effective(S.ALL, self.OWNER) == self.OWNER
        assert S.effective(S.ALL, frozenset()) == frozenset()

    def test_a_token_of_an_account_with_nothing_can_do_nothing(self):
        stored = S.encode_permissions(['users_view'])
        assert S.effective(stored, frozenset()) == frozenset()

    def test_unreadable_stored_permissions_grant_nothing(self):
        """A row somebody edited by hand must fail closed, not open."""
        assert S.effective('{not json', self.OWNER) == frozenset()
        assert S.effective('"users_view"', self.OWNER) == frozenset()

    def test_encoding_is_stable_and_deduplicated(self):
        assert S.encode_permissions(['b', 'a', 'a']) == '["a", "b"]'
        assert S.encode_permissions([]) == '[]'
        assert S.encode_permissions(S.ALL) == S.ALL


class TestWhatTheApiReports:

    def test_public_never_carries_the_hash_or_the_token(self):
        row = {'uid': 'u1', 'name': 'ci', 'token_id': 'abc', 'token_hash': 'DEADBEEF',
               'permissions': '["users_view"]', 'expires_at': '', 'last_used': '',
               'revoked': 0, 'created': 'x', 'created_by': 'me'}
        out = S.public(row)
        assert 'token_hash' not in out and 'token' not in out
        assert 'DEADBEEF' not in str(out)
        assert out['permissions'] == ['users_view']

    def test_a_name_is_trimmed_and_bounded(self):
        assert S.validate_name('  ci  ') == 'ci'
        assert len(S.validate_name('x' * 500)) == S.MAX_NAME_LEN
        assert S.validate_name(None) == ''
