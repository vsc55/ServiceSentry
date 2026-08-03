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


Split by category: this file holds the structural guards (they read the repo's own source, docs
and templates); the rest of the original ``test_entraid_sso_check_perms.py`` lives in
``tests/unit/test_entraid_sso_check_perms.py``,
``tests/integration/test_entraid_sso_check_perms.py``."""


ROUTE = '/api/v1/auth/entraid/sso/check-permissions'


class TestTheModalIsShared:
    """The checklist, the tick-by-tick rendering and how an answer is read are the same
    for a credential and for an auth section; only the source of the list differs."""

    def _read(self, *parts):
        import io                                                # noqa: PLC0415
        import os                                                # noqa: PLC0415
        base = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
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
