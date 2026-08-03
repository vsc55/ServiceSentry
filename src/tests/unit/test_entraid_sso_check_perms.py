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


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_entraid_sso_check_perms.py`` lives in
``tests/integration/test_entraid_sso_check_perms.py``,
``tests/meta/test_entraid_sso_check_perms.py``."""

import pytest


from lib.providers.entraid.client import GROUP_READ_ALL, SSO_APP_ROLES

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
        src = io.open(os.path.join(os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0],
                                   'lib', 'providers', 'entraid', 'provision_saml.py'),
                      encoding='utf-8-sig').read()
        assert 'GROUP_READ_ALL' in src


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
        base = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        render = io.open(os.path.join(base, 'lib', 'web_admin', 'templates', 'partials',
                                      'cfg', '_render.html'), encoding='utf-8-sig').read()
        # Matched WITHOUT the closing paren on purpose: what this guards is that the section
        # is passed at all, not how many arguments follow it. Pinning the exact call shape
        # made it fail the day maintenance actions started receiving the button element too —
        # a guard that breaks on an added argument is reporting the wrong thing.
        assert '${escAttr(a.fn)}(${jsStr(sec)}' in render, \
            'config actions are called with no argument again — the shared handler would ' \
            'not know which section it was asked about'


