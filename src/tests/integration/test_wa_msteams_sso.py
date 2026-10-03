#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Teams personal-tab SSO: the /auth/msteams/tab entry page and the
/auth/msteams/sso token sign-in endpoint (token validation + user mapping)."""

import unittest.mock

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    from lib.providers.entraid import sso_routes
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')

_CLAIMS = {'preferred_username': 'sso.user@example.com', 'oid': 'aad-oid-1',
           'name': 'SSO User', 'iss': 'https://login.microsoftonline.com/tid/v2.0'}


def _add_sso_user(admin, *, username='sso.user@example.com', email='sso.user@example.com',
                  source='oidc', enabled=True):
    admin._users[username] = {
        'uid': 'u-sso-1', 'auth_source': source, 'email': email,
        'role': 'viewer', 'display_name': 'SSO User', 'enabled': enabled, 'groups': [],
    }


# ─────────────────────────── /auth/msteams/tab entry page ─────────────────────────
class TestTabPage:
    def test_renders_with_sdk_and_framing_csp(self, client):
        r = client.get('/auth/msteams/tab')
        assert r.status_code == 200
        assert b'res.cdn.office.net' in r.data                      # loads the Teams SDK
        csp = r.headers.get('Content-Security-Policy', '')
        assert 'https://res.cdn.office.net' in csp                  # allowed in script-src
        assert "frame-ancestors 'self' https://teams.microsoft.com" in csp
        assert 'X-Frame-Options' not in r.headers                   # framing allowed → dropped

    def test_public_no_login_required(self, client):
        assert client.get('/auth/msteams/tab').status_code == 200          # not gated


# ─────────────────────────── user mapping helper ───────────────────────────
class TestResolveUser:
    def test_match_by_username(self, admin):
        _add_sso_user(admin, username='sso.user@example.com')
        uname, user = sso_routes._resolve_user(admin, _CLAIMS)
        assert uname == 'sso.user@example.com' and user is not None

    def test_match_by_email(self, admin):
        admin._users['jdoe'] = {'uid': 'x', 'auth_source': 'oidc',
                                'email': 'sso.user@example.com', 'role': 'viewer', 'enabled': True}
        uname, user = sso_routes._resolve_user(admin, _CLAIMS)
        assert uname == 'jdoe'

    def test_no_match(self, admin):
        uname, user = sso_routes._resolve_user(admin, _CLAIMS)
        assert uname is None and user is None


# ─────────────────────────── /auth/msteams/sso ────────────────────────
class TestSsoEndpoint:
    def test_no_token_400(self, client):
        assert client.post('/auth/msteams/sso', json={}).status_code == 400

    def test_unavailable_501_when_no_pyjwt(self, client):
        # Real state: PyJWT not installed → refuse rather than trust the token.
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=False):
            r = client.post('/auth/msteams/sso', json={'token': 'x'})
        assert r.status_code == 501

    def test_invalid_token_401(self, admin, client):
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=True), \
             unittest.mock.patch.object(sso_routes.tab_sso, 'validate_tab_token',
                                        side_effect=ValueError('bad token')):
            r = client.post('/auth/msteams/sso', json={'token': 'x'})
        assert r.status_code == 401

    def test_unknown_user_403(self, admin, client):
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=True), \
             unittest.mock.patch.object(sso_routes.tab_sso, 'validate_tab_token', return_value=_CLAIMS):
            r = client.post('/auth/msteams/sso', json={'token': 'x'})
        assert r.status_code == 403

    def test_local_account_rejected(self, admin, client):
        _add_sso_user(admin, source='local')
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=True), \
             unittest.mock.patch.object(sso_routes.tab_sso, 'validate_tab_token', return_value=_CLAIMS):
            r = client.post('/auth/msteams/sso', json={'token': 'x'})
        assert r.status_code == 403                                 # anti-takeover guard

    def test_disabled_user_rejected(self, admin, client):
        _add_sso_user(admin, enabled=False)
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=True), \
             unittest.mock.patch.object(sso_routes.tab_sso, 'validate_tab_token', return_value=_CLAIMS):
            r = client.post('/auth/msteams/sso', json={'token': 'x'})
        assert r.status_code == 403

    def test_success_establishes_session(self, admin, client):
        _add_sso_user(admin)
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=True), \
             unittest.mock.patch.object(sso_routes.tab_sso, 'validate_tab_token', return_value=_CLAIMS):
            r = client.post('/auth/msteams/sso', json={'token': 'x'})
        assert r.status_code == 200
        d = r.get_json()
        assert d['ok'] is True and d.get('redirect')
        # session established → an authenticated endpoint now works without a form login
        assert client.get('/api/v1/me').status_code == 200


def test_msteams_sso_csrf_and_embed_declared(admin):
    # The entraid provider (Teams SSO) declares its CSRF-exempt paths AND the Teams embed origins.
    px = admin._csrf_exempt_prefixes
    assert '/auth/msteams/tab' in px and '/auth/msteams/sso' in px
    profiles = dict(admin._embed_profiles)
    assert '_EMBED_IN_TEAMS' in profiles
    assert 'https://teams.microsoft.com' in profiles['_EMBED_IN_TEAMS']


# ─────────────────────────── the refusals the other doors make ───────────────────────
class TestTheSameRefusalsAsOidcAndSaml:
    """The Teams door skipped two checks the OIDC and SAML callbacks make: a no-login
    (service) account and a reserved built-in name both got a full session through it."""

    def _post(self, client, claims=_CLAIMS):
        with unittest.mock.patch.object(sso_routes.tab_sso, 'available', return_value=True), \
             unittest.mock.patch.object(sso_routes.tab_sso, 'validate_tab_token',
                                        return_value=claims):
            return client.post('/auth/msteams/sso', json={'token': 'x'})

    def test_a_no_login_account_is_refused(self, admin, client):
        _add_sso_user(admin)
        admin._users['sso.user@example.com']['login_enabled'] = False
        r = self._post(client)
        assert r.status_code == 403
        with client.session_transaction() as s:
            assert not s.get('logged_in')

    def test_a_reserved_name_is_refused(self, admin, client):
        _add_sso_user(admin, username='system', email='sso.user@example.com')
        r = self._post(client)
        assert r.status_code == 403
        with client.session_transaction() as s:
            assert not s.get('logged_in')


class TestTheObjectIdNamesThePerson:
    """A UPN or a mail address is a label the directory can rename and reassign; the `oid`
    is the person. An account bound to the oid is found by it first."""

    def test_an_account_bound_to_the_oid_wins_over_a_upn_match(self, admin):
        _add_sso_user(admin)                                      # matches by UPN
        admin._users['the-real-one'] = {'uid': 'u-real', 'auth_source': 'entraid',
                                        'auth_source_id': 'AAD-OID-1', 'email': '',
                                        'role': 'viewer', 'enabled': True, 'groups': []}
        uname, _user = sso_routes._resolve_user(admin, _CLAIMS)
        assert uname == 'the-real-one'

    def test_a_local_account_is_never_matched_by_oid(self, admin):
        admin._users['loc'] = {'uid': 'u-loc', 'auth_source': 'local',
                               'auth_source_id': 'aad-oid-1', 'enabled': True}
        uname, _user = sso_routes._resolve_user(admin, _CLAIMS)
        assert uname is None
