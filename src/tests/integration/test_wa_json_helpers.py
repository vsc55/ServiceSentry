#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for WebAdmin._require_json() and ._optional_json() helpers.

Both helpers must be called inside a Flask request context, so the
test suite registers two thin probe routes on the test app and drives
them through the test client.
"""

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


# ──────────────────────────── Fixtures ─────────────────────────────

@pytest.fixture()
def probed_client(admin):
    """Test client whose app has two extra probe routes.

    POST /probe/require  — calls wa._require_json() and echoes the result.
    POST /probe/optional — calls wa._optional_json() and echoes the result.
    """
    wa = admin
    app = wa.app
    app.config['TESTING'] = True

    @app.route('/probe/require', methods=['POST'])
    def probe_require():
        from flask import jsonify
        data, err = wa._require_json()
        if err:
            return err
        return jsonify({'received': data})

    @app.route('/probe/optional', methods=['POST'])
    def probe_optional():
        from flask import jsonify
        data = wa._optional_json()
        return jsonify({'received': data})

    return app.test_client()


# ─────────────────────────── _require_json ─────────────────────────

class TestRequireJson:
    """WebAdmin._require_json() — body is mandatory and must be a JSON object."""

    # ── happy path ──────────────────────────────────────────────────

    def test_valid_object_returns_200(self, probed_client):
        resp = probed_client.post('/probe/require', json={'key': 'val'})
        assert resp.status_code == 200

    def test_valid_object_echoed_back(self, probed_client):
        resp = probed_client.post('/probe/require', json={'a': 1, 'b': True})
        assert resp.get_json()['received'] == {'a': 1, 'b': True}

    def test_empty_object_accepted(self, probed_client):
        resp = probed_client.post('/probe/require', json={})
        assert resp.status_code == 200
        assert resp.get_json()['received'] == {}

    def test_nested_object_accepted(self, probed_client):
        payload = {'outer': {'inner': [1, 2, 3]}}
        resp = probed_client.post('/probe/require', json=payload)
        assert resp.get_json()['received'] == payload

    # ── rejected inputs — 400 ───────────────────────────────────────

    def test_no_body_returns_400(self, probed_client):
        resp = probed_client.post('/probe/require')
        assert resp.status_code == 400

    def test_malformed_json_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='{bad json', content_type='application/json'
        )
        assert resp.status_code == 400

    def test_null_body_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='null', content_type='application/json'
        )
        assert resp.status_code == 400

    def test_json_array_returns_400(self, probed_client):
        resp = probed_client.post('/probe/require', json=[1, 2, 3])
        assert resp.status_code == 400

    def test_json_string_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='"hello"', content_type='application/json'
        )
        assert resp.status_code == 400

    def test_json_integer_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='42', content_type='application/json'
        )
        assert resp.status_code == 400

    def test_json_float_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='3.14', content_type='application/json'
        )
        assert resp.status_code == 400

    def test_json_bool_true_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='true', content_type='application/json'
        )
        assert resp.status_code == 400

    def test_json_bool_false_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='false', content_type='application/json'
        )
        assert resp.status_code == 400

    def test_plain_text_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require', data='hello', content_type='text/plain'
        )
        assert resp.status_code == 400

    def test_wrong_content_type_returns_400(self, probed_client):
        resp = probed_client.post(
            '/probe/require',
            data='{"key": "val"}',
            content_type='text/plain',
        )
        assert resp.status_code == 400

    # ── error payload ───────────────────────────────────────────────

    def test_error_response_contains_error_key(self, probed_client):
        resp = probed_client.post('/probe/require', json=[])
        body = resp.get_json()
        assert 'error' in body

    def test_error_value_is_string(self, probed_client):
        body = probed_client.post('/probe/require', json=[]).get_json()
        assert isinstance(body['error'], str)

    def test_error_string_is_not_empty(self, probed_client):
        body = probed_client.post('/probe/require', json=[]).get_json()
        assert body['error']

    # ── return-value contract ────────────────────────────────────────

    def test_returns_two_tuple(self, admin, config_dir):
        """_require_json returns a 2-tuple in both success and failure paths."""
        app = admin.app
        results = {}

        @app.route('/probe/require/introspect', methods=['POST'])
        def probe_introspect():
            from flask import jsonify, request as req
            ret = admin._require_json()
            results['len'] = len(ret)
            results['types'] = [type(x).__name__ for x in ret]
            return jsonify({})

        with app.test_request_context(
            '/probe/require/introspect',
            method='POST',
            json={'x': 1},
            content_type='application/json',
        ):
            data, err = admin._require_json()
        assert data == {'x': 1}
        assert err is None

    def test_failure_path_returns_none_data(self, admin):
        app = admin.app
        with app.test_request_context(
            '/probe/require/introspect',
            method='POST',
            data='[]',
            content_type='application/json',
        ):
            data, err = admin._require_json()
        assert data is None
        assert err is not None

    def test_failure_err_is_tuple_of_two(self, admin):
        app = admin.app
        with app.test_request_context(
            '/',
            method='POST',
            data='[]',
            content_type='application/json',
        ):
            _, err = admin._require_json()
        assert isinstance(err, tuple)
        assert len(err) == 2

    def test_failure_err_second_element_is_400(self, admin):
        app = admin.app
        with app.test_request_context(
            '/',
            method='POST',
            data='null',
            content_type='application/json',
        ):
            _, err = admin._require_json()
        assert err[1] == 400


# ─────────────────────────── _optional_json ────────────────────────

class TestOptionalJson:
    """WebAdmin._optional_json() — body is optional; always returns a dict."""

    # ── always returns a dict ────────────────────────────────────────

    def test_valid_object_returned(self, probed_client):
        resp = probed_client.post('/probe/optional', json={'k': 'v'})
        assert resp.get_json()['received'] == {'k': 'v'}

    def test_empty_object_returned(self, probed_client):
        resp = probed_client.post('/probe/optional', json={})
        assert resp.get_json()['received'] == {}

    def test_no_body_returns_empty_dict(self, probed_client):
        resp = probed_client.post('/probe/optional')
        assert resp.status_code == 200
        assert resp.get_json()['received'] == {}

    def test_malformed_json_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='{bad', content_type='application/json'
        )
        assert resp.status_code == 200
        assert resp.get_json()['received'] == {}

    def test_null_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='null', content_type='application/json'
        )
        assert resp.get_json()['received'] == {}

    def test_array_returns_empty_dict(self, probed_client):
        resp = probed_client.post('/probe/optional', json=[1, 2])
        assert resp.get_json()['received'] == {}

    def test_string_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='"hi"', content_type='application/json'
        )
        assert resp.get_json()['received'] == {}

    def test_integer_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='99', content_type='application/json'
        )
        assert resp.get_json()['received'] == {}

    def test_float_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='1.5', content_type='application/json'
        )
        assert resp.get_json()['received'] == {}

    def test_bool_true_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='true', content_type='application/json'
        )
        assert resp.get_json()['received'] == {}

    def test_bool_false_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='false', content_type='application/json'
        )
        assert resp.get_json()['received'] == {}

    def test_plain_text_returns_empty_dict(self, probed_client):
        resp = probed_client.post(
            '/probe/optional', data='hello', content_type='text/plain'
        )
        assert resp.get_json()['received'] == {}

    def test_never_returns_400(self, probed_client):
        for body, ct in [
            ('null', 'application/json'),
            ('[]', 'application/json'),
            ('{bad', 'application/json'),
            ('', 'application/json'),
            ('hello', 'text/plain'),
        ]:
            resp = probed_client.post('/probe/optional', data=body, content_type=ct)
            assert resp.status_code == 200, f"Unexpected 4xx for body={body!r}"

    # ── return type contract ─────────────────────────────────────────

    def test_return_value_is_always_dict(self, admin):
        app = admin.app
        for raw, ct in [
            ('{"a":1}', 'application/json'),
            ('null', 'application/json'),
            ('[]', 'application/json'),
            ('{bad', 'application/json'),
            ('', 'text/plain'),
        ]:
            with app.test_request_context(
                '/', method='POST', data=raw, content_type=ct
            ):
                result = admin._optional_json()
            assert isinstance(result, dict), f"Expected dict for input {raw!r}, got {type(result)}"
