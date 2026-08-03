#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP security response headers (lib.security.headers) applied to responses.

Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_headers.py`` lives in ``tests/integration/test_wa_headers.py``."""



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
