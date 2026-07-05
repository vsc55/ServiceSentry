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
