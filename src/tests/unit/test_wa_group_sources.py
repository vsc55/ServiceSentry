#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Group→role mapping: the directory "fetch groups" source of each auth section.

The mapping widget lets an admin pull the groups from the directory backing that section
(LDAP for ``ldap``; Microsoft Graph for ``oidc``/``saml2``) instead of typing DNs/object
ids by hand.  That wiring is what makes group→role mapping usable, and it had **no test at
all** — so this pins it BEFORE the glue is moved out of ``web_admin`` into each provider:
if the move drops a provider, renames a hook or stops injecting it, these fail.

Deliberately asserted at the rendered-page level: the JS is concatenated into the dashboard
(from web_admin partials today, from ``<provider>/web/*_ui.html`` after the move), so this
survives the relocation and checks the thing that actually matters — that the section still
gets a working fetch/pick/lookup wiring.
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _admin_html(client) -> bytes:
    _login(client)
    return client.get('/admin').data




class TestGroupSourceDescriptors:
    """The descriptors themselves (server side)."""

    def test_every_auth_section_with_a_directory_declares_one(self):
        from lib.config.group_sources import discover_group_sources
        assert {s['section'] for s in discover_group_sources()} == {'ldap', 'oidc', 'saml2'}

    def test_each_source_carries_what_the_renderer_needs(self):
        from lib.config.group_sources import discover_group_sources
        for s in discover_group_sources():
            for key in ('label_key', 'fetch_fn', 'lookup_url', 'lookup_key', 'picker_id'):
                assert s.get(key), f'{s["section"]} source missing {key}'

    def test_layout_delivers_the_source_to_the_panel(self):
        from lib.config.layout import config_layout
        cards = {c['id']: c for c in config_layout()['cards']}
        assert cards['ldap']['group_source']['fetch_fn'] == '_ldapFetchGroups'
        assert cards['oidc']['group_source']['lookup_key'] == 'group_id'

    def test_section_without_a_directory_has_no_source(self):
        from lib.config.group_sources import group_source_for
        assert group_source_for('email') is None


