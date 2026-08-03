#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the shared Microsoft API layer (lib/providers/entraid + lib/providers/azure).

This layer now carries the transport for BOTH the m365 and azure watchfuls, so a bug here
is a bug in two modules at once — and the modules' own tests stub it out, which is exactly
why it needs tests of its own.
"""

import json
from unittest.mock import patch

import pytest

from lib.providers.azure.arm import ARM_BASE, ARM_SCOPE, ArmApi
from lib.providers.entraid.client import GRAPH_SCOPE, EntraApiError, api_error
from lib.providers.entraid.graph_api import EntraApi, parse_dt, q, qs


class TestApiError:
    """One extractor for three answer shapes: getting this wrong turns a real reason
    ('invalid client secret') into a useless 'HTTP 400: Bad Request'."""

    def test_the_graph_shape(self):
        assert api_error(json.dumps({'error': {'message': 'Item not found'}})) == 'Item not found'

    def test_the_arm_shape_falls_back_to_the_code(self):
        """ARM often sends only a code, and 'AuthorizationFailed' is the whole answer:
        the app has no RBAC role. Dropping it would leave the operator with nothing."""
        assert api_error(json.dumps({'error': {'code': 'AuthorizationFailed'}})) == 'AuthorizationFailed'

    def test_the_token_endpoint_shape(self):
        aadsts = 'AADSTS7000215: Invalid client secret provided.'
        assert api_error(json.dumps({'error': 'invalid_client',
                                     'error_description': aadsts})) == aadsts

    def test_a_bare_error_code_is_better_than_nothing(self):
        assert api_error(json.dumps({'error': 'invalid_request'})) == 'invalid_request'

    def test_a_non_json_body_gives_nothing_rather_than_html(self):
        """The caller falls back to the HTTP reason. Returning the body would paste a
        proxy's HTML error page into an alert message."""
        assert api_error('<html>502 Bad Gateway</html>') == ''
        assert api_error('') == ''
        assert api_error(json.dumps([1, 2, 3])) == ''

    def test_the_message_is_bounded(self):
        assert len(api_error(json.dumps({'error': {'message': 'x' * 5000}}))) == 200


class TestEncoding:
    """The module learnt this in production: an unencoded space in a query value makes
    urllib refuse the URL outright ('URL can't contain control characters')."""

    def test_a_space_survives_as_an_escape(self):
        assert qs({'queryStartTime': '2026-01-01 00:00:00'}) == \
            'queryStartTime=2026-01-01+00%3A00%3A00'

    def test_a_path_segment_is_fully_escaped(self):
        assert q('a/b c') == 'a%2Fb%20c'

    def test_a_blank_path_segment_is_empty_not_none(self):
        assert q(None) == ''


class TestParseDt:
    def test_a_graph_timestamp_becomes_aware(self):
        dt = parse_dt('2027-01-15T10:20:30Z')
        assert dt is not None and dt.tzinfo is not None

    def test_a_naive_timestamp_is_assumed_utc(self):
        """Subtracting a naive datetime from an aware 'now' raises TypeError, which would
        take a whole expiry check down over a missing 'Z'."""
        dt = parse_dt('2027-01-15T10:20:30')
        assert dt is not None and dt.tzinfo is not None

    @pytest.mark.parametrize('bad', ['', None, 'not a date', '2027-13-45'])
    def test_an_unparseable_value_is_none_not_an_exception(self, bad):
        assert parse_dt(bad) is None


class TestToken:
    def test_the_scope_defaults_to_graph(self):
        seen = {}

        def fake(url, **kw):
            seen.update(kw.get('data') or {})
            return 200, json.dumps({'access_token': 'tok'})

        with patch.object(EntraApi, '_request', side_effect=fake):
            assert EntraApi._get_token('t', 'c', 's', 10) == 'tok'
        assert seen['scope'] == GRAPH_SCOPE
        assert seen['grant_type'] == 'client_credentials'

    def test_an_answer_with_no_token_is_an_error_carrying_the_reason(self):
        body = json.dumps({'error': 'invalid_client', 'error_description': 'AADSTS7000215'})
        with patch.object(EntraApi, '_request', return_value=(200, body)):
            with pytest.raises(EntraApiError) as exc:
                EntraApi._get_token('t', 'c', 's', 10)
        assert 'AADSTS7000215' in exc.value.msg

    def test_the_tenant_is_escaped_into_the_path(self):
        seen = []
        with patch.object(EntraApi, '_request',
                          side_effect=lambda url, **kw: seen.append(url) or
                          (200, json.dumps({'access_token': 't'}))):
            EntraApi._get_token('ten ant/x', 'c', 's', 10)
        assert 'ten%20ant%2Fx' in seen[0]


class TestPaging:
    """Graph pages at 100 and ARM pages large result sets: a single-page read reports a
    slice of the answer, which is the one thing a monitoring check must never do."""

    def test_graph_next_links_are_followed(self):
        pages = [json.dumps({'value': [{'id': 'a'}], '@odata.nextLink': 'https://next/2'}),
                 json.dumps({'value': [{'id': 'b'}]})]
        with patch.object(EntraApi, '_request',
                          side_effect=[(200, p) for p in pages]) as req:
            out = EntraApi._paged('tok', '/applications', 10)
        assert [o['id'] for o in out] == ['a', 'b']
        assert req.call_args_list[1][0][0] == 'https://next/2'

    def test_arm_uses_its_own_next_key(self):
        """ARM says 'nextLink' where Graph says '@odata.nextLink'. Using the Graph key
        against ARM silently stops after page one."""
        pages = [json.dumps({'value': [{'id': 'a'}], 'nextLink': ARM_BASE + '/p2'}),
                 json.dumps({'value': [{'id': 'b'}]})]
        with patch.object(ArmApi, '_request', side_effect=[(200, p) for p in pages]):
            out = ArmApi._arm_paged('tok', '/subscriptions/s/resources', 10)
        assert [o['id'] for o in out] == ['a', 'b']

    def test_a_runaway_next_link_cannot_spin_forever(self):
        loop = json.dumps({'value': [{'id': 'x'}], '@odata.nextLink': 'https://same'})
        with patch.object(EntraApi, '_request', return_value=(200, loop)) as req:
            out = EntraApi._paged('tok', '/x', 10, max_pages=3)
        assert len(out) == 3 and req.call_count == 3

    def test_non_dict_entries_are_skipped(self):
        body = json.dumps({'value': [{'id': 'a'}, 'junk', None, {'id': 'b'}]})
        with patch.object(EntraApi, '_request', return_value=(200, body)):
            out = EntraApi._paged('tok', '/x', 10)
        assert [o['id'] for o in out] == ['a', 'b']


class TestBatch:
    """Per-object questions about a tenant are N requests, and N sequential round-trips is
    how a check times out on a large one. $batch takes 20 at a time."""

    @staticmethod
    def _answer(*ids, status=200):
        return (200, json.dumps({'responses': [{'id': str(i), 'status': status,
                                                'body': {'n': i}} for i in ids]}))

    def test_the_answers_come_back_keyed_by_the_path_that_asked(self):
        with patch.object(EntraApi, '_request', return_value=self._answer(0, 1)):
            out = EntraApi._graph_batch('tok', ['/sites/a/drive', '/sites/b/drive'], 10)
        assert out == {'/sites/a/drive': {'n': 0}, '/sites/b/drive': {'n': 1}}

    def test_more_than_twenty_is_split_into_several_requests(self):
        """Graph rejects a 21st sub-request outright, so the chunking is not an optimisation."""
        paths = [f'/p{i}' for i in range(45)]
        with patch.object(EntraApi, '_request', side_effect=[
                self._answer(*range(20)), self._answer(*range(20)),
                self._answer(*range(5))]) as req:
            out = EntraApi._graph_batch('tok', paths, 10)
        assert req.call_count == 3
        assert len(out) == 45
        assert [len(c[1]['json_body']['requests']) for c in req.call_args_list] == [20, 20, 5]

    def test_one_forbidden_object_does_not_cost_the_batch(self):
        """A site that 404s or is denied is dropped from the result — the other nineteen
        answers are the point of asking."""
        body = json.dumps({'responses': [{'id': '0', 'status': 403, 'body': {'error': 1}},
                                         {'id': '1', 'status': 200, 'body': {'n': 1}}]})
        with patch.object(EntraApi, '_request', return_value=(200, body)):
            out = EntraApi._graph_batch('tok', ['/a', '/b'], 10)
        assert out == {'/b': {'n': 1}}

    def test_an_out_of_range_or_unparseable_id_is_ignored(self):
        body = json.dumps({'responses': [{'id': 'x', 'status': 200, 'body': {}},
                                         {'id': '9', 'status': 200, 'body': {}}]})
        with patch.object(EntraApi, '_request', return_value=(200, body)):
            assert EntraApi._graph_batch('tok', ['/a'], 10) == {}

    def test_nothing_to_ask_is_no_request_at_all(self):
        with patch.object(EntraApi, '_request') as req:
            assert EntraApi._graph_batch('tok', [], 10) == {}
        assert not req.called


class TestArm:
    def test_arm_is_a_different_audience_from_graph(self):
        """The classic Azure failure: every Graph permission granted, every ARM call
        still 403, because the token was issued for the wrong audience."""
        assert ARM_SCOPE != GRAPH_SCOPE
        assert 'management.azure.com' in ARM_SCOPE

    def test_an_arm_read_goes_to_the_arm_base(self):
        seen = []
        with patch.object(ArmApi, '_request',
                          side_effect=lambda url, **kw: seen.append(url) or (200, '{}')):
            ArmApi._arm_json('tok', '/subscriptions/s', 10)
        assert seen == [ARM_BASE + '/subscriptions/s']

    def test_the_bearer_token_is_sent(self):
        seen = {}
        with patch.object(ArmApi, '_request',
                          side_effect=lambda url, **kw: seen.update(kw) or (200, '{}')):
            ArmApi._arm_json('tok-123', '/x', 10)
        assert seen['headers']['Authorization'] == 'Bearer tok-123'

    def test_an_empty_body_is_an_empty_dict_not_a_crash(self):
        with patch.object(ArmApi, '_request', return_value=(200, '')):
            assert ArmApi._arm_json('tok', '/x', 10) == {}
