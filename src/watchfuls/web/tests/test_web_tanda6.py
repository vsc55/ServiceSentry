#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regressions for watchfuls/web from the second 2026-10-12 audit (WF-4).

urllib followed every redirect: a check that EXPECTS a 301 could never see one, and a 302
to the cloud metadata address was fetched although the SSRF guard refuses that address as
a first URL (``content_contains`` then made the answer an oracle). A loopback HTTP server
stands in for the remote one; nothing leaves this machine.
"""

import http.server
import threading

import pytest

from watchfuls.web import Watchful

_SEEN = []


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        _SEEN.append((self.path, self.headers.get('Authorization')))
        port = self.server.server_address[1]
        if self.path == '/old':
            self.send_response(301)
            self.send_header('Location', '/new')
            self.end_headers()
        elif self.path == '/meta':
            self.send_response(302)
            self.send_header('Location', 'http://169.254.169.254/latest/meta-data/')
            self.end_headers()
        elif self.path == '/other-host':
            # Same server, another host name: the credentials must not travel.
            self.send_response(302)
            self.send_header('Location', f'http://localhost:{port}/new')
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'hello')

    def log_message(self, *_a):
        pass


@pytest.fixture(scope='module')
def server():
    srv = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f'127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()
    srv.server_close()


class TestExpectedRedirect:

    def test_expected_301_is_seen(self, server):
        res = Watchful.test_connection({'server': f'{server}/old', 'scheme': 'http',
                                        'code': 301, 'timeout': 5})
        assert res['ok'] is True, res

    def test_expected_200_still_follows(self, server):
        res = Watchful.test_connection({'server': f'{server}/old', 'scheme': 'http',
                                        'code': 200, 'timeout': 5})
        assert res['ok'] is True, res

    def test_request_without_follow_returns_the_3xx(self, server):
        code, detail = Watchful._web_request(f'{server}/old', 5, True, 'http',
                                             follow_redirects=False)
        assert code == 301 and detail == 'HTTP 301'


class TestRedirectSsrf:

    def test_redirect_to_metadata_is_blocked(self, server):
        code, detail = Watchful._web_request(f'{server}/meta', 3, True, 'http')
        assert code == 0
        assert detail.startswith('Blocked:') and '169.254.169.254' in detail

    def test_content_oracle_gets_nothing(self, server):
        code, detail = Watchful._web_request(f'{server}/meta', 3, True, 'http', 'GET',
                                             True, 'ami-id')
        assert code == 0 and detail.startswith('Blocked:')

    def test_basic_auth_does_not_follow_to_another_host(self, server):
        _SEEN.clear()
        code, _detail = Watchful._web_request(f'{server}/other-host', 5, True, 'http',
                                              auth_user='u', auth_password='p')
        assert code == 200
        assert _SEEN[0][1] is not None            # sent to the host it was set for
        assert _SEEN[-1] == ('/new', None)         # not to the one it was sent on to


def test_the_redirect_ceiling_is_the_configured_one():
    """One configurable number for every guarded fetch: the web check used urllib's 10 unsaid."""
    from lib.security import net_guard
    from watchfuls.web import _GuardedRedirect
    try:
        net_guard.set_max_redirects(3)
        assert _GuardedRedirect(True).max_redirections == 3
    finally:
        net_guard.set_max_redirects(net_guard.MAX_REDIRECTS)
