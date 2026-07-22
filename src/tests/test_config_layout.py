#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The config UI layout (lib.config.layout) must stay coherent with the registry."""

import pytest

from lib.config.layout import config_layout, TABS, CARDS

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False


class TestLayoutCoherence:

    def test_tabs_and_cards_present(self):
        lay = config_layout()
        assert lay['tabs'] and lay['cards']
        assert all('id' in t and 'label_key' in t and 'icon' in t for t in lay['tabs'])

    def test_every_card_targets_a_real_tab(self):
        tab_ids = {t['id'] for t in TABS}
        for c in CARDS:
            assert c['tab'] in tab_ids, f"card {c['id']} → unknown tab {c['tab']}"

    def test_card_is_generic_xor_bespoke(self):
        # config_layout() derives `fields` for generic cards from the spec; each card
        # ends up with exactly one of fields (generic) / renderer (bespoke).
        for c in config_layout()['cards']:
            assert ('fields' in c) ^ ('renderer' in c), \
                f"card {c['id']} must have exactly one of fields/renderer"

    def test_generic_cards_are_not_empty(self):
        # A generic card (no renderer) must resolve to at least one field OR carry
        # contributed actions, else it is an empty card (typically a field that lost its
        # card= assignment). Actions alone are legitimate: the Maintenance card has no
        # fields of its own and is built entirely from what the domains contribute.
        for c in config_layout()['cards']:
            if 'renderer' not in c:
                assert c.get('fields') or c.get('actions'), \
                    f"generic card {c['id']} has neither fields nor actions"

    def test_generic_fields_exist_in_registry(self):
        from lib.config.spec import CONFIG_FIELDS
        paths = {f.path for f in CONFIG_FIELDS}
        for c in config_layout()['cards']:
            for f in c.get('fields', []):
                assert f in paths, f"card {c['id']}: field {f} not in the registry"

    def test_no_field_placed_in_two_cards(self):
        seen = {}
        for c in config_layout()['cards']:
            for f in c.get('fields', []):
                assert f not in seen, f"field {f} in cards {seen[f]} and {c['id']}"
                seen[f] = c['id']

    def test_card_ids_unique(self):
        ids = [c['id'] for c in CARDS]
        assert len(ids) == len(set(ids))


@pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")
class TestLayoutEndpoint:

    def test_requires_auth(self, client):
        assert client.get('/api/v1/config/layout').status_code == 401

    def test_returns_layout(self, client):
        from tests.conftest import _login
        _login(client)
        r = client.get('/api/v1/config/layout')
        assert r.status_code == 200
        data = r.get_json()
        assert {t['id'] for t in data['tabs']} >= {'general', 'monitoring', 'auth'}
        assert any(c.get('renderer') == 'database' for c in data['cards'])
