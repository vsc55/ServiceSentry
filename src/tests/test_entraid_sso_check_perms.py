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


class TestWhatTheAppIsRegisteredWith:
    """One declaration, two spellings of the same permission."""

    def test_the_name_and_the_id_live_together(self):
        """The id is what a grant is written with; the name is what a token claim carries
        and therefore all a check can read. Keeping them apart is how a check ends up
        verifying a permission the registration never asked for."""
        assert SSO_APP_ROLES == ('Group.Read.All',)
        assert GROUP_READ_ALL == '5b567255-7703-4780-807c-7be8301ae99b'

    def test_the_saml2_registration_grants_exactly_that(self):
        """The SAML2 wizard writes the id directly — this pins the pair together."""
        import io                                              # noqa: PLC0415
        import os                                              # noqa: PLC0415
        src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'lib', 'providers', 'entraid', 'provision_saml.py'),
                      encoding='utf-8-sig').read()
        assert 'GROUP_READ_ALL' in src


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


class TestTheButtons:

    @pytest.mark.parametrize('section', ['oidc', 'saml2'])
    def test_the_section_offers_the_button(self, section):
        from lib.config.config_actions import actions_for       # noqa: PLC0415
        act = next((a for a in actions_for(section) if a['id'] == 'check_perms'), None)
        assert act, f'{section} has no check-permissions button'
        assert act['fn'] == 'checkEntraSsoPermissions'
        assert act['label_key'] == 'entra_check_perms'

    @pytest.mark.parametrize('section', ['oidc', 'saml2'])
    def test_it_only_shows_once_there_is_an_app(self, section):
        """Nothing to check before the app is registered — and the field it keys off is
        the one that section's own registration fills in."""
        from lib.config.config_actions import actions_for       # noqa: PLC0415
        act = next(a for a in actions_for(section) if a['id'] == 'check_perms')
        expected = 'client_id' if section == 'oidc' else 'graph_secret'
        assert act['show_when'] == {'field': expected, 'not_empty': True}

    def test_one_handler_serves_both_sections(self):
        """The panel passes the section id to a config action, so a package writes one
        function instead of a near-identical wrapper per section."""
        import io                                                # noqa: PLC0415
        import os                                                # noqa: PLC0415
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        render = io.open(os.path.join(base, 'lib', 'web_admin', 'templates', 'partials',
                                      'cfg', '_render.html'), encoding='utf-8-sig').read()
        # Matched WITHOUT the closing paren on purpose: what this guards is that the section
        # is passed at all, not how many arguments follow it. Pinning the exact call shape
        # made it fail the day maintenance actions started receiving the button element too —
        # a guard that breaks on an added argument is reporting the wrong thing.
        assert '${escAttr(a.fn)}(${jsStr(sec)}' in render, \
            'config actions are called with no argument again — the shared handler would ' \
            'not know which section it was asked about'


class TestTheModalIsShared:
    """The checklist, the tick-by-tick rendering and how an answer is read are the same
    for a credential and for an auth section; only the source of the list differs."""

    def _read(self, *parts):
        import io                                                # noqa: PLC0415
        import os                                                # noqa: PLC0415
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return io.open(os.path.join(base, 'lib', 'web_admin', 'templates', *parts),
                       encoding='utf-8-sig').read()

    def test_there_is_one_renderer(self):
        assert 'async function showPermissionCheck(' in self._read(
            'partials', 'core', '_perm_check.html')

    def test_the_credentials_editor_uses_it(self):
        src = self._read('partials', 'credentials', '_modal.html')
        assert 'showPermissionCheck({' in src
        assert 'credPermCheckModal' not in src, 'the credentials editor kept its own copy'

    def test_a_caller_without_the_list_still_gets_a_checklist(self):
        """The auth sections do not hold the required list — it is declared server-side —
        so the renderer must build the rows from the answer instead of showing nothing."""
        src = self._read('partials', 'core', '_perm_check.html')
        assert 'if (!rows.length && (d.results || []).length)' in src
