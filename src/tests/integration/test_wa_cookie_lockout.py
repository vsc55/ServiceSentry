#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A setting must not make the panel impossible to log into.

Two of them could, and both failed the same way: an endless bounce between ``/login`` and
``/``. Every login succeeded — the credentials were right, the session was created — and the
browser then arrived at the next page with no session at all, because the cookie carrying it
had been thrown away on arrival. Nothing on screen said so; the panel simply became
unreachable, including the page where you would turn the setting back off.

**Secure cookies over plain HTTP.** A browser drops a ``Secure`` cookie on ``http://``. The
session config is careful about this for ``public_url`` — a canonical external URL is not a
statement that every request is HTTPS — but the *embed* policy set ``Secure`` unconditionally
the moment any frame-ancestor origin was allowed (turning on the Teams embed was enough).
That trade never paid: a cross-site iframe needs ``SameSite=None``, browsers refuse
``SameSite=None`` without ``Secure``, and they refuse ``Secure`` over HTTP — so on an http://
deployment the policy could not enable the embed either. It only broke login.

**A redirect to itself.** ``force_fqdn`` compared ``request.host`` (which carries the port)
against a public URL that need not, so ``192.168.0.1:8080`` read as a different host from
``192.168.0.1`` and the browser was sent to port 80. The setting is about the *hostname* you
arrived on, and a redirect that lands back where it started loops forever.

The shape of both rules is the same, and it is the point of this file: **a security setting
that cannot take effect must not take half of it.** Refusing to redirect, or leaving the
cookie usable, is always better than a lockout — the worst case is that the hardening does
not apply, which is where you already were.
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False


@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestTheSessionCookieStaysUsableOverPlainHttp:

    def _policy(self, wa, *, ancestors, secure_cookies=False, force_https=False):
        wa._frame_ancestors_list = list(ancestors)
        wa._SECURE_COOKIES = secure_cookies
        wa._FORCE_HTTPS = force_https
        wa._apply_embed_cookie_policy(wa._app)
        return (wa._app.config['SESSION_COOKIE_SAMESITE'],
                wa._app.config['SESSION_COOKIE_SECURE'])

    def test_no_embed_no_https_keeps_the_cookie_usable(self, admin):
        assert self._policy(admin, ancestors=[]) == ('Lax', False)

    def test_allowing_an_iframe_origin_does_not_break_plain_http_login(self, admin):
        """**The lockout.** Turning on the Teams embed marked the cookie Secure; on an
        http:// deployment the browser then dropped it, every login bounced straight back to
        the login page, and the setting that caused it was two clicks away behind that login."""
        assert self._policy(admin, ancestors=['https://teams.microsoft.com']) == ('Lax', False)

    def test_with_https_the_embed_policy_applies(self, admin):
        """It is not disabled — it is conditional on the one thing that makes it work."""
        assert self._policy(admin, ancestors=['https://teams.microsoft.com'],
                            force_https=True) == ('None', True)
        assert self._policy(admin, ancestors=['https://teams.microsoft.com'],
                            secure_cookies=True) == ('None', True)

    def test_an_https_intent_alone_still_marks_it_secure(self, admin):
        assert self._policy(admin, ancestors=[], force_https=True) == ('Lax', True)
        assert self._policy(admin, ancestors=[], secure_cookies=True) == ('Lax', True)

    def test_the_impossible_combination_is_reported(self, admin, monkeypatch):
        """An embed that cannot work must not fail silently: the admin allowed an origin and
        is entitled to know why nothing happened."""
        seen = []
        monkeypatch.setattr(admin, '_dbg', lambda msg, *a, **k: seen.append(msg))
        self._policy(admin, ancestors=['https://teams.microsoft.com'])
        assert any('frame-ancestors' in m for m in seen), \
            'the embed was silently ignored'


@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestForcingTheDomainCannotLoop:

    def _get(self, admin, client, *, public_url, host, force_https=False):
        admin._FORCE_FQDN = True
        admin._PUBLIC_URL = public_url
        admin._FORCE_HTTPS = force_https
        return client.get('/login', headers={'Host': host})

    def test_a_different_hostname_is_redirected(self, admin, client):
        r = self._get(admin, client, public_url='ss.example.com', host='192.168.0.1:8080')
        assert r.status_code == 302
        assert r.headers['Location'] == 'http://ss.example.com/login'

    def test_the_query_string_survives(self, admin, client):
        admin._FORCE_FQDN = True
        admin._PUBLIC_URL = 'ss.example.com'
        r = client.get('/login?next=%2Fusers', headers={'Host': '10.0.0.9'})
        assert r.headers['Location'].endswith('/login?next=%2Fusers')

    def test_a_public_url_without_a_port_accepts_any_port(self, admin, client):
        """**The loop.** `request.host` carries the port and the public URL need not, so
        `192.168.0.1:8080` read as a different host from `192.168.0.1` and the browser was
        sent to port 80 — where nothing is listening, or worse, something that bounces
        back. The setting is about the hostname you arrived on."""
        r = self._get(admin, client, public_url='192.168.0.1', host='192.168.0.1:8080')
        assert r.status_code != 302, 'redirected over a port difference'

    def test_a_named_port_is_still_honoured(self, admin, client):
        """Naming one means it matters — a request on another port is a different address."""
        r = self._get(admin, client, public_url='ss.example.com:8443',
                      host='ss.example.com:9999')
        assert r.status_code == 302
        assert r.headers['Location'] == 'http://ss.example.com:8443/login'

    def test_the_comparison_ignores_case(self, admin, client):
        r = self._get(admin, client, public_url='ss.example.com', host='SS.Example.COM')
        assert r.status_code != 302

    def test_it_never_redirects_to_the_request_it_is_answering(self, admin, client):
        """Belt and braces: whatever combination gets here, a target identical to the current
        URL is a loop the browser will follow forever."""
        r = self._get(admin, client, public_url='192.168.0.1:8080', host='other:8080')
        loc = r.headers.get('Location', '')
        assert loc != 'http://other:8080/login'

    def test_it_does_nothing_while_switched_off(self, admin, client):
        admin._FORCE_FQDN = False
        admin._PUBLIC_URL = 'ss.example.com'
        assert client.get('/login', headers={'Host': '192.168.0.1:8080'}).status_code != 302

    def test_it_does_nothing_without_a_public_url(self, admin, client):
        admin._FORCE_FQDN = True
        admin._PUBLIC_URL = ''
        assert client.get('/login', headers={'Host': '192.168.0.1:8080'}).status_code != 302
