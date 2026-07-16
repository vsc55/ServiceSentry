#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP security response headers (lib.security.headers) applied to responses."""

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


class TestSecurityHeaders:
    def test_headers_present_on_response(self, client):
        r = client.get('/login')
        h = r.headers
        assert h.get('X-Content-Type-Options') == 'nosniff'
        assert h.get('X-Frame-Options') == 'DENY'
        assert h.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
        assert 'camera=()' in h.get('Permissions-Policy', '')
        csp = h.get('Content-Security-Policy', '')
        assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp

    def test_setdefault_does_not_override_proxy(self):
        # apply_security_headers must not clobber a header already set upstream.
        from lib.security.headers import apply_security_headers

        class _Resp:
            def __init__(self):
                self.headers = {'X-Frame-Options': 'SAMEORIGIN'}
        r = apply_security_headers(_Resp())
        assert r.headers['X-Frame-Options'] == 'SAMEORIGIN'      # preserved
        assert r.headers['X-Content-Type-Options'] == 'nosniff'  # added


class TestFrameAncestors:
    def test_allowlist_opens_frame_ancestors_and_drops_xfo(self):
        from lib.security.headers import apply_security_headers

        class _H(dict):
            def setdefault(self, k, v):
                return dict.setdefault(self, k, v)

            def pop(self, k, d=None):
                return dict.pop(self, k, d)

        class _Resp:
            def __init__(self):
                self.headers = _H()
        r = apply_security_headers(_Resp(), frame_ancestors=['https://teams.microsoft.com'])
        csp = r.headers['Content-Security-Policy']
        assert "frame-ancestors 'self' https://teams.microsoft.com" in csp
        assert 'X-Frame-Options' not in r.headers          # can't express an allowlist → dropped

    def test_no_allowlist_keeps_framing_blocked(self):
        from lib.security.headers import apply_security_headers

        class _Resp:
            def __init__(self):
                self.headers = {}
        r = apply_security_headers(_Resp())
        assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
        assert r.headers['X-Frame-Options'] == 'DENY'

    def test_build_csp_with_origins(self):
        from lib.security.headers import build_csp
        csp = build_csp(['https://embed.example.com', 'https://*.example.org'])
        assert "frame-ancestors 'self' https://embed.example.com https://*.example.org" in csp


class TestDiscoveryMechanism:
    """The GENERIC discovery machinery (core). Which specific prefixes/origins each provider
    declares is asserted in that provider's own test file."""

    def test_register_csrf_exempt_dedup(self, admin):
        saved = admin._csrf_exempt_prefixes
        try:
            admin._register_csrf_exempt('/zz-test/', '/zz-test/', '')
            assert '/zz-test/' in admin._csrf_exempt_prefixes
            assert admin._csrf_exempt_prefixes.count('/zz-test/') == 1   # deduped, empties dropped
        finally:
            admin._csrf_exempt_prefixes = saved

    def test_register_embed_origins_gated_by_flag(self, admin):
        saved_p, saved_fa = admin._embed_profiles, admin._frame_ancestors_list
        try:
            admin._zz_flag = False
            admin._register_embed_origins('_zz_flag', 'https://embed.example.com')
            admin._recompute_frame_ancestors()
            assert 'https://embed.example.com' not in admin._frame_ancestors_list  # flag off
            admin._zz_flag = True
            admin._recompute_frame_ancestors()
            assert 'https://embed.example.com' in admin._frame_ancestors_list       # flag on
        finally:
            admin._embed_profiles, admin._frame_ancestors_list = saved_p, saved_fa

    def test_embed_cookie_policy_is_generic(self, admin):
        # SameSite=None; Secure iff the app is embeddable cross-site — driven by the effective
        # frame-ancestors allowlist, NOT any integration-specific flag.
        class _App:
            def __init__(self):
                self.config = {}
        app, saved = _App(), admin._frame_ancestors_list
        try:
            admin._frame_ancestors_list = ['https://embed.example.com']
            admin._apply_embed_cookie_policy(app)
            assert app.config['SESSION_COOKIE_SAMESITE'] == 'None'
            assert app.config['SESSION_COOKIE_SECURE'] is True
            admin._frame_ancestors_list = []
            admin._apply_embed_cookie_policy(app)
            assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
        finally:
            admin._frame_ancestors_list = saved


class TestCsrfModule:
    def test_issue_and_validate(self):
        from lib.security import csrf

        sess = {}
        tok = csrf.issue_token(sess)
        assert tok and sess[csrf.SESSION_KEY] == tok
        assert csrf.issue_token(sess) == tok      # stable within a session

        class _Req:
            def __init__(self, headers=None, form=None):
                self.headers = headers or {}
                self.form = form or {}
        assert csrf.is_valid(_Req(headers={csrf.HEADER_NAME: tok}), sess)
        assert csrf.is_valid(_Req(form={csrf.FORM_FIELD: tok}), sess)
        assert not csrf.is_valid(_Req(headers={csrf.HEADER_NAME: 'wrong'}), sess)
        assert not csrf.is_valid(_Req(), sess)                 # no token sent
        assert not csrf.is_valid(_Req(headers={csrf.HEADER_NAME: 'x'}), {})  # no session token

    def test_needs_check(self):
        from lib.security import csrf

        exempt = ('/scim/', '/auth/saml2/acs')
        assert csrf.needs_check('POST', '/api/v1/config', exempt)
        assert not csrf.needs_check('GET', '/api/v1/config', exempt)
        assert not csrf.needs_check('POST', '/scim/v2/Users', exempt)
        assert not csrf.needs_check('DELETE', '/auth/saml2/acs', exempt)
