#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""""Check permissions" for the SSO sections (OIDC / SAML2).

The Credentials editor could already ask whether a module's Entra app holds the Graph
permissions it needs.  The SSO apps could not, and they are where the question bites
hardest: **consent is the half that fails silently.**  Registering the app succeeds, the
admin never presses "Grant admin consent", and nothing complains until Graph is actually
called — the group picker comes back empty, or a login maps no groups, with nothing saying
a consent is missing.

The check reads the ``roles`` claim of an app-only token: a permission that was requested
but never consented never reaches that claim, which is exactly the distinction being made.

Two properties matter more than the happy path, and both are about asking the RIGHT
question:

* the credentials are resolved by the same helper the group fetch uses, so the check tests
  the identity that is really used — SAML2's own app, never OIDC's;
* the required list is declared server-side, next to the id the registration grants, so
  the check cannot end up asking for something the register button never provisioned.
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.providers.entraid.client import GROUP_READ_ALL, SSO_APP_ROLES
from tests.conftest import _login

ROUTE = '/api/v1/auth/entraid/sso/check-permissions'




@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestTheRoute:

    def test_it_needs_config_edit(self, client):
        """It reads a stored client secret and talks to the tenant: an unauthenticated
        caller must not reach it."""
        assert client.post(ROUTE, json={'sec': 'oidc'}).status_code in (401, 403)

    def test_a_section_with_no_provider_url_says_so(self, admin, client):
        """No tenant can be derived, so there is nothing to sign in to. It answers rather
        than erroring — the modal shows the reason."""
        _login(client)
        r = client.post(ROUTE, json={'sec': 'oidc'})
        assert r.status_code == 200
        assert r.get_json()['ok'] is False

    def test_it_reports_missing_credentials_instead_of_failing(self, admin, client, monkeypatch):
        """A configured provider URL with no client secret is the state right after
        someone fills in the URL by hand."""
        _login(client)
        from lib.providers.entraid import auth                  # noqa: PLC0415
        monkeypatch.setattr(auth, 'tenant_from_provider_url', lambda _u: 'tenant-1')
        r = client.post(ROUTE, json={'sec': 'oidc', 'provider_url': 'https://login/tenant-1/v2.0'})
        d = r.get_json()
        assert r.status_code == 200 and d['ok'] is False and d['message']

    def test_a_granted_permission_reports_all_ok(self, admin, client, monkeypatch):
        _login(client)
        from lib.providers.entraid import auth                  # noqa: PLC0415
        from lib.providers.entraid import permissions           # noqa: PLC0415
        monkeypatch.setattr(auth, 'tenant_from_provider_url', lambda _u: 'tenant-1')
        monkeypatch.setattr(auth, 'app_token', lambda *a, **k: 'tok')
        monkeypatch.setattr(permissions, 'token_roles', lambda _t: ['Group.Read.All'])
        d = client.post(ROUTE, json={'sec': 'oidc', 'client_id': 'cid',
                                     'client_secret': 'sec',
                                     'provider_url': 'https://login/tenant-1/v2.0'}).get_json()
        assert d['ok'] and d['all_ok'] and d['variant'] == 'success'
        assert [x['priv'] for x in d['results']] == ['Group.Read.All']

    def test_a_requested_but_unconsented_permission_reports_missing(self, admin, client, monkeypatch):
        """**The case this exists for.** The app was registered, so it *requests* the
        permission — but without admin consent it never appears in the token, and every
        Graph call fails later with nothing pointing here."""
        _login(client)
        from lib.providers.entraid import auth                  # noqa: PLC0415
        from lib.providers.entraid import permissions           # noqa: PLC0415
        monkeypatch.setattr(auth, 'tenant_from_provider_url', lambda _u: 'tenant-1')
        monkeypatch.setattr(auth, 'app_token', lambda *a, **k: 'tok')
        monkeypatch.setattr(permissions, 'token_roles', lambda _t: [])
        d = client.post(ROUTE, json={'sec': 'oidc', 'client_id': 'cid',
                                     'client_secret': 'sec',
                                     'provider_url': 'https://login/tenant-1/v2.0'}).get_json()
        assert d['ok'] and not d['all_ok']
        assert d['missing'] == ['Group.Read.All'] and d['variant'] == 'warning'

    def test_a_failed_sign_in_is_reported_not_raised(self, admin, client, monkeypatch):
        _login(client)
        from lib.providers.entraid import auth                  # noqa: PLC0415

        def _boom(*_a, **_k):
            raise RuntimeError('invalid_client')
        monkeypatch.setattr(auth, 'tenant_from_provider_url', lambda _u: 'tenant-1')
        monkeypatch.setattr(auth, 'app_token', _boom)
        d = client.post(ROUTE, json={'sec': 'oidc', 'client_id': 'cid',
                                     'client_secret': 'sec',
                                     'provider_url': 'https://login/tenant-1/v2.0'}).get_json()
        assert d['ok'] is False and 'invalid_client' in d['message']

    def test_saml2_uses_its_own_app_never_oidc_s(self, admin, client, monkeypatch):
        """SAML2 has its own registration with its own graph secret. Borrowing OIDC's
        credentials would check an app nobody is using for SAML group lookups."""
        _login(client)
        seen = {}
        from lib.providers.entraid import auth                  # noqa: PLC0415
        from lib.providers.entraid import permissions           # noqa: PLC0415
        monkeypatch.setattr(auth, 'tenant_from_provider_url', lambda _u: 'tenant-1')
        monkeypatch.setattr(auth, 'app_token',
                            lambda t, cid, sec, *_a, **_k: seen.update(client_id=cid) or 'tok')
        monkeypatch.setattr(permissions, 'token_roles', lambda _t: ['Group.Read.All'])
        client.post(ROUTE, json={'sec': 'saml2', 'client_id': 'saml-app',
                                 'client_secret': 'saml-secret',
                                 'provider_url': 'https://login/tenant-1/v2.0'})
        assert seen.get('client_id') == 'saml-app'




