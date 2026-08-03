#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A crash inside a handler leaves a record, and the record can be found from the screen.

Asked after a real one: "why do these errors not get recorded in the audit or the console?
All you see is 'Error al guardar', which gives you nothing." Nothing recorded them, at any
of the four points where something could have:

* Flask answered the unhandled exception with its own 500 page;
* ``after_request`` does NOT run on that path, so the per-endpoint trace line — the one that
  logs every 4xx/5xx with its reason — never fired;
* the traceback went to Flask's logger, which this panel wires into neither its debug output
  nor its log file, so under a service or a container it went where nobody looks;
* the audit was never written, because no code wrote it.

And the client discarded what little survived: an HTML error body threw inside ``r.json()``
and landed in the same ``catch`` as a dropped connection, returning the same ``null`` — so
the toast printed ``r?.error`` on a value with no error to print.

The fix is one reference code appearing in three places at once — the log line, the audit
entry, and the message on screen — so a user can read a short code off a toast and somebody
else can find the endpoint and the exception. What the response must NOT carry is the
traceback: an error page is not where internals get published to whoever can reach the URL.


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_wa_unhandled_errors.py`` lives in ``tests/unit/test_wa_unhandled_errors.py``."""

import os
import re

import pytest

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
API = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_api.html')

_REF = re.compile(r'ref: ([0-9a-f]{8})')


@pytest.fixture
def crashing(admin, client):
    """Register a route that raises, with propagation off — production's setting.

    Under pytest Flask propagates exceptions (TESTING), which the handler reproduces
    deliberately so a crash in the suite still shows its traceback. Turning it off here is
    what lets this test see the response a browser would get.
    """
    app = client.application
    prev = app.config.get('PROPAGATE_EXCEPTIONS')
    app.config['PROPAGATE_EXCEPTIONS'] = False

    @app.route('/api/v1/__boom__', methods=['GET'])
    def _boom():                                       # noqa: ANN202
        raise RuntimeError('the thing that went wrong')

    yield client
    app.config['PROPAGATE_EXCEPTIONS'] = prev


class TestTheResponseSaysSomethingUsable:

    def test_an_api_crash_answers_json_not_an_html_page(self, crashing):
        """The whole client-side blackout started here: an HTML body cannot be parsed, and
        the wrapper that fails to parse it cannot tell a crash from a dead network."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(crashing)
        r = crashing.get('/api/v1/__boom__')
        assert r.status_code == 500
        assert r.is_json, f'still not JSON: {r.data[:200]}'
        assert r.get_json().get('error'), 'a 500 with no error message to show'

    def test_the_message_carries_a_reference(self, crashing):
        from tests.conftest import _login                        # noqa: PLC0415
        _login(crashing)
        body = crashing.get('/api/v1/__boom__').get_json()
        assert _REF.search(body['error']), f'no reference to quote: {body["error"]}'
        assert body.get('ref'), 'the reference is only in the prose, not readable as a field'

    def test_the_traceback_never_reaches_the_client(self, crashing):
        """The reference exists precisely so this does not have to."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(crashing)
        raw = crashing.get('/api/v1/__boom__').data.decode('utf-8', 'replace')
        assert 'Traceback' not in raw
        assert 'the thing that went wrong' not in raw, \
            'the exception message is being echoed to whoever hit the URL'
        assert '_boom' not in raw


class TestTheCrashIsAudited:

    def test_an_entry_is_written(self, admin, crashing):
        from tests.conftest import _login                        # noqa: PLC0415
        _login(crashing)
        crashing.get('/api/v1/__boom__')
        assert [e for e in admin._audit_log if e['event'] == 'internal_error'], \
            'the crash left no audit entry at all'

    def test_the_entry_says_what_broke_and_where(self, admin, crashing):
        from tests.conftest import _login                        # noqa: PLC0415
        _login(crashing)
        crashing.get('/api/v1/__boom__')
        d = [e for e in admin._audit_log if e['event'] == 'internal_error'][-1]['detail']
        assert d['path'] == '/api/v1/__boom__'
        assert d['method'] == 'GET'
        assert d['exception'] == 'RuntimeError'
        assert 'the thing that went wrong' in d['message']

    def test_the_reference_on_screen_finds_the_entry(self, admin, crashing):
        """The one property the whole design rests on: a user reads a code off a toast and
        somebody else can locate the endpoint and the exception from it."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(crashing)
        shown = crashing.get('/api/v1/__boom__').get_json()['error']
        ref = _REF.search(shown).group(1)
        entry = [e for e in admin._audit_log if e['event'] == 'internal_error'][-1]
        assert entry['detail']['ref'] == ref, 'the code on screen matches no record'


class TestOrdinaryRejectionsAreNotTreatedAsCrashes:

    def test_a_404_is_not_audited(self, admin, crashing):
        """A 404 is an ANSWER, not a fault. Auditing every probe for /wp-admin would bury
        the real entries under scanner traffic — the exact opposite of the point."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(crashing)
        before = len([e for e in admin._audit_log if e['event'] == 'internal_error'])
        assert crashing.get('/api/v1/__nothing_here__').status_code == 404
        after = len([e for e in admin._audit_log if e['event'] == 'internal_error'])
        assert after == before

    def test_an_abort_keeps_its_own_status(self, crashing):
        """HTTPException is returned untouched. `abort(403)` is how the routes reject a
        permission failure, and rewriting one into a generic 500 would replace "you may not
        do this" with "something broke" — a different problem, sent to a different person."""
        from flask import abort                                  # noqa: PLC0415
        from tests.conftest import _login                        # noqa: PLC0415
        app = crashing.application

        @app.route('/api/v1/__denied__', methods=['GET'])
        def _denied():                                 # noqa: ANN202
            abort(403)

        _login(crashing)
        assert crashing.get('/api/v1/__denied__').status_code == 403


class TestTheSuiteStillSeesItsTracebacks:

    def test_pytest_still_gets_the_raise(self, client):
        """Registering a handler for Exception overrides PROPAGATE_EXCEPTIONS, so the handler
        reproduces Flask's default itself. Without that, every crash in the suite would turn
        into a tidy 500 response and stop failing tests the way a crash should."""
        app = client.application

        @app.route('/api/v1/__boom2__', methods=['GET'])
        def _boom2():                                  # noqa: ANN202
            raise RuntimeError('still raised')

        from tests.conftest import _login                        # noqa: PLC0415
        _login(client)
        with pytest.raises(RuntimeError, match='still raised'):
            client.get('/api/v1/__boom2__')


