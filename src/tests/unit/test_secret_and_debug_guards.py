#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Three small guards from the 2026-10-12 audit, tested where they are decided.

- A connection test uses the stored secret only against the stored destination
  (`lib.security.stored_secret`): pointed at a listener of one's own, the LDAP test sent the
  bind password in clear.
- An uploaded SVG is read as the browser reads it (`lib.core.brand.service.svg_problem`):
  `&#106;avascript:` passed the filter as bytes and became `javascript:` once parsed.
- `--verbose` alone no longer turns on Werkzeug's interactive debugger (`main._flask_debug`).
"""

from __future__ import annotations

import argparse
import os
import sys

from lib.core.brand.service import svg_problem
from lib.security.stored_secret import stored_secret_for

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]

_STORED = {'server': 'ldap.corp.example', 'port': 389, 'bind_dn': 'cn=svc,dc=corp',
           'bind_password': 'S3cret'}
_KEYS = ('server', 'port', 'bind_dn')


class TestStoredSecret:

    def test_the_stored_destination_gets_the_stored_secret(self):
        assert stored_secret_for({}, _STORED, 'bind_password', _KEYS) == 'S3cret'
        assert stored_secret_for({'server': 'LDAP.corp.example ', 'port': '389'}, _STORED,
                                 'bind_password', _KEYS) == 'S3cret'

    def test_another_destination_does_not(self):
        for cambio in ({'server': '127.0.0.1'}, {'port': 3890}, {'bind_dn': 'cn=other'}):
            assert stored_secret_for(cambio, _STORED, 'bind_password', _KEYS) == ''

    def test_a_secret_that_is_sent_is_used_as_sent(self):
        assert stored_secret_for({'server': 'x', 'bind_password': 'mine'}, _STORED,
                                 'bind_password', _KEYS) == 'mine'


class TestSvgFilter:

    def test_character_references_and_whitespace_do_not_hide_a_javascript_url(self):
        assert svg_problem(b'<svg><a href="&#106;avascript:alert(1)"><rect/></a></svg>')
        assert svg_problem(b'<svg><a href="&#x6A;avascript:alert(1)"><rect/></a></svg>')
        assert svg_problem(b'<svg><a href="java\tscript:alert(1)"><rect/></a></svg>')
        assert svg_problem(b'<svg><a href="javascript&colon;alert(1)"><rect/></a></svg>')

    def test_an_ordinary_picture_passes(self):
        assert svg_problem(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1"/>'
                           b'<text>A &amp; B</text></svg>') == ''


class TestFlaskDebug:

    def _main(self):
        if _SRC not in sys.path:
            sys.path.insert(0, _SRC)
        import main                                                 # noqa: PLC0415
        return main

    def test_verbose_alone_is_not_the_debugger(self, monkeypatch):
        monkeypatch.delenv('SS_FLASK_DEBUG', raising=False)
        assert self._main()._flask_debug(argparse.Namespace(verbose=True)) is False

    def test_the_watcher_turns_it_on(self, monkeypatch):
        monkeypatch.setenv('SS_FLASK_DEBUG', '1')
        m = self._main()
        assert m._flask_debug(argparse.Namespace(verbose=True)) is True
        assert m._flask_debug(argparse.Namespace(verbose=False)) is False
