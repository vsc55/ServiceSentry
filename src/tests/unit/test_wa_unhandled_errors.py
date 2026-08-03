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


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_unhandled_errors.py`` lives in
``tests/integration/test_wa_unhandled_errors.py``."""

import io
import os
import re


SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
API = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_api.html')

_REF = re.compile(r'ref: ([0-9a-f]{8})')


class TestTheClientStopsDiscardingTheAnswer:
    """`_readJson` is the fix for the other blackout: a non-JSON body used to throw on the
    parse and be caught beside a network failure, so status and body both vanished."""

    @staticmethod
    def _src() -> str:
        return io.open(API, encoding='utf-8-sig').read()

    def test_the_wrappers_do_not_parse_bare(self):
        src = self._src()
        for fn in ('apiPut', 'apiPost', 'apiDelete'):
            m = re.search(r'^async function ' + fn + r'\([^)]*\)\s*\{(.*?)^\}', src, re.S | re.M)
            assert m, f'{fn} is gone — update this guard with whatever replaced it'
            assert '_readJson' in m.group(1), f'{fn} parses the body bare again'
            assert 'await r.json()' not in m.group(1), \
                f'{fn} still has a bare r.json() that throws on an error page'

    def test_a_failed_call_is_logged_to_the_console(self):
        """The user's actual question was why nothing reached the console. Every wrapper
        answers for itself now, so a report of "it says failed" comes with something to
        paste."""
        src = self._src()
        assert src.count('console.error') >= 5, \
            'the wrappers went quiet again — a failure with no console line is unreportable'

    def test_the_non_json_path_still_yields_an_error_field(self):
        """Callers read `r.error` / `r.data.error`; returning null there is what produced a
        bare "Error al guardar" with nothing behind it."""
        m = re.search(r'^async function _readJson\([^)]*\)\s*\{(.*?)^\}',
                      self._src(), re.S | re.M)
        assert m, '_readJson is gone — update this guard with whatever replaced it'
        assert 'error:' in m.group(1), 'the non-JSON branch stopped producing an error field'
        assert 'r.status' in m.group(1), 'the status is being dropped again'
